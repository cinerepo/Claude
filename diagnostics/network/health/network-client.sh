#!/bin/bash

# =============================================================================
# network-client.sh — Cinesys Client-Side Network Diagnostics (macOS)
# No port scanning. No external device probing. Your machine only.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORTS_DIR="$SCRIPT_DIR/reports"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
REPORT="$REPORTS_DIR/report_client_$TIMESTAMP.txt"
TMP_DIR=$(mktemp -d)
SPINNER_PID=""
ISSUES=0
ERRORS=0

cleanup() {
  [ -n "$SPINNER_PID" ] && kill "$SPINNER_PID" 2>/dev/null || true
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$REPORTS_DIR"

for cmd in ping dig traceroute netstat ifconfig; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "  ✗  Missing dependency: $cmd"
    exit 1
  fi
done

NETWORKQUALITY_AVAIL=false
command -v networkquality &>/dev/null && NETWORKQUALITY_AVAIL=true

# =============================================================================
# COLORS
# =============================================================================
R='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[32m'
RED='\033[31m'
YELLOW='\033[33m'
WHITE='\033[97m'
GREY='\033[90m'

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
  [ -n "$SPINNER_PID" ] && kill "$SPINNER_PID" 2>/dev/null || true
  wait "$SPINNER_PID" 2>/dev/null || true
  SPINNER_PID=""
  printf "\r  ${GREEN}✓${R}  %-60s\n" "$1"
}

spin_stop_warn() {
  [ -n "$SPINNER_PID" ] && kill "$SPINNER_PID" 2>/dev/null || true
  wait "$SPINNER_PID" 2>/dev/null || true
  SPINNER_PID=""
  printf "\r  ${YELLOW}⚠${R}  %-60s\n" "$1"
}

section() {
  printf "\n  ${BOLD}${WHITE}%s${R}\n" "$1"
  printf "  ${DIM}%s${R}\n" "──────────────────────────────────────────────────────────"
  log ""; log "$1"; log "──────────────────────────────────────────────────────────"
}

ok()   { printf "  ${GREEN}✓${R}  %s\n" "$1"; log "  ✓  $1"; }
warn() { printf "  ${YELLOW}⚠${R}  %s\n" "$1"; log "  ⚠  $1"; ((ISSUES++)) || true; }
err()  { printf "  ${RED}✗${R}  %s\n" "$1"; log "  ✗  $1"; ((ERRORS++)) || true; }
info() { printf "  ${DIM}·${R}  %s\n" "$1"; log "  ·  $1"; }
log()  { printf '%s\n' "$@" >> "$REPORT"; }

# =============================================================================
# BITBOT
# =============================================================================
bitbot_lines() {
  local eyes="$1" mouth="$2"
  printf "  ${GREY}┌──┬─────┬──┐${R}\n"
  printf "  ${GREY}│  │${R}${BOLD}%-5s${R}${GREY}│  │${R}\n" "$eyes"
  printf "  ${GREY}│  │%-5s│  │${R}\n"  "$mouth"
  printf "  ${GREY}└──┴─────┴──┘${R}\n"
  printf "  ${GREY}    │   │${R}\n"
}

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
IFACE=$(echo "$IFACE_INFO"  | awk '{print $1}')
LOCAL_IP=$(echo "$IFACE_INFO" | awk '{print $2}')
SUBNET=$(echo "$IFACE_INFO"  | awk '{print $3}')
GATEWAY=$(route -n get default 2>/dev/null | awk '/gateway:/{print $2}' | head -1 || echo "unknown")

# =============================================================================
# HEADER
# =============================================================================
HEADER_DATE=$(date +"%Y-%m-%d  %H:%M:%S")

printf "\n"
printf "  ${BOLD}${WHITE}╭──────────────────────────────────────────────────────────╮${R}\n"
printf "  ${BOLD}${WHITE}│${R}  ${BOLD}Cinesys · Client Diagnostics${R}%-30s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}│${R}  ${DIM}%s${R}%-34s${BOLD}${WHITE}│${R}\n" "$HEADER_DATE" ""
printf "  ${BOLD}${WHITE}│${R}  ${DIM}%s  ·  %s  ·  %s${R}%-*s${BOLD}${WHITE}│${R}\n" \
  "$IFACE" "$LOCAL_IP" "$SUBNET" \
  "$((34 - ${#IFACE} - ${#LOCAL_IP} - ${#SUBNET} - 6))" ""
