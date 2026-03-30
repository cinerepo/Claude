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
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$REPORTS_DIR"
[ ! -f "$DB" ] && echo "[]" > "$DB"

for cmd in arp-scan nmap jq ping dig; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "[ERROR] Missing: $cmd — brew install $cmd"
    exit 1
  fi
done

NBTSCAN_AVAIL=false
command -v nbtscan &>/dev/null && NBTSCAN_AVAIL=true

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
  echo "[ERROR] No active interface found."
  exit 1
fi
IFACE=$(echo "$IFACE_INFO" | awk '{print $1}')
LOCAL_IP=$(echo "$IFACE_INFO" | awk '{print $2}')
SUBNET=$(echo "$IFACE_INFO" | awk '{print $3}')
GATEWAY=$(route -n get default 2>/dev/null | awk '/gateway:/{print $2}' | head -1 || echo "unknown")

# =============================================================================
# HEADER
# =============================================================================
{
  echo "======================================================"
  echo " Cinesys Network Health Report — $TIMESTAMP"
  echo "======================================================"
  echo " Interface : $IFACE"
  echo " Local IP  : $LOCAL_IP"
  echo " Subnet    : $SUBNET"
  echo " Gateway   : $GATEWAY"
  echo "------------------------------------------------------"
} | tee "$REPORT"

# =============================================================================
# INTERNET + DNS HEALTH
# =============================================================================
echo "" | tee -a "$REPORT"
echo "[*] Internet + DNS health..." | tee -a "$REPORT"

for target in "1.1.1.1" "8.8.8.8"; do
  result=$(ping -c 3 -W 1 "$target" 2>/dev/null | tail -1 || echo "")
  if echo "$result" | grep -q "avg"; then
    latency=$(echo "$result" | awk -F'/' '{print $5 "ms"}')
    printf "    %-14s UP        %s\n" "$target" "$latency" | tee -a "$REPORT"
  else
    printf "    %-14s UNREACHABLE\n" "$target" | tee -a "$REPORT"
  fi
done

dns_result=$(dig +short +time=3 +tries=1 cloudflare.com 2>/dev/null | grep -E "^[0-9]" | head -1 || echo "")
if [ -n "$dns_result" ]; then
  printf "    %-14s RESOLVING  (%s)\n" "DNS" "$dns_result" | tee -a "$REPORT"
else
  printf "    %-14s FAILED\n" "DNS" | tee -a "$REPORT"
fi

# =============================================================================
# GATEWAY HEALTH
# =============================================================================
if [ "$GATEWAY" != "unknown" ]; then
  echo "" | tee -a "$REPORT"
  echo "[*] Gateway health ($GATEWAY — 10 pings)..." | tee -a "$REPORT"
  gw_result=$(ping -c 10 -W 1 "$GATEWAY" 2>/dev/null || echo "")
  gw_loss=$(echo "$gw_result" | grep "packet loss" | awk '{print $7}' || echo "—")
  gw_avg=$(echo "$gw_result" | tail -1 | awk -F'/' '{print $5 "ms"}' 2>/dev/null || echo "—")
  printf "    Packet loss: %-8s  Avg latency: %s\n" "$gw_loss" "$gw_avg" | tee -a "$REPORT"
fi

# =============================================================================
# NBTSCAN — optional, discover NetBIOS names
# =============================================================================
if [ "$NBTSCAN_AVAIL" = true ]; then
  echo "" | tee -a "$REPORT"
  echo "[*] NetBIOS scan..." | tee -a "$REPORT"
  nbtscan -q "$SUBNET" 2>/dev/null | grep -v "^$" | grep -E "^[0-9]" | while IFS= read -r line; do
    nb_ip=$(echo "$line" | awk '{print $1}')
    nb_name=$(echo "$line" | awk '{print $2}')
    echo "$nb_ip|$nb_name"
  done > "$TMP_DIR/netbios.txt" || true
fi

# Helper: look up NetBIOS name for an IP
get_netbios_name() {
  local ip="$1"
  [ -f "$TMP_DIR/netbios.txt" ] && grep "^${ip}|" "$TMP_DIR/netbios.txt" | cut -d'|' -f2 | head -1 || echo ""
}

# Helper: look up mDNS name for an IP via dscacheutil
get_mdns_name() {
  local ip="$1"
  dscacheutil -q host -a ip_address "$ip" 2>/dev/null | awk '/^name:/{print $2}' | sed 's/\.$//' | head -1 || echo ""
}

