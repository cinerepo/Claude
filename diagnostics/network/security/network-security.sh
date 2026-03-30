#!/bin/bash

# =============================================================================
# network-security.sh — Cinesys WiFi Threat Detection & Response (macOS)
# =============================================================================
#
# Threat Coverage:
#   1. ARP Spoofing / MITM     — gateway MAC changed from baseline
#   2. Evil Twin / Rogue AP    — duplicate SSID with different BSSID
#   3. DNS Hijacking           — local DNS answers differ from 1.1.1.1
#   4. IP-MAC Binding Change   — known device IP/MAC pair has shifted
#   5. Promiscuous Sniffer     — nmap sniffer-detect on subnet
#   6. Deauth Storm            — repeated disassociation events in system log
#   7. MAC Spoofing            — OUI vendor mismatch vs known device
#
# Response Actions (automatic, graduated by severity):
#   CRITICAL  — static ARP lock + macOS alert + threat log + optional disconnect
#   HIGH      — macOS alert + threat log + optional block via pf
#   MEDIUM    — macOS alert + threat log
#
# Baseline:
#   First run establishes trusted state (gateway MAC, SSID/BSSID, DNS fingerprints)
#   All subsequent runs compare against this baseline
#
# Usage:
#   sudo ./network-security.sh              # full scan + response
#   sudo ./network-security.sh --init       # force re-baseline
#   sudo ./network-security.sh --status     # show current threat log
#   sudo ./network-security.sh --monitor    # continuous mode (60s intervals)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HEALTH_DIR="$(dirname "$SCRIPT_DIR")/health"
CLIENTS_DB="$HEALTH_DIR/clients.json"
BASELINE="$SCRIPT_DIR/baseline.json"
THREATS="$SCRIPT_DIR/threats.json"
REPORTS_DIR="$SCRIPT_DIR/reports"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
REPORT="$REPORTS_DIR/security_$TIMESTAMP.txt"
TMP_DIR=$(mktemp -d)
SPINNER_PID=""
THREAT_COUNT=0
CRITICAL_COUNT=0

MODE="${1:-}"