printf "  ${BOLD}${WHITE}│${R}%-60s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}│${R}  ${GREY}┌──┬─────┬──┐${R}%-43s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}│${R}  ${GREY}│  │${R}${BOLD} ◔ ◔ ${R}${GREY}│  │${R}%-43s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}│${R}  ${GREY}│  │  ─  │  │${R}%-43s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}└──┴─────┴──┘${R}%-46s${BOLD}${WHITE}│${R}\n" "" 2>/dev/null || \
printf "  ${BOLD}${WHITE}│${R}  ${GREY}└──┴─────┴──┘${R}%-43s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}│${R}  ${GREY}    │   │${R}%-47s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}│${R}  ${DIM}Running diagnostics...${R}%-36s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}╰──────────────────────────────────────────────────────────╯${R}\n"

log "======================================================"
log " Cinesys Client Diagnostics — $TIMESTAMP"
log "======================================================"
log " Interface : $IFACE    IP : $LOCAL_IP    Subnet : $SUBNET"
log " Gateway   : $GATEWAY"
log "======================================================"

# =============================================================================
# INTERFACE
# =============================================================================
section "Interface  ·  $IFACE"

MAC=$(ifconfig "$IFACE" 2>/dev/null | awk '/ether/{print $2}' | head -1 || echo "unknown")
MTU=$(ifconfig "$IFACE" 2>/dev/null | grep -oE 'mtu [0-9]+' | awk '{print $2}' | head -1 || echo "unknown")
MSS=$(( ${MTU:-0} - 40 ))
MEDIA=$(ifconfig "$IFACE" 2>/dev/null | awk '/media:/{$1=""; print $0}' | sed 's/^ //' | head -1 || echo "")

info "MAC      $MAC"
info "IP       $LOCAL_IP / $SUBNET"
info "MTU      $MTU bytes"
info "MSS      $MSS bytes  (MTU − 40)"
info "Gateway  $GATEWAY"
[ -n "$MEDIA" ] && info "Media    $MEDIA"

# =============================================================================
# INTERFACE STATS
# =============================================================================
section "Interface Stats"

# netstat -i -b columns (macOS): Name Mtu Network Address Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll
STATS_LINE=$(netstat -i -b 2>/dev/null | awk -v iface="$IFACE" '$1 == iface && /Link/' | head -1 || echo "")

if [ -n "$STATS_LINE" ]; then
  IPKTS=$(echo "$STATS_LINE" | awk '{print $5}')
  IERRS=$(echo "$STATS_LINE" | awk '{print $6}')
  OPKTS=$(echo "$STATS_LINE" | awk '{print $8}')
  OERRS=$(echo "$STATS_LINE" | awk '{print $9}')
  COLL=$(echo "$STATS_LINE"  | awk '{print $11}')

  info "RX packets   $IPKTS"
  info "TX packets   $OPKTS"

  [ "${IERRS:-0}" -eq 0 ] 2>/dev/null && ok "RX errors    0" || err "RX errors    $IERRS"
  [ "${OERRS:-0}" -eq 0 ] 2>/dev/null && ok "TX errors    0" || err "TX errors    $OERRS"
  [ "${COLL:-0}"  -eq 0 ] 2>/dev/null && ok "Collisions   0" || warn "Collisions   $COLL"
else
  warn "Could not read interface stats via netstat"
fi

# =============================================================================
# FIREWALL
# =============================================================================
section "Firewall"

FW_BIN="/usr/libexec/ApplicationFirewall/socketfilterfw"
if [ -x "$FW_BIN" ]; then
  FW_STATE=$("$FW_BIN" --getglobalstate 2>/dev/null || echo "")
  if echo "$FW_STATE" | grep -qi "enabled"; then
    ok "Application Firewall   enabled"
  elif echo "$FW_STATE" | grep -qi "disabled"; then
    warn "Application Firewall   disabled"
  else
    info "Application Firewall   $FW_STATE"
  fi

  STEALTH=$("$FW_BIN" --getstealthmode 2>/dev/null || echo "")
  echo "$STEALTH" | grep -qi "enabled" \
    && ok "Stealth mode           enabled" \
    || info "Stealth mode           disabled"

  BLOCK=$("$FW_BIN" --getblockall 2>/dev/null || echo "")
  echo "$BLOCK" | grep -qi "enabled" \
    && info "Block all incoming     enabled" \
    || info "Block all incoming     disabled"
else
  info "socketfilterfw not found — skipping firewall check"
fi

# =============================================================================
# ROUTING
# =============================================================================
section "Routing"

DEFAULT_GW=$(route -n get default 2>/dev/null | awk '/gateway:/{print $2}' | head -1 || echo "unknown")
DEFAULT_IF=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}' | head -1 || echo "unknown")
info "Default gateway    $DEFAULT_GW  via  $DEFAULT_IF"

ROUTE_COUNT=$(netstat -rn 2>/dev/null | grep -cE "^[0-9]" || echo "0")
info "Active routes      $ROUTE_COUNT"