# Helper: parse nmap grepable output into open_ports JSON array (always returns valid JSON)
parse_ports_json() {
  local nmap_out="$1"
  local raw
  raw=$(echo "$nmap_out" | grep "Ports:" | sed 's/.*Ports: //' | tr ',' '\n' | grep '/open/' | \
    sed 's/^ *//' | cut -d'/' -f1 | tr -d ' ' 2>/dev/null || true)
  [ -z "$raw" ] && echo "[]" && return
  echo "$raw" | jq -Rcs '[split("\n")[] | select(length > 0)]' 2>/dev/null || echo "[]"
}

# Helper: parse nmap grepable output into services JSON object (always returns valid JSON)
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

# Helper: validate JSON, return fallback if invalid
validate_json() {
  local val="$1" fallback="$2"
  echo "$val" | jq -e . > /dev/null 2>&1 && echo "$val" || echo "$fallback"
}

# =============================================================================
# ARP SCAN
# =============================================================================
echo "" | tee -a "$REPORT"
echo "[*] ARP scan on $SUBNET via $IFACE..." | tee -a "$REPORT"
ARP_OUTPUT=$(arp-scan --interface="$IFACE" "$SUBNET" 2>/dev/null | grep -E "^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" || true)

NEW_DEVICES=()
SEEN_MACS=()
NEWLY_SCANNED_IPS=()