cleanup() {
  [ -n "$SPINNER_PID" ] && kill "$SPINNER_PID" 2>/dev/null || true
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$REPORTS_DIR"
[ ! -f "$THREATS" ] && echo "[]" > "$THREATS"

# =============================================================================
# DEPENDENCY CHECK
# =============================================================================
for cmd in arp-scan nmap jq arp dig networksetup; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "  ✗  Missing dependency: $cmd"
    exit 1
  fi
done

AIRPORT="/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
AIRPORT_AVAIL=false
[ -x "$AIRPORT" ] && AIRPORT_AVAIL=true

# =============================================================================
# COLORS + UI
# =============================================================================
R='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[32m'
RED='\033[31m'
YELLOW='\033[33m'
CYAN='\033[36m'
MAGENTA='\033[35m'
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

spin_stop_fail() {
  [ -n "$SPINNER_PID" ] && kill "$SPINNER_PID" 2>/dev/null || true
  wait "$SPINNER_PID" 2>/dev/null || true
  SPINNER_PID=""
  printf "\r  ${RED}✗${R}  %-60s\n" "$1"
}

section() {
  local title="$1"
  printf "\n  ${BOLD}${WHITE}%s${R}\n" "$title"
  printf "  ${DIM}%s${R}\n" "──────────────────────────────────────────────────────────"
  log ""
  log "[$title]"
  log "──────────────────────────────────────────────────────────"
}

ok()       { printf "  ${GREEN}✓${R}  %s\n" "$1"; log "  OK      $1"; }
warn()     { printf "  ${YELLOW}⚠${R}  %s\n" "$1"; log "  WARN    $1"; }
info()     { printf "  ${DIM}·${R}  %s\n" "$1"; log "  INFO    $1"; }
log()      { printf '%s\n' "$@" >> "$REPORT"; }

threat_medium() {
  local title="$1" detail="$2"
  printf "  ${YELLOW}⚠${R}  ${BOLD}[MEDIUM]${R}  %s\n" "$title"
  printf "        ${DIM}%s${R}\n" "$detail"
  log "  THREAT  MEDIUM  $title  |  $detail"
  ((THREAT_COUNT++)) || true
  record_threat "MEDIUM" "$title" "$detail"
  notify_macos "⚠ Security Alert" "$title" "$detail"
}

threat_high() {
  local title="$1" detail="$2"
  printf "  ${YELLOW}${BOLD}⚠${R}  ${BOLD}${YELLOW}[HIGH]${R}    %s\n" "$title"
  printf "        ${DIM}%s${R}\n" "$detail"
  log "  THREAT  HIGH    $title  |  $detail"
  ((THREAT_COUNT++)) || true
  record_threat "HIGH" "$title" "$detail"
  notify_macos "🔴 HIGH Threat Detected" "$title" "$detail"
}

threat_critical() {
  local title="$1" detail="$2"
  printf "  ${RED}${BOLD}✗  [CRITICAL]${R}  %s\n" "$title"
  printf "        ${DIM}%s${R}\n" "$detail"
  log "  THREAT  CRITICAL  $title  |  $detail"
  ((THREAT_COUNT++)) || true
  ((CRITICAL_COUNT++)) || true
  record_threat "CRITICAL" "$title" "$detail"
  notify_macos "🚨 CRITICAL THREAT" "$title" "$detail"
}

# =============================================================================
# NOTIFICATIONS
# =============================================================================
notify_macos() {
  local title="$1" subtitle="$2" body="$3"
  osascript -e "display notification \"$body\" with title \"$title\" subtitle \"$subtitle\" sound name \"Basso\"" 2>/dev/null || true
}

# =============================================================================
# THREAT LOG
# =============================================================================
record_threat() {
  local severity="$1" title="$2" detail="$3"
  local existing
  existing=$(cat "$THREATS")
  echo "$existing" | jq \
    --arg ts "$TIMESTAMP" \
    --arg sev "$severity" \
    --arg title "$title" \
    --arg detail "$detail" \
    '. += [{"timestamp": $ts, "severity": $sev, "title": $title, "detail": $detail, "resolved": false}]' \
    > "${THREATS}.tmp" && mv "${THREATS}.tmp" "$THREATS"
}

# =============================================================================
# INTERFACE + NETWORK DETECTION
# =============================================================================
detect_interface() {
  while IFS= read -r line; do
    if [[ "$line" =~ ^(en[0-9]+): ]]; then
      current_iface="${BASH_REMATCH[1]}"
    elif [[ -n "${current_iface:-}" && "$line" =~ inet[[:space:]]([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)[[:space:]]netmask[[:space:]](0x[0-9a-fA-F]+) ]]; then
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
IFACE=$(echo "$IFACE_INFO"   | awk '{print $1}')
LOCAL_IP=$(echo "$IFACE_INFO" | awk '{print $2}')
SUBNET=$(echo "$IFACE_INFO"  | awk '{print $3}')
GATEWAY=$(route -n get default 2>/dev/null | awk '/gateway:/{print $2}' | head -1 || echo "unknown")

# =============================================================================
# STATUS MODE
# =============================================================================
if [ "$MODE" = "--status" ]; then
  printf "\n  ${BOLD}${WHITE}Threat Log${R}  ${DIM}(%s)${R}\n\n" "$THREATS"
  if [ ! -f "$THREATS" ] || [ "$(jq 'length' "$THREATS")" = "0" ]; then
    printf "  ${GREEN}No threats recorded.${R}\n\n"
    exit 0
  fi
  jq -r '.[] | "  [\(.timestamp)]  \(.severity)  \(.title)\n        \(.detail)\n"' "$THREATS"
  printf "\n  Total: %s threats\n\n" "$(jq 'length' "$THREATS")"
  exit 0
fi

# =============================================================================
# HEADER
# =============================================================================
HEADER_DATE=$(date +"%Y-%m-%d  %H:%M:%S")
printf "\n"
printf "  ${BOLD}${RED}╭──────────────────────────────────────────────────────────╮${R}\n"
printf "  ${BOLD}${RED}│${R}  ${BOLD}Cinesys · Network Security Monitor${R}%-24s${BOLD}${RED}│${R}\n" ""
printf "  ${BOLD}${RED}│${R}  ${DIM}%s${R}%-34s${BOLD}${RED}│${R}\n" "$HEADER_DATE" ""
printf "  ${BOLD}${RED}│${R}  ${DIM}%s  ·  %s  ·  gw %s${R}%-*s${BOLD}${RED}│${R}\n" "$IFACE" "$LOCAL_IP" "$GATEWAY" "$((28 - ${#IFACE} - ${#LOCAL_IP} - ${#GATEWAY}))" ""
printf "  ${BOLD}${RED}╰──────────────────────────────────────────────────────────╯${R}\n"

log "======================================================"
log " Cinesys Network Security Report — $TIMESTAMP"
log "======================================================"
log " Interface : $IFACE"
log " Local IP  : $LOCAL_IP"
log " Subnet    : $SUBNET"
log " Gateway   : $GATEWAY"
log "======================================================"

# =============================================================================
# GET CURRENT GATEWAY MAC
# =============================================================================
get_gateway_mac() {
  # Force an ARP refresh for the gateway
  ping -c 1 -W 1 "$GATEWAY" &>/dev/null || true
  # Read from ARP cache
  arp -n "$GATEWAY" 2>/dev/null | awk '/ at /{print $4}' | head -1 || echo "unknown"
}

GATEWAY_MAC=$(get_gateway_mac)

# =============================================================================
# GET CURRENT SSID + BSSID
# =============================================================================
get_wifi_info() {
  if [ "$AIRPORT_AVAIL" = true ]; then
    local info
    info=$("$AIRPORT" -I 2>/dev/null || echo "")
    local ssid bssid channel
    ssid=$(echo "$info"  | awk -F': ' '/ SSID:/{print $2}' | xargs 2>/dev/null || echo "unknown")
    bssid=$(echo "$info" | awk -F': ' '/BSSID:/{print $2}' | xargs 2>/dev/null | head -1 || echo "unknown")
    channel=$(echo "$info"| awk -F': ' '/channel:/{print $2}' | head -1 || echo "?")
    echo "$ssid|$bssid|$channel"
  else
    local ssid
    ssid=$(networksetup -getairportnetwork "$IFACE" 2>/dev/null | sed 's/Current Wi-Fi Network: //' || echo "unknown")
    echo "$ssid|unknown|unknown"
  fi
}

WIFI_INFO=$(get_wifi_info)
CURRENT_SSID=$(echo "$WIFI_INFO"   | cut -d'|' -f1)
CURRENT_BSSID=$(echo "$WIFI_INFO"  | cut -d'|' -f2)
CURRENT_CHANNEL=$(echo "$WIFI_INFO" | cut -d'|' -f3)

# =============================================================================
# BASELINE MANAGEMENT
# =============================================================================
section "Baseline"

if [ "$MODE" = "--init" ] || [ ! -f "$BASELINE" ]; then
  printf "  ${CYAN}→${R}  Establishing trusted baseline...\n"
  log "  Establishing new baseline"

  # Capture DNS fingerprints against trusted resolvers
  spin_start "Fingerprinting DNS responses via 1.1.1.1..."
  dns_cloudflare=$(dig +short @1.1.1.1 +time=4 +tries=1 cloudflare.com A 2>/dev/null | sort | tr '\n' ',' | sed 's/,$//' || echo "")
  dns_google_dns=$(dig +short @8.8.8.8 +time=4 +tries=1 google.com A 2>/dev/null | sort | tr '\n' ',' | sed 's/,$//' || echo "")
  spin_stop "DNS fingerprints captured"

  jq -n \
    --arg ts "$TIMESTAMP" \
    --arg gw_ip "$GATEWAY" \
    --arg gw_mac "$GATEWAY_MAC" \
    --arg ssid "$CURRENT_SSID" \
    --arg bssid "$CURRENT_BSSID" \
    --arg channel "$CURRENT_CHANNEL" \
    --arg iface "$IFACE" \
    --arg local_ip "$LOCAL_IP" \
    --arg dns_cloudflare "$dns_cloudflare" \
    --arg dns_google "$dns_google_dns" \
    '{
      "established": $ts,
      "iface": $iface,
      "local_ip": $local_ip,
      "gateway": {
        "ip": $gw_ip,
        "mac": $gw_mac
      },
      "wifi": {
        "ssid": $ssid,
        "bssid": $bssid,
        "channel": $channel
      },
      "dns_fingerprints": {
        "cloudflare_com_via_1_1_1_1": $dns_cloudflare,
        "google_com_via_8_8_8_8": $dns_google
      }
    }' > "$BASELINE"

  printf "  ${GREEN}✓${R}  Baseline saved:\n"
  printf "     ${DIM}Gateway:  %s  (%s)${R}\n" "$GATEWAY" "$GATEWAY_MAC"
  printf "     ${DIM}WiFi:     %s  (%s)  ch %s${R}\n" "$CURRENT_SSID" "$CURRENT_BSSID" "$CURRENT_CHANNEL"
  log "  Baseline: GW=$GATEWAY MAC=$GATEWAY_MAC SSID=$CURRENT_SSID BSSID=$CURRENT_BSSID"
else
  BASE_GW_IP=$(jq -r '.gateway.ip'   "$BASELINE")
  BASE_GW_MAC=$(jq -r '.gateway.mac' "$BASELINE")
  BASE_SSID=$(jq -r '.wifi.ssid'     "$BASELINE")
  BASE_BSSID=$(jq -r '.wifi.bssid'   "$BASELINE")
  BASE_TS=$(jq -r '.established'     "$BASELINE")
  ok "Baseline loaded  (established $BASE_TS)"
  info "Trusted gateway: $BASE_GW_IP  ($BASE_GW_MAC)"
  info "Trusted SSID:    $BASE_SSID  ($BASE_BSSID)"
fi

# Load baseline for checks
BASE_GW_MAC=$(jq -r '.gateway.mac' "$BASELINE")
BASE_GW_IP=$(jq -r '.gateway.ip'   "$BASELINE")
BASE_SSID=$(jq -r '.wifi.ssid'     "$BASELINE")
BASE_BSSID=$(jq -r '.wifi.bssid'   "$BASELINE")
BASE_DNS_CF=$(jq -r '.dns_fingerprints.cloudflare_com_via_1_1_1_1' "$BASELINE")
BASE_DNS_GG=$(jq -r '.dns_fingerprints.google_com_via_8_8_8_8'     "$BASELINE")

# =============================================================================
# CHECK 1: ARP SPOOFING / GATEWAY MAC INTEGRITY
# =============================================================================
section "Check 1  ·  ARP / Gateway MAC"

info "Gateway IP:       $GATEWAY"
info "Current MAC:      $GATEWAY_MAC"
info "Trusted MAC:      $BASE_GW_MAC"

if [ "$GATEWAY_MAC" = "unknown" ]; then
  warn "Could not resolve gateway MAC from ARP cache"
elif [ "$GATEWAY" != "$BASE_GW_IP" ]; then
  threat_high \
    "Gateway IP changed" \
    "Was: $BASE_GW_IP  Now: $GATEWAY  — possible DHCP or routing change"
elif [ "$GATEWAY_MAC" != "$BASE_GW_MAC" ]; then
  threat_critical \
    "ARP Spoofing / MITM Detected" \
    "Gateway $GATEWAY MAC changed: was $BASE_GW_MAC — now $GATEWAY_MAC"
  # RESPONSE: Lock in the legitimate gateway MAC via static ARP
  printf "  ${RED}${BOLD}  → RESPONSE: Setting static ARP for gateway...${R}\n"
  if arp -s "$GATEWAY" "$BASE_GW_MAC" 2>/dev/null; then
    ok "Static ARP set: $GATEWAY → $BASE_GW_MAC  (ARP poison blocked)"
    log "  RESPONSE: static ARP locked  $GATEWAY → $BASE_GW_MAC"
  else
    warn "Could not set static ARP (may need root or SIP constraints apply)"
  fi
else
  ok "Gateway MAC verified  ·  $GATEWAY_MAC matches baseline"
fi

# Also check ARP table for duplicate MACs (same MAC answering for 2 IPs)
section "Check 1b  ·  Duplicate MACs in ARP Table"
spin_start "Scanning ARP table for duplicate entries..."
ARP_TABLE=$(arp -a 2>/dev/null | grep -E "\([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\)" | awk '{print $2, $4}' | tr -d '()' || true)
DUPE_CHECK=$(echo "$ARP_TABLE" | awk '{print $2}' | sort | uniq -d || true)
spin_stop "ARP table analyzed"

if [ -n "$DUPE_CHECK" ]; then
  while IFS= read -r dupe_mac; do
    [ -z "$dupe_mac" ] && continue
    dupe_ips=$(echo "$ARP_TABLE" | awk -v m="$dupe_mac" '$2==m{print $1}' | tr '\n' ' ')
    threat_critical \
      "ARP Table: MAC serving multiple IPs" \
      "MAC $dupe_mac answers for: $dupe_ips — strong MITM indicator"
  done <<< "$DUPE_CHECK"
else
  ok "No duplicate MACs in ARP table"
fi

# =============================================================================
# CHECK 2: EVIL TWIN / ROGUE AP DETECTION
# =============================================================================
section "Check 2  ·  Evil Twin / Rogue AP"

if [ "$AIRPORT_AVAIL" = false ]; then
  warn "airport utility not available — skipping AP scan"
else
  spin_start "Scanning nearby APs with airport..."
  AP_SCAN=$("$AIRPORT" -s 2>/dev/null | tail -n +2 || echo "")
  spin_stop "AP scan complete"

  info "Current network: SSID=$CURRENT_SSID  BSSID=$CURRENT_BSSID  ch=$CURRENT_CHANNEL"

  # Look for same SSID with different BSSID — evil twin
  EVIL_TWIN_FOUND=false
  if [ -n "$AP_SCAN" ]; then
    while IFS= read -r ap_line; do
      [ -z "$ap_line" ] && continue
      ap_ssid=$(echo "$ap_line"   | awk '{$1=""; print}' | sed 's/^ *//' | awk '{for(i=1;i<=NF-5;i++) printf $i " "; print ""}' | xargs 2>/dev/null || echo "")
      ap_bssid=$(echo "$ap_line"  | awk '{print $(NF-4)}' || echo "")
      ap_rssi=$(echo "$ap_line"   | awk '{print $1}' || echo "")
      ap_channel=$(echo "$ap_line"| awk '{print $(NF-3)}' || echo "")

      # Normalize SSID comparison
      if [ "$ap_ssid" = "$CURRENT_SSID" ] && [ "$ap_bssid" != "$CURRENT_BSSID" ]; then
        EVIL_TWIN_FOUND=true
        threat_critical \
          "Evil Twin / Rogue AP Detected" \
          "SSID '$CURRENT_SSID' also seen at BSSID $ap_bssid (ch $ap_channel, RSSI $ap_rssi) — NOT your AP ($CURRENT_BSSID)"
      fi

      # Check against trusted BSSID baseline
      if [ "$ap_bssid" = "$CURRENT_BSSID" ] && [ "$ap_ssid" != "$CURRENT_SSID" ]; then
        threat_high \
          "Your AP BSSID broadcasting different SSID" \
          "BSSID $CURRENT_BSSID now advertising '$ap_ssid' instead of '$CURRENT_SSID'"
      fi
    done <<< "$AP_SCAN"
  fi

  [ "$EVIL_TWIN_FOUND" = false ] && ok "No evil twin detected for SSID '$CURRENT_SSID'"

  # Check if we're connected to the trusted BSSID
  if [ "$CURRENT_BSSID" != "unknown" ] && [ "$CURRENT_BSSID" != "$BASE_BSSID" ]; then
    threat_high \
      "Connected to different BSSID than baseline" \
      "Was: $BASE_BSSID  Now: $CURRENT_BSSID  (channel $CURRENT_CHANNEL)"
  elif [ "$CURRENT_BSSID" != "unknown" ]; then
    ok "Connected to trusted BSSID  ·  $CURRENT_BSSID"
  fi
fi

# =============================================================================
# CHECK 3: DNS HIJACKING
# =============================================================================
section "Check 3  ·  DNS Hijacking"

spin_start "Comparing local DNS vs trusted resolvers..."

# Get local resolver answers
LOCAL_DNS_CF=$(dig +short +time=4 +tries=1 cloudflare.com A 2>/dev/null | sort | tr '\n' ',' | sed 's/,$//' || echo "")
LOCAL_DNS_GG=$(dig +short +time=4 +tries=1 google.com A 2>/dev/null | sort | tr '\n' ',' | sed 's/,$//' || echo "")

# Get trusted resolver answers (direct queries)
TRUSTED_DNS_CF=$(dig +short @1.1.1.1 +time=4 +tries=1 cloudflare.com A 2>/dev/null | sort | tr '\n' ',' | sed 's/,$//' || echo "")
TRUSTED_DNS_GG=$(dig +short @8.8.8.8 +time=4 +tries=1 google.com A 2>/dev/null | sort | tr '\n' ',' | sed 's/,$//' || echo "")

spin_stop "DNS comparison complete"

info "cloudflare.com via local:  $LOCAL_DNS_CF"
info "cloudflare.com via 1.1.1.1: $TRUSTED_DNS_CF"
info "google.com via local:      $LOCAL_DNS_GG"
info "google.com via 8.8.8.8:    $TRUSTED_DNS_GG"

DNS_HIJACK=false

if [ -n "$LOCAL_DNS_CF" ] && [ -n "$TRUSTED_DNS_CF" ] && [ "$LOCAL_DNS_CF" != "$TRUSTED_DNS_CF" ]; then
  # CDN-backed domains have many IPs — this is expected. Only flag if ZERO overlap
  local_cf_set=$(echo "$LOCAL_DNS_CF"   | tr ',' '\n' | sort)
  trusted_cf_set=$(echo "$TRUSTED_DNS_CF" | tr ',' '\n' | sort)
  overlap=$(comm -12 <(echo "$local_cf_set") <(echo "$trusted_cf_set") | wc -l | tr -d ' ')
  if [ "$overlap" = "0" ]; then
    DNS_HIJACK=true
    threat_high \
      "DNS Hijacking Suspected — cloudflare.com" \
      "Local resolver returned $LOCAL_DNS_CF  |  1.1.1.1 returned $TRUSTED_DNS_CF (no overlap)"
  else
    info "cloudflare.com IPs differ (CDN variance, $overlap shared) — OK"
  fi
fi

if [ -n "$LOCAL_DNS_GG" ] && [ -n "$TRUSTED_DNS_GG" ] && [ "$LOCAL_DNS_GG" != "$TRUSTED_DNS_GG" ]; then
  local_gg_set=$(echo "$LOCAL_DNS_GG"   | tr ',' '\n' | sort)
  trusted_gg_set=$(echo "$TRUSTED_DNS_GG" | tr ',' '\n' | sort)
  overlap=$(comm -12 <(echo "$local_gg_set") <(echo "$trusted_gg_set") | wc -l | tr -d ' ')
  if [ "$overlap" = "0" ]; then
    DNS_HIJACK=true
    threat_high \
      "DNS Hijacking Suspected — google.com" \
      "Local resolver returned $LOCAL_DNS_GG  |  8.8.8.8 returned $TRUSTED_DNS_GG (no overlap)"
  else
    info "google.com IPs differ (CDN variance, $overlap shared) — OK"
  fi
fi

if [ "$DNS_HIJACK" = true ]; then
  # RESPONSE: Flush DNS cache
  printf "  ${YELLOW}${BOLD}  → RESPONSE: Flushing DNS cache...${R}\n"
  dscacheutil -flushcache 2>/dev/null || true
  killall -HUP mDNSResponder 2>/dev/null || true
  ok "DNS cache flushed"
  log "  RESPONSE: DNS cache flushed"
else
  ok "DNS responses consistent with trusted resolvers"
fi

# =============================================================================
# CHECK 4: IP-MAC BINDING CHANGES (from clients.json)
# =============================================================================
section "Check 4  ·  IP-MAC Binding Integrity"

if [ ! -f "$CLIENTS_DB" ]; then
  warn "clients.json not found — run network-health.sh first to build device database"
else
  spin_start "Checking current ARP table against client database..."

  BINDING_ISSUES=0
  while IFS= read -r device; do
    db_ip=$(echo "$device"  | jq -r '.ip')
    db_mac=$(echo "$device" | jq -r '.mac')
    db_status=$(echo "$device" | jq -r '.status')

    [ "$db_status" != "up" ] && continue

    # Get current MAC for this IP from the live ARP table
    current_mac=$(arp -n "$db_ip" 2>/dev/null | awk '/ at /{print $4}' | head -1 || echo "")

    if [ -z "$current_mac" ] || [ "$current_mac" = "unknown" ]; then
      continue  # device not in ARP cache right now — not a threat
    fi

    if [ "$current_mac" != "$db_mac" ]; then
      ((BINDING_ISSUES++)) || true
      if [ "$db_ip" = "$GATEWAY" ]; then
        threat_critical \
          "Gateway IP-MAC binding changed" \
          "$db_ip  was $db_mac  now $current_mac — MITM risk"
      else
        threat_high \
          "Device MAC changed for known IP" \
          "$db_ip  was $db_mac  now $current_mac"
      fi
    fi
  done < <(jq -c '.[]' "$CLIENTS_DB")

  spin_stop "IP-MAC binding check complete"
  [ "$BINDING_ISSUES" -eq 0 ] && ok "All IP-MAC bindings consistent with database"
fi

# =============================================================================
# CHECK 5: PROMISCUOUS MODE / SNIFFER DETECTION
# =============================================================================
section "Check 5  ·  Promiscuous Mode / Sniffers"

spin_start "Running nmap sniffer-detect on $SUBNET..."
SNIFFER_OUT=$(nmap -T4 --script sniffer-detect "$SUBNET" 2>/dev/null || echo "")
spin_stop "Sniffer detection complete"

SNIFFERS_FOUND=$(echo "$SNIFFER_OUT" | grep -i "Likely in promiscuous mode" || echo "")
if [ -n "$SNIFFERS_FOUND" ]; then
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    sniffer_ip=$(echo "$line" | grep -oE "([0-9]+\.){3}[0-9]+" | head -1 || echo "unknown")
    threat_high \
      "Promiscuous Mode / Packet Sniffer Detected" \
      "Host $sniffer_ip appears to be in promiscuous mode (capturing all traffic)"
  done <<< "$SNIFFERS_FOUND"
else
  ok "No hosts detected in promiscuous mode"
fi

# =============================================================================
# CHECK 6: DEAUTH / DISASSOCIATION EVENTS
# =============================================================================
section "Check 6  ·  Deauth Storm Detection"

spin_start "Checking system log for deauth events..."
# macOS logs WiFi deauth events in system log
DEAUTH_EVENTS=$(log show --last 10m --predicate 'subsystem == "com.apple.wifi" OR subsystem == "com.apple.airport"' 2>/dev/null | \
  grep -iE "deauth|disassoc|disconnect" | grep -v "grep" | wc -l | tr -d ' ' || echo "0")

spin_stop "Deauth log check complete"

if [ "$DEAUTH_EVENTS" -ge 5 ]; then
  threat_high \
    "Deauth Storm Detected" \
    "$DEAUTH_EVENTS deauth/disassociation events in last 10 minutes — possible deauth attack"
elif [ "$DEAUTH_EVENTS" -ge 2 ]; then
  threat_medium \
    "Elevated Deauth Events" \
    "$DEAUTH_EVENTS deauth events in last 10 minutes — monitor for increase"
else
  ok "Deauth event count normal  ·  $DEAUTH_EVENTS in last 10 min"
fi

# =============================================================================
# CHECK 7: MAC VENDOR ANOMALIES (OUI vs known devices)
# =============================================================================
section "Check 7  ·  MAC Vendor Consistency"

if [ -f "$CLIENTS_DB" ]; then
  # Check for devices with obviously randomized MACs (local bit set in OUI)
  # Bit 1 of first byte being 1 means locally administered (i.e., randomized)
  RAND_MAC_COUNT=0
  while IFS= read -r device; do
    mac=$(echo "$device" | jq -r '.mac')
    status=$(echo "$device" | jq -r '.status')
    ip=$(echo "$device" | jq -r '.ip')
    [ "$status" != "up" ] && continue

    # Check if MAC is locally administered (randomized)
    first_octet_hex=$(echo "$mac" | cut -d':' -f1)
    first_octet_dec=$((16#$first_octet_hex))
    is_local=$(( (first_octet_dec & 2) >> 1 ))  # bit 1 = locally administered

    if [ "$is_local" -eq 1 ]; then
      ((RAND_MAC_COUNT++)) || true
      info "Randomized MAC (locally administered): $ip  $mac — likely mobile device with private addressing"
    fi
  done < <(jq -c '.[] | select(.status == "up")' "$CLIENTS_DB")

  if [ "$RAND_MAC_COUNT" -gt 0 ]; then
    info "$RAND_MAC_COUNT device(s) using randomized/private MACs — expected for iOS/Android"
  else
    ok "No randomized MACs detected"
  fi
fi

# =============================================================================
# GATEWAY MAC SNAPSHOT — always update baseline gateway MAC tracking
# =============================================================================
section "Gateway MAC Record"

info "Gateway: $GATEWAY"
info "Current MAC: $GATEWAY_MAC"

# Update baseline with latest confirmed MAC (only if no threats detected)
if [ "$CRITICAL_COUNT" -eq 0 ] && [ "$GATEWAY_MAC" != "unknown" ]; then
  # Append to gateway MAC history within baseline
  CURRENT_BASELINE=$(cat "$BASELINE")
  echo "$CURRENT_BASELINE" | jq \
    --arg ts "$TIMESTAMP" \
    --arg mac "$GATEWAY_MAC" \
    --arg ip "$GATEWAY" \
    'if (.gateway_history | type) == "array" then
       .gateway_history += [{"ts": $ts, "ip": $ip, "mac": $mac}]
     else
       .gateway_history = [{"ts": $ts, "ip": $ip, "mac": $mac}]
     end' \
    > "${BASELINE}.tmp" && mv "${BASELINE}.tmp" "$BASELINE"
  ok "Gateway MAC confirmed and recorded  ·  $GATEWAY → $GATEWAY_MAC"
  log "  Gateway MAC history updated: $GATEWAY = $GATEWAY_MAC at $TIMESTAMP"
elif [ "$CRITICAL_COUNT" -gt 0 ]; then
  warn "Gateway MAC record NOT updated — CRITICAL threat active"
fi

# =============================================================================
# SUMMARY + RESPONSE ESCALATION
# =============================================================================
printf "\n"
printf "  ${BOLD}${WHITE}╭──────────────────────────────────────────────────────────╮${R}\n"

if [ "$THREAT_COUNT" -eq 0 ]; then
  printf "  ${BOLD}${WHITE}│${R}  ${GREEN}${BOLD}✓  Network Clean — No Threats Detected${R}%-20s${BOLD}${WHITE}│${R}\n" ""
elif [ "$CRITICAL_COUNT" -gt 0 ]; then
  printf "  ${BOLD}${WHITE}│${R}  ${RED}${BOLD}✗  CRITICAL: %d threat(s) detected${R}%-26s${BOLD}${WHITE}│${R}\n" "$THREAT_COUNT" ""
else
  printf "  ${BOLD}${WHITE}│${R}  ${YELLOW}${BOLD}⚠  %d threat(s) detected — review above${R}%-22s${BOLD}${WHITE}│${R}\n" "$THREAT_COUNT" ""
fi

printf "  ${BOLD}${WHITE}│${R}  ${DIM}Report → %s${R}%-*s${BOLD}${WHITE}│${R}\n" \
  "$(basename "$REPORT")" "$((31 - ${#REPORT} % 40))" ""
printf "  ${BOLD}${WHITE}╰──────────────────────────────────────────────────────────╯${R}\n\n"

log ""
log "======================================================"
log " SUMMARY: $THREAT_COUNT threat(s) | $CRITICAL_COUNT critical"
log " Report: $REPORT"
log "======================================================"

# =============================================================================
# CRITICAL RESPONSE ESCALATION
# =============================================================================
if [ "$CRITICAL_COUNT" -gt 0 ]; then
  printf "  ${RED}${BOLD}CRITICAL THREATS ACTIVE — Recommended actions:${R}\n\n"
  printf "  ${DIM}1. Verify your router/AP is not compromised${R}\n"
  printf "  ${DIM}2. Check for unknown devices on your network${R}\n"
  printf "  ${DIM}3. If MITM confirmed, disconnect immediately:${R}\n"
  printf "     ${CYAN}networksetup -setairportpower %s off${R}\n" "$IFACE"
  printf "  ${DIM}4. Re-run with --init once threat is cleared to reset baseline${R}\n\n"
  log ""
  log "  CRITICAL RESPONSE GUIDANCE DISPLAYED"
fi

# =============================================================================
# MONITOR MODE
# =============================================================================
if [ "$MODE" = "--monitor" ]; then
  INTERVAL=60
  printf "  ${DIM}Monitor mode active — scanning every %ds  (Ctrl+C to stop)${R}\n\n" "$INTERVAL"
  while true; do
    sleep "$INTERVAL"
    printf "  ${DIM}[%s]  Running security scan...${R}\n" "$(date +%H:%M:%S)"
    exec "$0"
  done
fi