# Any suspicious default routes (more than one default)
MULTI_DEFAULT=$(netstat -rn 2>/dev/null | grep -cE "^default" || echo "0")
if [ "$MULTI_DEFAULT" -gt 1 ]; then
  warn "Multiple default routes detected ($MULTI_DEFAULT)"
else
  ok "Single default route"
fi

# =============================================================================
# INTERNET CONNECTIVITY
# =============================================================================
section "Internet Connectivity"

for target in "1.1.1.1" "8.8.8.8"; do
  ping_out=$(ping -c 5 -W 1 "$target" 2>/dev/null || echo "")
  loss=$(echo "$ping_out" | awk '/packet loss/{print $7}' || echo "100%")
  stats=$(echo "$ping_out" | tail -1)
  avg=$(echo "$stats" | awk -F'/' '{print $5}' 2>/dev/null || echo "")

  if [ -n "$avg" ]; then
    if [ "$loss" = "0.0%" ]; then
      ok "$target   ${avg}ms avg   loss ${loss}"
    else
      warn "$target   ${avg}ms avg   loss ${loss}"
    fi
  else
    err "$target   unreachable"
  fi
done

# =============================================================================
# DNS
# =============================================================================
section "DNS"

LOCAL_DNS=$(scutil --dns 2>/dev/null | awk '/nameserver/{print $3; exit}' || echo "")

for resolver in "1.1.1.1" "8.8.8.8" "$LOCAL_DNS"; do
  [ -z "$resolver" ] && continue
  label="$resolver"
  [[ "$resolver" != "1.1.1.1" && "$resolver" != "8.8.8.8" ]] && label="local  ($resolver)"

  dig_out=$(dig +time=3 +tries=1 @"$resolver" cloudflare.com 2>/dev/null || echo "")
  resolved=$(echo "$dig_out" | awk '/^[^;].*IN.*A/{print $5; exit}' || echo "")
  qtime=$(echo "$dig_out" | awk '/Query time/{print $4 "ms"}' || echo "—")

  if [ -n "$resolved" ]; then
    ok "$label   ${qtime}"
  else
    err "$label   resolution failed"
  fi
done

# =============================================================================
# GATEWAY DEEP PING
# =============================================================================
if [ "$GATEWAY" != "unknown" ]; then
  section "Gateway  ·  $GATEWAY"
  spin_start "Sending 20 pings to $GATEWAY..."
  GW_OUT=$(ping -c 20 -W 1 "$GATEWAY" 2>/dev/null || echo "")

  GW_LOSS=$(echo "$GW_OUT" | awk '/packet loss/{print $7}' || echo "—")
  GW_STATS=$(echo "$GW_OUT" | tail -1)
  GW_MIN=$(echo "$GW_STATS"    | awk -F'/' '{print $4}' 2>/dev/null || echo "—")
  GW_AVG=$(echo "$GW_STATS"    | awk -F'/' '{print $5}' 2>/dev/null || echo "—")
  GW_MAX=$(echo "$GW_STATS"    | awk -F'/' '{print $6}' 2>/dev/null || echo "—")
  GW_JITTER=$(echo "$GW_STATS" | awk -F'/' '{print $7}' | sed 's/[^0-9.]//g' 2>/dev/null || echo "—")

  if [ "$GW_LOSS" = "0.0%" ]; then
    spin_stop "0% loss  ·  ${GW_AVG}ms avg  ·  ${GW_JITTER}ms jitter"
  else
    spin_stop_warn "${GW_LOSS} loss  ·  ${GW_AVG}ms avg"
  fi

  info "Min / Avg / Max   ${GW_MIN} / ${GW_AVG} / ${GW_MAX} ms"
  info "Jitter            ${GW_JITTER}ms  (stddev)"

  if [ "$GW_LOSS" = "0.0%" ]; then
    ok "No packet loss to gateway"
  elif [ "$GW_LOSS" = "100%" ]; then
    err "Gateway unreachable"
  else
    warn "Packet loss to gateway: $GW_LOSS"
  fi
fi

# =============================================================================
# PATH MTU
# =============================================================================
section "Path MTU"

spin_start "Probing path MTU toward 1.1.1.1..."
PMTU_FOUND=0
# Test sizes: payload bytes. ICMP total = payload + 28 (20 IP + 8 ICMP)
for size in 1472 1024 512 256 128; do
  result=$(ping -c 1 -W 2 -s "$size" -D 1.1.1.1 2>/dev/null || echo "")
  if echo "$result" | grep -q "bytes from"; then
    PMTU_FOUND=$((size + 28))
    break
  fi
done

if [ "$PMTU_FOUND" -ge 1500 ]; then
  spin_stop "Path MTU ≥ 1500 bytes  (full Ethernet)"
  ok "Path MTU   ≥ 1500 bytes"
