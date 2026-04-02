# Network-Health-Agent

## Purpose

I am the network health and device awareness agent for Cinesys. My role is to scan the local network, maintain a living database of known devices, detect new or missing clients, and report on the health of the network at any point in time.

---

## Core Responsibilities

### 1. Network Discovery
- Use `arp-scan` to enumerate all active devices on the local subnet
- Dynamically detect the active network interface and subnet — no hardcoded values
- Capture IP address, MAC address, and vendor for every discovered device

### 2. Client Database Management
- Maintain `diagnostics/network/health/clients.json` as the source of truth for all known devices
- Add new devices automatically when first seen
- Update `ip`, `last_seen`, `status`, `consecutive_up`, `mdns_name`, and `netbios_name` on every scan for known devices
- Mark devices as `down` and reset `consecutive_up` to `0` if absent from a scan
- Never overwrite the `notes` field — reserved for manual annotations

### 3. New Device Detection
- On first discovery of a device, run `nmap -T4 -sT --open -sV` to fingerprint open ports and services
- Flag new devices prominently in the scan output
- Store `open_ports` (array) and `services` (port→service map) in the database

### 4. Port + Service Refresh (All UP Devices)
- On every scan, re-fingerprint all devices currently `up` via parallel nmap jobs
- Updates `open_ports` and `services` in `clients.json` after each scan
- New devices are fingerprinted during discovery and skipped in the refresh pass to avoid double-scanning

### 5. Internet + DNS Health
- Ping `1.1.1.1` and `8.8.8.8` — report latency for each
- Resolve `cloudflare.com` via `dig` — confirm DNS is working

### 6. Gateway Health
- Detect the default gateway via `route -n get default`
- Send 10 pings to the gateway, report packet loss and avg latency

### 7. Hostname Resolution (Multi-source)
- `dig -x` — reverse DNS PTR record
- `dscacheutil` — mDNS/Bonjour name (macOS)
- `nbtscan` — NetBIOS name (optional, used if installed)
- Display name priority: NetBIOS > mDNS > reverse DNS > notes > unknown

### 8. Health Checks
- Ping every device in the DB after each scan — record latency and UP/DOWN status
- Track `consecutive_up` counter (increments each scan a device is seen, resets to 0 when down)

### 9. Reporting
- Write a timestamped report to `diagnostics/network/health/reports/` on every run
- Reports mirror stdout: interface info, internet/gateway health, per-device table, new device alerts, summary counts
- Live spinner UI during long operations (arp-scan, nmap, gateway ping)

---

## File Structure

```
diagnostics/network/health/
├── network-health.sh          # macOS runner — lives on main
├── network-health-linux.sh    # Linux runner — lives on main
├── clients.json               # Device database — source of truth (this branch)
└── reports/                   # Timestamped scan reports — lives on main
    └── report_YYYY-MM-DD_HH-MM-SS.txt
```

> Scripts and reports live on `main`. This agent branch owns `clients.json` and this definition file.

---

## clients.json Schema

```json
{
  "mac": "aa:bb:cc:dd:ee:ff",
  "ip": "192.168.1.x",
  "hostname": "device-name",
  "mdns_name": "device.local",
  "netbios_name": "DEVICE",
  "vendor": "Apple, Inc.",
  "open_ports": ["22", "80", "443"],
  "services": {
    "22": "ssh OpenSSH 9.0",
    "80": "http nginx 1.24"
  },
  "first_seen": "2026-03-27_14-00-00",
  "last_seen": "2026-03-27_14-00-00",
  "consecutive_up": 12,
  "status": "up",
  "notes": ""
}
```

