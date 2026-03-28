#!/bin/bash

# =============================================================================
# network-health.sh — Cinesys Network Health Agent (macOS)
# Scans the local network, maintains a client database, and reports health.
# Usage: ./network-health.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="$SCRIPT_DIR/clients.json"
REPORTS_DIR="$SCRIPT_DIR/reports"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
REPORT="$REPORTS_DIR/report_$TIMESTAMP.txt"

mkdir -p "$REPORTS_DIR"

# Init DB if missing
[ ! -f "$DB" ] && echo "[]" > "$DB"

# Check dependencies
for cmd in arp-scan nmap jq ping; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "[ERROR] Missing dependency: $cmd — install with: brew install $cmd"
    exit 1
  fi
done

# =============================================================================
# INTERFACE + SUBNET DETECTION
# Finds the first active non-loopback en* interface with an inet address
# =============================================================================
detect_interface() {
  local current_iface=""
  while IFS= read -r line; do
    if [[ "$line" =~ ^(en[0-9]+): ]]; then
      current_iface="${BASH_REMATCH[1]}"
    elif [[ -n "$current_iface" && "$line" =~ inet[[:space:]]([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)[[:space:]]netmask[[:space:]](0x[0-9a-fA-F]+) ]]; then
      local ip="${BASH_REMATCH[1]}"
      local mask_hex="${BASH_REMATCH[2]#0x}"
      # Convert hex mask to CIDR prefix length
      local mask_dec=$((16#$mask_hex))
      local cidr=0
      for i in {0..31}; do
        (( (mask_dec >> (31 - i)) & 1 )) && ((cidr++)) || true
      done
      # Derive network base address
      IFS='.' read -r o1 o2 o3 o4 <<< "$ip"
      local net_base="$o1.$o2.$o3.0"
      echo "$current_iface $ip $net_base/$cidr"
      return
    fi
  done < <(ifconfig 2>/dev/null | grep -E "^en[0-9]+:|inet " | grep -v inet6)
  echo ""
}

IFACE_INFO=$(detect_interface)
if [ -z "$IFACE_INFO" ]; then
  echo "[ERROR] No active network interface found."
  exit 1
fi

IFACE=$(echo "$IFACE_INFO" | awk '{print $1}')
LOCAL_IP=$(echo "$IFACE_INFO" | awk '{print $2}')
SUBNET=$(echo "$IFACE_INFO" | awk '{print $3}')

# =============================================================================
# SCAN
# =============================================================================
echo "======================================================" | tee "$REPORT"
echo " Cinesys Network Health Report — $TIMESTAMP"         | tee -a "$REPORT"
echo "======================================================" | tee -a "$REPORT"
echo " Interface : $IFACE"                                  | tee -a "$REPORT"
echo " Local IP  : $LOCAL_IP"                               | tee -a "$REPORT"
echo " Subnet    : $SUBNET"                                 | tee -a "$REPORT"
echo "------------------------------------------------------" | tee -a "$REPORT"

echo ""
echo "[*] Running arp-scan on $SUBNET via $IFACE..."
ARP_OUTPUT=$(arp-scan --interface="$IFACE" "$SUBNET" 2>/dev/null | grep -E "^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" || true)

# =============================================================================
# PARSE ARP RESULTS + UPDATE DATABASE
# =============================================================================
NEW_DEVICES=()
SEEN_MACS=()

while IFS=$'\t' read -r ip mac vendor; do
  [ -z "$ip" ] && continue
  SEEN_MACS+=("$mac")

  # Try reverse DNS for hostname
  hostname=$(dns-sd -G v4 "$ip" 2>/dev/null | awk 'NR==2{print $4}' | sed 's/\.$//' || echo "unknown")
  [ -z "$hostname" ] && hostname="unknown"

  exists=$(jq --arg mac "$mac" 'any(.[]; .mac == $mac)' "$DB")

  if [ "$exists" = "false" ]; then
    # New device — run nmap to get open ports
    echo "[+] NEW device found: $ip ($mac) — scanning ports..."
    ports=$(nmap -sS --open -oG - "$ip" 2>/dev/null | grep "Ports:" | grep -oP '\d+(?=/open)' | tr '\n' ',' | sed 's/,$//' || echo "")

    jq --arg ip "$ip" --arg mac "$mac" --arg vendor "$vendor" \
       --arg hostname "$hostname" --arg ports "$ports" \
       --arg date "$TIMESTAMP" \
       '. += [{
         "mac": $mac,
         "ip": $ip,
         "hostname": $hostname,
         "vendor": $vendor,
         "open_ports": ($ports | split(",") | map(select(length > 0))),
         "first_seen": $date,
         "last_seen": $date,
         "status": "up",
         "notes": ""
       }]' "$DB" > "${DB}.tmp" && mv "${DB}.tmp" "$DB"

    NEW_DEVICES+=("$ip ($mac) — $vendor")
  else
    # Known device — update IP, last_seen, status
    jq --arg mac "$mac" --arg ip "$ip" --arg date "$TIMESTAMP" \
       'map(if .mac == $mac then .ip = $ip | .last_seen = $date | .status = "up" else . end)' \
       "$DB" > "${DB}.tmp" && mv "${DB}.tmp" "$DB"
  fi
done <<< "$ARP_OUTPUT"

# Mark devices not seen in this scan as down
ALL_MACS=$(jq -r '.[].mac' "$DB")
for mac in $ALL_MACS; do
  seen=false
  for s in "${SEEN_MACS[@]:-}"; do
    [ "$s" = "$mac" ] && seen=true && break
  done
  if [ "$seen" = "false" ]; then
    jq --arg mac "$mac" --arg date "$TIMESTAMP" \
       'map(if .mac == $mac then .status = "down" | .last_seen = $date else . end)' \
       "$DB" > "${DB}.tmp" && mv "${DB}.tmp" "$DB"
  fi
done

# =============================================================================
# HEALTH CHECK — PING ALL KNOWN DEVICES
# =============================================================================
echo "" | tee -a "$REPORT"
echo "[*] Health check — pinging all known devices..." | tee -a "$REPORT"
echo "" | tee -a "$REPORT"
printf "%-18s %-20s %-17s %-6s %-s\n" "IP" "HOSTNAME" "MAC" "STATUS" "LATENCY" | tee -a "$REPORT"
printf "%-18s %-20s %-17s %-6s %-s\n" "--" "--------" "---" "------" "-------" | tee -a "$REPORT"

jq -c '.[]' "$DB" | while IFS= read -r device; do
  ip=$(echo "$device" | jq -r '.ip')
  mac=$(echo "$device" | jq -r '.mac')
  hostname=$(echo "$device" | jq -r '.hostname')
  [ ${#hostname} -gt 20 ] && hostname="${hostname:0:17}..."

  ping_result=$(ping -c 2 -W 1 "$ip" 2>/dev/null | tail -1 || echo "")
  if echo "$ping_result" | grep -q "avg"; then
    latency=$(echo "$ping_result" | awk -F'/' '{print $5 "ms"}')
    status="UP"
  else
    latency="—"
    status="DOWN"
  fi

  printf "%-18s %-20s %-17s %-6s %-s\n" "$ip" "$hostname" "$mac" "$status" "$latency" | tee -a "$REPORT"
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
  echo " [!] NEW DEVICES DETECTED THIS SCAN:" | tee -a "$REPORT"
  for d in "${NEW_DEVICES[@]}"; do
    echo "     + $d" | tee -a "$REPORT"
  done
fi

echo "------------------------------------------------------" | tee -a "$REPORT"
echo " Report saved to: $REPORT"
echo "======================================================"
