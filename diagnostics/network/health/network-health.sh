#!/bin/bash

# =============================================================================
# network-health.sh — Cinesys Network Health Agent (macOS)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="$SCRIPT_DIR/clients.json"
REPORTS_DIR="$SCRIPT_DIR/reports"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
REPORT="$REPORTS_DIR/report_$TIMESTAMP.txt"
TMP_DIR=$(mktemp -d)
SPINNER_PID=""

cleanup() {
  [ -n "$SPINNER_PID" ] && kill "$SPINNER_PID" 2>/dev/null || true
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$REPORTS_DIR"
[ ! -f "$DB" ] && echo "[]" > "$DB"

for cmd in arp-scan nmap jq ping dig; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "  ✗  Missing dependency: $cmd — brew install $cmd"
    exit 1
  fi
done

NBTSCAN_AVAIL=false
command -v nbtscan &>/dev/null && NBTSCAN_AVAIL=true

# =============================================================================
# COLORS + UI
# =============================================================================
R='\033[0m'       # reset
BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[32m'
RED='\033[31m'
YELLOW='\033[33m'
CYAN='\033[36m'
WHITE='\033[97m'

SPIN_FRAMES=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')

spin_start() {
  local msg="$1"
  (
    local i=0
    while true; do
      printf "\r  ${DIM}%s${R}  %s" "${SPIN_FRAMES[$((i % 10))]}" "$msg"
      sleep 0.08
      ((i++)) || true
    done
  ) &
  SPINNER_PID=$!
}

spin_stop() {
  local msg="$1"
  [ -n "$SPINNER_PID" ] && kill "$SPINNER_PID" 2>/dev/null || true
  wait "$SPINNER_PID" 2>/dev/null || true
  SPINNER_PID=""
  printf "\r  ${GREEN}✓${R}  %-60s\n" "$msg"
}

spin_stop_warn() {
  local msg="$1"
  [ -n "$SPINNER_PID" ] && kill "$SPINNER_PID" 2>/dev/null || true
  wait "$SPINNER_PID" 2>/dev/null || true
  SPINNER_PID=""
  printf "\r  ${YELLOW}⚠${R}  %-60s\n" "$msg"
}

section() {
  local title="$1"
  printf "\n  ${BOLD}${WHITE}%s${R}\n" "$title"
  printf "  ${DIM}%s${R}\n" "──────────────────────────────────────────────────────────"
  log ""
  log "$title"
  log "──────────────────────────────────────────────────────────"
}

ok()   { printf "  ${GREEN}✓${R}  %s\n" "$1"; log "  ✓  $1"; }
warn() { printf "  ${YELLOW}⚠${R}  %s\n" "$1"; log "  ⚠  $1"; }
info() { printf "  ${DIM}·${R}  %s\n" "$1"; log "  ·  $1"; }
log()  { printf '%s\n' "$@" >> "$REPORT"; }

# =============================================================================
# INTERFACE DETECTION
# =============================================================================
detect_interface() {
  local current_iface=""
  while IFS= read -r line; do
    if [[ "$line" =~ ^(en[0-9]+): ]]; then
      current_iface="${BASH_REMATCH[1]}"
    elif [[ -n "$current_iface" && "$line" =~ inet[[:space:]]([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)[[:space:]]netmask[[:space:]](0x[0-9a-fA-F]+) ]]; then
      local ip="${BASH_REMATCH[1]}"
      local mask_hex="${BASH_REMATCH[2]#0x}"
      local mask_dec=$((16#$mask_hex))
      local cidr=0
      for i in {0..31}; do
        (( (mask_dec >> (31 - i)) & 1 )) && ((cidr++)) || true
      done
      IFS='.' read -r o1 o2 o3 o4 <<< "$ip"
      echo "$current_iface $ip $o1.$o2.$o3.0/$cidr"
      return
    fi
  done < <(ifconfig 2>/dev/null | grep -E "^en[0-9]+:|inet " | grep -v inet6)
}

IFACE_INFO=$(detect_interface)
if [ -z "$IFACE_INFO" ]; then
  printf "  ${RED}✗${R}  No active network interface found.\n"
  exit 1
fi
IFACE=$(echo "$IFACE_INFO" | awk '{print $1}')
LOCAL_IP=$(echo "$IFACE_INFO" | awk '{print $2}')
SUBNET=$(echo "$IFACE_INFO" | awk '{print $3}')
GATEWAY=$(route -n get default 2>/dev/null | awk '/gateway:/{print $2}' | head -1 || echo "unknown")

# =============================================================================
# HEADER
# =============================================================================
HEADER_DATE=$(date +"%Y-%m-%d  %H:%M:%S")
printf "\n"
printf "  ${BOLD}${WHITE}╭──────────────────────────────────────────────────────────╮${R}\n"
printf "  ${BOLD}${WHITE}│${R}  ${BOLD}Cinesys · Network Health${R}%-34s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}│${R}  ${DIM}%s${R}%-34s${BOLD}${WHITE}│${R}\n" "$HEADER_DATE" ""
printf "  ${BOLD}${WHITE}│${R}  ${DIM}%s  ·  %s  ·  %s${R}%-*s${BOLD}${WHITE}│${R}\n" "$IFACE" "$LOCAL_IP" "$SUBNET" "$((34 - ${#IFACE} - ${#LOCAL_IP} - ${#SUBNET} - 6))" ""
printf "  ${BOLD}${WHITE}╰──────────────────────────────────────────────────────────╯${R}\n"

log "======================================================"
log " Cinesys Network Health Report — $TIMESTAMP"
log "======================================================"
log " Interface : $IFACE"
log " Local IP  : $LOCAL_IP"
log " Subnet    : $SUBNET"
log " Gateway   : $GATEWAY"
log "======================================================"

# =============================================================================
# INTERNET + DNS HEALTH
# =============================================================================
section "Internet"

for target in "1.1.1.1" "8.8.8.8"; do
  result=$(ping -c 3 -W 1 "$target" 2>/dev/null | tail -1 || echo "")
  if echo "$result" | grep -q "avg"; then
    latency=$(echo "$result" | awk -F'/' '{print $5 "ms"}')
    printf "  ${GREEN}✓${R}  ${WHITE}%-14s${R}  ${DIM}%s${R}\n" "$target" "$latency"
    log "  ✓  $target  $latency"
  else
    printf "  ${RED}✗${R}  ${WHITE}%-14s${R}  ${RED}unreachable${R}\n" "$target"
    log "  ✗  $target  unreachable"
  fi
done

dns_result=$(dig +short +time=3 +tries=1 cloudflare.com 2>/dev/null | grep -E "^[0-9]" | head -1 || echo "")
if [ -n "$dns_result" ]; then
  printf "  ${GREEN}✓${R}  ${WHITE}%-14s${R}  ${DIM}cloudflare.com → %s${R}\n" "DNS" "$dns_result"
  log "  ✓  DNS  cloudflare.com → $dns_result"
else
  printf "  ${RED}✗${R}  ${WHITE}%-14s${R}  ${RED}resolution failed${R}\n" "DNS"
  log "  ✗  DNS  resolution failed"
fi

# =============================================================================
# GATEWAY HEALTH
# =============================================================================
if [ "$GATEWAY" != "unknown" ]; then
  section "Gateway  ·  $GATEWAY"
  spin_start "Sending 10 pings to $GATEWAY..."
  gw_result=$(ping -c 10 -W 1 "$GATEWAY" 2>/dev/null || echo "")
  gw_loss=$(echo "$gw_result" | grep "packet loss" | awk '{print $7}' || echo "—")
  gw_avg=$(echo "$gw_result" | tail -1 | awk -F'/' '{print $5}' 2>/dev/null || echo "—")
  if [ "$gw_loss" = "0.0%" ]; then
    spin_stop "0% packet loss  ·  ${gw_avg}ms avg"
  else
    spin_stop_warn "${gw_loss} packet loss  ·  ${gw_avg}ms avg"
  fi
  log "  Packet loss: $gw_loss  Avg: ${gw_avg}ms"
fi

# =============================================================================
# HELPERS
# =============================================================================
get_netbios_name() {
  local ip="$1"
  [ -f "$TMP_DIR/netbios.txt" ] && grep "^${ip}|" "$TMP_DIR/netbios.txt" | cut -d'|' -f2 | head -1 || echo ""
}

get_mdns_name() {
  local ip="$1"
  dscacheutil -q host -a ip_address "$ip" 2>/dev/null | awk '/^name:/{print $2}' | sed 's/\.$//' | head -1 || echo ""
}

parse_ports_json() {
  local nmap_out="$1"
  local raw
  raw=$(echo "$nmap_out" | grep "Ports:" | sed 's/.*Ports: //' | tr ',' '\n' | grep '/open/' | \
    sed 's/^ *//' | cut -d'/' -f1 | tr -d ' ' 2>/dev/null || true)
  [ -z "$raw" ] && echo "[]" && return
  echo "$raw" | jq -Rcs '[split("\n")[] | select(length > 0)]' 2>/dev/null || echo "[]"
}

parse_services_json() {
  local nmap_out="$1"
  local pairs
  pairs=$(echo "$nmap_out" | grep "Ports:" | sed 's/.*Ports: //' | tr ',' '\n' | grep '/open/' | \
    sed 's/^ *//' | awk -F'/' '{
      port=$1; svc=$5; ver=$6
      gsub(/^ +| +$/, "", svc); gsub(/^ +| +$/, "", ver)
      if (length(ver) > 0 && ver != " ") svc = svc " " ver
      gsub(/^ +| +$/, "", svc)
      if (length(svc) == 0) svc = "unknown"
      print port "\t" svc
    }' 2>/dev/null || true)
  [ -z "$pairs" ] && echo "{}" && return
  echo "$pairs" | awk -F'\t' 'NF==2{print}' | \
    jq -Rcs '[split("\n")[] | select(length>0) | split("\t") | {(.[0]): (.[1])}] | add // {}' \
    2>/dev/null || echo "{}"
}

validate_json() {
  local val="$1" fallback="$2"
  echo "$val" | jq -e . > /dev/null 2>&1 && echo "$val" || echo "$fallback"
}

# =============================================================================
# NBTSCAN (optional)
# =============================================================================
if [ "$NBTSCAN_AVAIL" = true ]; then
  spin_start "NetBIOS scan..."
  nbtscan -q "$SUBNET" 2>/dev/null | grep -v "^$" | grep -E "^[0-9]" | while IFS= read -r line; do
    nb_ip=$(echo "$line" | awk '{print $1}')
    nb_name=$(echo "$line" | awk '{print $2}')
    echo "$nb_ip|$nb_name"
  done > "$TMP_DIR/netbios.txt" || true
  spin_stop "NetBIOS scan complete"
fi

# =============================================================================
# ARP SCAN
# =============================================================================
section "Discovery  ·  $SUBNET"

spin_start "Running arp-scan on $SUBNET..."
ARP_OUTPUT=$(arp-scan --interface="$IFACE" "$SUBNET" 2>/dev/null | grep -E "^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" || true)
ARP_COUNT=$(echo "$ARP_OUTPUT" | grep -c "." 2>/dev/null || echo 0)
spin_stop "ARP scan complete  ·  $ARP_COUNT devices found"

NEW_DEVICES=()
SEEN_MACS=()
NEWLY_SCANNED_IPS=()

while IFS=$'\t' read -r ip mac vendor; do
  [ -z "$ip" ] && continue
  SEEN_MACS+=("$mac")

  hostname=$(dig +short +time=2 +tries=1 -x "$ip" 2>/dev/null | sed 's/\.$//' || echo "")
  mdns_name=$(get_mdns_name "$ip")
  [ -z "$hostname" ] && hostname="${mdns_name:-unknown}"
  netbios_name=$(get_netbios_name "$ip")

  exists=$(jq --arg mac "$mac" 'any(.[]; .mac == $mac)' "$DB")

  if [ "$exists" = "false" ]; then
    printf "  ${YELLOW}⚠${R}  New device: ${WHITE}%s${R}  ${DIM}%s${R}  — scanning ports...\n" "$ip" "$mac"
    log "  NEW: $ip  $mac  $vendor"
    nmap_out=$(nmap -T4 -sT --open -sV -oG - "$ip" 2>/dev/null || echo "")
    ports_arr=$(validate_json "$(parse_ports_json "$nmap_out")" "[]")
    services_obj=$(validate_json "$(parse_services_json "$nmap_out")" "{}")
    NEWLY_SCANNED_IPS+=("$ip")

    jq --arg ip "$ip" --arg mac "$mac" --arg vendor "$vendor" \
       --arg hostname "$hostname" --arg mdns_name "$mdns_name" \
       --arg netbios_name "$netbios_name" \
       --argjson open_ports "$ports_arr" \
       --argjson services "$services_obj" \
       --arg date "$TIMESTAMP" \
       '. += [{
         "mac": $mac, "ip": $ip, "hostname": $hostname,
         "mdns_name": $mdns_name, "netbios_name": $netbios_name,
         "vendor": $vendor, "open_ports": $open_ports, "services": $services,
         "first_seen": $date, "last_seen": $date,
         "consecutive_up": 1, "status": "up", "notes": ""
       }]' "$DB" > "${DB}.tmp" && mv "${DB}.tmp" "$DB"

    NEW_DEVICES+=("$ip  $mac  $vendor")
  else
    jq --arg mac "$mac" --arg ip "$ip" --arg date "$TIMESTAMP" \
       --arg mdns_name "$mdns_name" --arg netbios_name "$netbios_name" \
       'map(if .mac == $mac then
         .ip = $ip | .last_seen = $date | .status = "up" |
         .consecutive_up = ((.consecutive_up // 0) + 1) |
         (if $mdns_name != "" then .mdns_name = $mdns_name else . end) |
         (if $netbios_name != "" then .netbios_name = $netbios_name else . end)
       else . end)' "$DB" > "${DB}.tmp" && mv "${DB}.tmp" "$DB"
  fi
done <<< "$ARP_OUTPUT"

ALL_MACS=$(jq -r '.[].mac' "$DB")
for mac in $ALL_MACS; do
  seen=false
  for s in "${SEEN_MACS[@]:-}"; do [ "$s" = "$mac" ] && seen=true && break; done
  if [ "$seen" = "false" ]; then
    jq --arg mac "$mac" --arg date "$TIMESTAMP" \
       'map(if .mac == $mac then .status = "down" | .last_seen = $date | .consecutive_up = 0 else . end)' \
       "$DB" > "${DB}.tmp" && mv "${DB}.tmp" "$DB"
  fi
done

# =============================================================================
# NMAP REFRESH — all UP devices in parallel
# =============================================================================
UP_IPS=()
while IFS= read -r ip; do
  already=false
  for scanned in "${NEWLY_SCANNED_IPS[@]:-}"; do [ "$scanned" = "$ip" ] && already=true && break; done
  [ "$already" = false ] && UP_IPS+=("$ip")
done < <(jq -r '.[] | select(.status == "up") | .ip' "$DB")

if [ ${#UP_IPS[@]} -gt 0 ]; then
  NMAP_PIDS=()
  for ip in "${UP_IPS[@]}"; do
    (
      nmap_out=$(nmap -T4 -sT --open -sV -oG - "$ip" 2>/dev/null || echo "")
      ports_arr=$(validate_json "$(parse_ports_json "$nmap_out")" "[]")
      services_obj=$(validate_json "$(parse_services_json "$nmap_out")" "{}")
      printf '%s\n' "$ip" > "$TMP_DIR/${ip}.nmap"
      printf '%s\n' "$ports_arr" >> "$TMP_DIR/${ip}.nmap"
      printf '%s\n' "$services_obj" >> "$TMP_DIR/${ip}.nmap"
    ) &
    NMAP_PIDS+=($!)
  done

  spin_start "Fingerprinting ${#UP_IPS[@]} devices via nmap -sV..."
  for pid in "${NMAP_PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
  spin_stop "Port + service scan complete"

  for nmap_file in "$TMP_DIR"/*.nmap; do
    [ -f "$nmap_file" ] || continue
    ip=$(sed -n '1p' "$nmap_file")
    ports_arr=$(validate_json "$(sed -n '2p' "$nmap_file")" "[]")
    services_obj=$(validate_json "$(sed -n '3p' "$nmap_file")" "{}")
    jq --arg ip "$ip" \
       --argjson open_ports "$ports_arr" \
       --argjson services "$services_obj" \
       'map(if .ip == $ip then .open_ports = $open_ports | .services = $services else . end)' \
       "$DB" > "${DB}.tmp" && mv "${DB}.tmp" "$DB"
  done
fi

# =============================================================================
# DEVICE TABLE
# =============================================================================
section "Devices"

TOTAL=$(jq 'length' "$DB")
UP_COUNT=$(jq '[.[] | select(.status == "up")] | length' "$DB")
DOWN_COUNT=$(jq '[.[] | select(.status == "down")] | length' "$DB")

printf "  ${DIM}  %-18s %-22s %-17s %-4s  %-10s %s${R}\n" \
  "IP" "NAME" "MAC" "    " "LATENCY" "STREAK"
printf "  ${DIM}%s${R}\n" "──────────────────────────────────────────────────────────────────────"
log "  IP                 NAME                   MAC                PING   LATENCY    STREAK"
log "  ─────────────────────────────────────────────────────────────────────────"

jq -c '.[]' "$DB" | while IFS= read -r device; do
  ip=$(echo "$device" | jq -r '.ip')
  mac=$(echo "$device" | jq -r '.mac')
  hostname=$(echo "$device" | jq -r '.hostname')
  mdns_name=$(echo "$device" | jq -r '.mdns_name // ""')
  netbios_name=$(echo "$device" | jq -r '.netbios_name // ""')
  notes=$(echo "$device" | jq -r '.notes')
  consecutive_up=$(echo "$device" | jq -r '.consecutive_up // 0')
  open_ports=$(echo "$device" | jq -r '.open_ports | join(", ")' 2>/dev/null || echo "")

  display="$hostname"
  [ -n "$mdns_name" ] && [ "$mdns_name" != "null" ] && [ "$mdns_name" != "" ] && display="$mdns_name"
  [ -n "$netbios_name" ] && [ "$netbios_name" != "null" ] && [ "$netbios_name" != "" ] && display="$netbios_name"
  [ "$display" = "unknown" ] && [ -n "$notes" ] && [ "$notes" != "null" ] && [ "$notes" != "" ] && display="$notes"
  [ ${#display} -gt 20 ] && display="${display:0:17}..."

  ping_result=$(ping -c 2 -W 1 "$ip" 2>/dev/null | tail -1 || echo "")
  if echo "$ping_result" | grep -q "avg"; then
    latency=$(echo "$ping_result" | awk -F'/' '{print $5 "ms"}')
    status_display="${GREEN}● UP${R}"
    status_plain="UP"
  else
    latency="—"
    status_display="${RED}○ DN${R}"
    status_plain="DN"
  fi

  ports_display=""
  [ -n "$open_ports" ] && ports_display="${DIM}  ${open_ports}${R}"

  printf "  ${DIM}│${R}  %-18s ${BOLD}%-20s${R}  ${DIM}%-17s${R}  %b  %-10s ${DIM}%s${R}%b\n" \
    "$ip" "$display" "$mac" "$status_display" "$latency" "${consecutive_up}x" "$ports_display"
  log "  $(printf '%-18s %-22s %-17s %-6s %-10s %s' "$ip" "$display" "$mac" "$status_plain" "$latency" "${consecutive_up}x")"
done

printf "  ${DIM}%s${R}\n" "──────────────────────────────────────────────────────────────────────"
log "  ─────────────────────────────────────────────────────────────────────────"

# =============================================================================
# SUMMARY
# =============================================================================
printf "\n"
printf "  ${BOLD}%d${R} devices  ${DIM}·${R}  ${GREEN}%d up${R}  ${DIM}·${R}  " "$TOTAL" "$UP_COUNT"
if [ "$DOWN_COUNT" -gt 0 ]; then
  printf "${RED}%d down${R}\n" "$DOWN_COUNT"
else
  printf "${DIM}0 down${R}\n"
fi
log ""
log "  $TOTAL total  ·  $UP_COUNT up  ·  $DOWN_COUNT down"

if [ ${#NEW_DEVICES[@]} -gt 0 ]; then
  printf "\n  ${YELLOW}⚠  New devices this scan:${R}\n"
  log ""
  log "  NEW DEVICES:"
  for d in "${NEW_DEVICES[@]}"; do
    printf "     ${DIM}%s${R}\n" "$d"
    log "     $d"
  done
fi

printf "\n  ${DIM}Report → %s${R}\n\n" "$REPORT"
log ""
log "  Report: $REPORT"