elif [ "$PMTU_FOUND" -gt 0 ]; then
  spin_stop_warn "Path MTU ${PMTU_FOUND} bytes — fragmentation possible"
  warn "Path MTU   ${PMTU_FOUND} bytes  (fragmentation may occur)"
else
  spin_stop_warn "Path MTU probe inconclusive (ICMP DF may be filtered)"
  info "Path MTU   probe inconclusive — ICMP DF-bit filtering suspected"
fi

info "Local MTU  $MTU bytes  ·  MSS  $MSS bytes"

# =============================================================================
# TRACEROUTE
# =============================================================================
section "Traceroute  ·  1.1.1.1  (8 hops max)"

spin_start "Tracing route to 1.1.1.1..."
TRACE=$(traceroute -m 8 -w 2 1.1.1.1 2>/dev/null | tail -n +2 || echo "")
spin_stop "Trace complete"

if [ -n "$TRACE" ]; then
  while IFS= read -r line; do
    info "$line"
  done <<< "$TRACE"
else
  warn "Traceroute returned no output — ICMP may be filtered"
fi

# =============================================================================
# SPEED
# =============================================================================
section "Speed"

if [ "$NETWORKQUALITY_AVAIL" = true ]; then
  spin_start "Running networkquality test (this takes ~10s)..."
  NQ_OUT=$(networkquality -s 2>/dev/null || echo "")
  spin_stop "Speed test complete"
  if [ -n "$NQ_OUT" ]; then
    while IFS= read -r line; do
      [[ "$line" =~ ^== ]] && continue
      [ -z "$line" ] && continue
      info "$line"
    done <<< "$NQ_OUT"
  else
    warn "networkquality returned no output"
  fi
else
  spin_start "Measuring download via curl (10 MB)..."
  DL_BYTES=$(curl -s -w "%{speed_download}" -o /dev/null --max-time 15 \
    "http://speed.cloudflare.com/__down?bytes=10000000" 2>/dev/null || echo "0")
  spin_stop "Download measurement complete"
  DL_MBPS=$(echo "$DL_BYTES" | awk '{printf "%.1f Mbps", $1 * 8 / 1000000}')
  info "Download   $DL_MBPS  (curl estimate — install networkquality for full test)"
fi

# =============================================================================
# SUMMARY + BITBOT FINAL STATE
# =============================================================================
if [ "$ERRORS" -gt 0 ]; then
  EYES=" × × "; MOUTH="  ﹏  "; QUOTE="We've got some problems."; SCOLOR="$RED"
elif [ "$ISSUES" -gt 0 ]; then
  EYES=" ◑ ◑ "; MOUTH="  〜 "; QUOTE="A few things worth watching."; SCOLOR="$YELLOW"
else
  EYES=" ◕ ◕ "; MOUTH="  ⌣  "; QUOTE="All clear. Looking good."; SCOLOR="$GREEN"
fi

printf "\n"
printf "  ${BOLD}${WHITE}╭──────────────────────────────────────────────────────────╮${R}\n"
printf "  ${BOLD}${WHITE}│${R}  ${BOLD}Summary${R}%-51s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}│${R}%-60s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}│${R}  ${GREY}┌──┬─────┬──┐${R}%-43s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}│${R}  ${GREY}│  │${R}${BOLD}%-5s${R}${GREY}│  │${R}%-43s${BOLD}${WHITE}│${R}\n" "$EYES" ""
printf "  ${BOLD}${WHITE}│${R}  ${GREY}│  │%-5s│  │${R}%-43s${BOLD}${WHITE}│${R}\n" "$MOUTH" ""
printf "  ${BOLD}${WHITE}│${R}  ${GREY}└──┴─────┴──┘${R}%-43s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}│${R}  ${GREY}    │   │${R}%-47s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}│${R}  ${DIM}%s${R}%-*s${BOLD}${WHITE}│${R}\n" "$QUOTE" "$((58 - ${#QUOTE}))" ""
printf "  ${BOLD}${WHITE}│${R}%-60s${BOLD}${WHITE}│${R}\n" ""
printf "  ${BOLD}${WHITE}│${R}  %b%d errors  ·  %d warnings${R}%-*s${BOLD}${WHITE}│${R}\n" \
  "${BOLD}${SCOLOR}" "$ERRORS" "$ISSUES" \
  "$((43 - ${#ERRORS} - ${#ISSUES} - 18))" ""
printf "  ${BOLD}${WHITE}╰──────────────────────────────────────────────────────────╯${R}\n"

printf "\n  ${DIM}Report → %s${R}\n\n" "$REPORT"

log ""
log "======================================================"
log " SUMMARY: $ERRORS errors  ·  $ISSUES warnings"
log " Report: $REPORT"
log "======================================================"