while IFS=$'\t' read -r ip mac vendor; do
  [ -z "$ip" ] && continue
  SEEN_MACS+=("$mac")

  # Hostname: try reverse DNS, then mDNS
  hostname=$(dig +short +time=2 +tries=1 -x "$ip" 2>/dev/null | sed 's/\.$//' || echo "")
  mdns_name=$(get_mdns_name "$ip")
  [ -z "$hostname" ] && hostname="${mdns_name:-unknown}"
  netbios_name=$(get_netbios_name "$ip")

  exists=$(jq --arg mac "$mac" 'any(.[]; .mac == $mac)' "$DB")

  if [ "$exists" = "false" ]; then
    echo "[+] NEW device: $ip ($mac) — scanning ports..." | tee -a "$REPORT"
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
         "mac": $mac,
         "ip": $ip,
         "hostname": $hostname,
         "mdns_name": $mdns_name,
         "netbios_name": $netbios_name,
         "vendor": $vendor,
         "open_ports": $open_ports,
         "services": $services,
         "first_seen": $date,
         "last_seen": $date,
         "consecutive_up": 1,
         "status": "up",
         "notes": ""
       }]' "$DB" > "${DB}.tmp" && mv "${DB}.tmp" "$DB"

    NEW_DEVICES+=("$ip ($mac) — $vendor")
  else
    jq --arg mac "$mac" --arg ip "$ip" --arg date "$TIMESTAMP" \
       --arg mdns_name "$mdns_name" --arg netbios_name "$netbios_name" \
       'map(if .mac == $mac then
         .ip = $ip |
         .last_seen = $date |
         .status = "up" |
         .consecutive_up = ((.consecutive_up // 0) + 1) |
         (if $mdns_name != "" then .mdns_name = $mdns_name else . end) |
         (if $netbios_name != "" then .netbios_name = $netbios_name else . end)
       else . end)' \
       "$DB" > "${DB}.tmp" && mv "${DB}.tmp" "$DB"
  fi
done <<< "$ARP_OUTPUT"

# Mark missing devices as down, reset consecutive_up
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
# NMAP REFRESH — all UP devices in parallel (skip newly scanned)
# =============================================================================
echo "" | tee -a "$REPORT"
echo "[*] Refreshing ports + services on all UP devices..." | tee -a "$REPORT"

UP_IPS=()
while IFS= read -r ip; do
  already=false
  for scanned in "${NEWLY_SCANNED_IPS[@]:-}"; do [ "$scanned" = "$ip" ] && already=true && break; done
  [ "$already" = false ] && UP_IPS+=("$ip")
done < <(jq -r '.[] | select(.status == "up") | .ip' "$DB")

for ip in "${UP_IPS[@]:-}"; do
  (
    nmap_out=$(nmap -T4 -sT --open -sV -oG - "$ip" 2>/dev/null || echo "")
    ports_arr=$(validate_json "$(parse_ports_json "$nmap_out")" "[]")
    services_obj=$(validate_json "$(parse_services_json "$nmap_out")" "{}")
    printf '%s\n' "$ip" > "$TMP_DIR/${ip}.nmap"
    printf '%s\n' "$ports_arr" >> "$TMP_DIR/${ip}.nmap"
    printf '%s\n' "$services_obj" >> "$TMP_DIR/${ip}.nmap"
  ) &
done
wait

for nmap_file in "$TMP_DIR"/*.nmap; do
  [ -f "$nmap_file" ] || continue
  ip=$(sed -n '1p' "$nmap_file")
  ports_arr=$(sed -n '2p' "$nmap_file")
  services_obj=$(sed -n '3p' "$nmap_file")
  ports_arr=$(validate_json "${ports_arr}" "[]")
  services_obj=$(validate_json "${services_obj}" "{}")
  jq --arg ip "$ip" \
     --argjson open_ports "$ports_arr" \
     --argjson services "$services_obj" \
     'map(if .ip == $ip then .open_ports = $open_ports | .services = $services else . end)' \
     "$DB" > "${DB}.tmp" && mv "${DB}.tmp" "$DB"
done

# =============================================================================
# PING HEALTH TABLE
# =============================================================================
echo "" | tee -a "$REPORT"
echo "[*] Pinging all known devices..." | tee -a "$REPORT"
echo "" | tee -a "$REPORT"
printf "%-18s %-22s %-17s %-6s %-10s %s\n" "IP" "NAME" "MAC" "PING" "LATENCY" "STREAK" | tee -a "$REPORT"
printf "%-18s %-22s %-17s %-6s %-10s %s\n" "--" "----" "---" "----" "-------" "------" | tee -a "$REPORT"

jq -c '.[]' "$DB" | while IFS= read -r device; do
  ip=$(echo "$device" | jq -r '.ip')
  mac=$(echo "$device" | jq -r '.mac')
  hostname=$(echo "$device" | jq -r '.hostname')
  mdns_name=$(echo "$device" | jq -r '.mdns_name // ""')
  netbios_name=$(echo "$device" | jq -r '.netbios_name // ""')
  notes=$(echo "$device" | jq -r '.notes')
  consecutive_up=$(echo "$device" | jq -r '.consecutive_up // 0')

  # Best available display name
  display="$hostname"
  [ -n "$mdns_name" ] && [ "$mdns_name" != "null" ] && display="$mdns_name"
  [ -n "$netbios_name" ] && [ "$netbios_name" != "null" ] && display="$netbios_name"
  [ "$display" = "unknown" ] && [ -n "$notes" ] && [ "$notes" != "null" ] && display="[$notes]"
  [ ${#display} -gt 22 ] && display="${display:0:19}..."

  ping_result=$(ping -c 2 -W 1 "$ip" 2>/dev/null | tail -1 || echo "")
  if echo "$ping_result" | grep -q "avg"; then
    latency=$(echo "$ping_result" | awk -F'/' '{print $5 "ms"}')
    status="UP"
  else
    latency="—"
    status="DOWN"
  fi

  printf "%-18s %-22s %-17s %-6s %-10s %s\n" "$ip" "$display" "$mac" "$status" "$latency" "${consecutive_up}x" | tee -a "$REPORT"
done

# =============================================================================
# SUMMARY
# =============================================================================
echo "" | tee -a "$REPORT"
echo "------------------------------------------------------" | tee -a "$REPORT"
total=$(jq 'length' "$DB")
up=$(jq '[.[] | select(.status == "up")] | length' "$DB")
down=$(jq '[.[] | select(.status == "down")] | length' "$DB")
echo " Total known devices : $total" | tee -a "$REPORT"
echo " Up                  : $up" | tee -a "$REPORT"
echo " Down / not seen     : $down" | tee -a "$REPORT"

if [ ${#NEW_DEVICES[@]} -gt 0 ]; then
  echo "" | tee -a "$REPORT"
  echo " [!] NEW DEVICES DETECTED:" | tee -a "$REPORT"
  for d in "${NEW_DEVICES[@]}"; do
    echo "     + $d" | tee -a "$REPORT"
  done
fi

echo "------------------------------------------------------" | tee -a "$REPORT"
echo " Report saved to: $REPORT"
echo "======================================================"