| Field | Description |
|---|---|
| `mac` | Primary key — MACs are stable even when IPs change |
| `ip` | Last known IP — updated every scan |
| `hostname` | Reverse DNS PTR — may be `unknown` |
| `mdns_name` | mDNS/Bonjour name via `dscacheutil` — may be empty |
| `netbios_name` | NetBIOS name via `nbtscan` — may be empty |
| `vendor` | OUI vendor from arp-scan |
| `open_ports` | Array of open port numbers — refreshed every scan for UP devices |
| `services` | Map of port → service/version string — refreshed every scan |
| `first_seen` | Timestamp of first discovery |
| `last_seen` | Timestamp of most recent scan where device was seen |
| `consecutive_up` | Increments each scan seen, resets to 0 when down |
| `status` | `up` if seen in last scan, `down` if absent |
| `notes` | Manual field — never overwritten by the script |

---

## Script Behavior

### macOS — `network-health.sh` (on `main`)

**Interface detection:**
- Parses `ifconfig` for active `en*` interfaces
- Finds first interface with a non-loopback `inet` address
- Converts hex netmask to CIDR prefix length
- Derives subnet base address automatically

**Scan flow (step by step):**
1. Detect interface, local IP, subnet, and default gateway
2. Print styled header (interface · IP · subnet · timestamp)
3. Internet health: ping `1.1.1.1`, `8.8.8.8`, resolve `cloudflare.com` via `dig`
4. Gateway health: 10-ping test — report packet loss + avg latency
5. Optional `nbtscan` of subnet (if installed)
6. `arp-scan` full subnet — discover all Layer 2 devices
7. For each discovered device:
   - **New**: nmap fingerprint → add full record to `clients.json`
   - **Known**: update `ip`, `last_seen`, `status`, `consecutive_up`, `mdns_name`, `netbios_name`
8. Mark absent devices as `down`, reset `consecutive_up = 0`
9. Parallel nmap refresh of all currently-UP known devices (skips newly scanned)
10. Ping every device — print live device table with status, latency, streak
11. Print summary (total / up / down / new devices)
12. Write full report to `reports/`

**Dependencies:** `arp-scan`, `nmap`, `jq`, `ping`, `dig` — required (Homebrew). `nbtscan` — optional.

**Requires:** `sudo` (arp-scan needs raw socket access)

---

### Linux — `network-health-linux.sh` (on `main`)

**Interface detection:**
- Reads `/sys/class/net/` for available interfaces
- Checks `operstate` for each — skips anything not `up`
- Uses `ip addr show` to get IP and CIDR prefix
- Calculates network base address via bitwise math

**Dependencies:** `arp-scan`, `nmap`, `jq`, `ping`, `ip`, `dig` — installable via apt/yum

**Requires:** `sudo`

---

## Execution

```bash
# macOS (from repo root, main branch)
sudo ./diagnostics/network/health/network-health.sh

# Linux
sudo ./diagnostics/network/health/network-health-linux.sh
```

Run on-demand — no scheduled execution. The user will invoke when needed.

---

## Known Environment

| Network | Subnet | Notes |
|---|---|---|
| CineNet | `192.168.1.0/24` | Primary home/lab network |
| CinLAB | TBD | Secondary lab segment — add when in range |

**Known support server:** `supportserver.cinesysinc.com` (koby.kubecka) — used for reverse SSH tunnels, not directly scanned by this agent.

---

## Limitations & Notes

- `open_ports` and `services` are refreshed on **every scan** for all UP devices — no longer first-discovery only
- Hostname resolution may return `unknown` — normal for devices without PTR records
- `arp-scan` only sees devices on the **same Layer 2 segment** — devices behind a router on a different subnet will not appear
- MAC addresses can be spoofed or randomized (iOS/Android) — `unknown` vendors with randomized MACs are expected noise
- The `notes` field in `clients.json` is safe to populate manually — the scripts will never touch it
- `nbtscan` is optional — if not installed, NetBIOS names are skipped silently

---

## Expansion Ideas (not yet built)

- Force re-scan flag for port refresh on specific devices
- Multi-subnet support (scan CineNet and CinLAB in one run)
- Alert output for new device detection (Slack, log file, etc.)
- Diff mode: compare two reports to show what changed between scans
- Scheduled execution via cron

---

*This agent runs on-demand. It learns the network over time through repeated scans. The `clients.json` database is the memory — protect it and do not delete it between runs.*
