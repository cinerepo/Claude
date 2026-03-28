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
- Update IP address and last-seen timestamp on every scan for known devices
- Mark devices as `down` if they are absent from a scan
- Never overwrite the `notes` field — this is reserved for manual annotations

### 3. New Device Detection
- On first discovery of a device, run `nmap -sS` to fingerprint open ports
- Flag new devices prominently in the scan report
- Store open ports in the database for future reference

### 4. Health Checks
- Ping every known device in the database after each scan
- Report latency and UP/DOWN status per device
- Reflect current status back into `clients.json`

### 5. Reporting
- Write a timestamped report to `diagnostics/network/health/reports/` on every run
- Reports include: interface info, subnet, per-device health table, new device alerts, and summary counts

---

## File Structure

```
diagnostics/network/health/
├── network-health.sh          # macOS runner
├── network-health-linux.sh    # Linux runner
├── clients.json               # Device database — source of truth
└── reports/                   # Timestamped scan reports (auto-generated)
    └── report_YYYY-MM-DD_HH-MM-SS.txt
```

---

## clients.json Schema

Each entry in the array represents a known device:

```json
{
  "mac": "aa:bb:cc:dd:ee:ff",
  "ip": "192.168.1.x",
  "hostname": "device-name",
  "vendor": "Apple, Inc.",
  "open_ports": ["22", "80", "443"],
  "first_seen": "2026-03-27_14-00-00",
  "last_seen": "2026-03-27_14-00-00",
  "status": "up",
  "notes": ""
}
```

| Field | Description |
|---|---|
| `mac` | Primary key — MACs are stable even when IPs change |
| `ip` | Last known IP — updated every scan |
| `hostname` | Resolved via reverse DNS — may be `unknown` |
| `vendor` | OUI vendor from arp-scan |
| `open_ports` | Captured on first discovery via nmap — not re-scanned unless manually triggered |
| `first_seen` | Timestamp of first discovery |
| `last_seen` | Timestamp of most recent scan where device was seen |
| `status` | `up` if seen in last scan, `down` if absent |
| `notes` | Manual field — never overwritten by the script |

---

## Script Behavior

### macOS — `network-health.sh`

**Interface detection:**
- Parses `ifconfig` output for active `en*` interfaces
- Finds the first interface with a non-loopback `inet` address
- Converts hex netmask to CIDR prefix length
- Derives the network base address automatically

**Dependencies:** `arp-scan`, `nmap`, `jq`, `ping` — all installable via Homebrew

**Requires:** `sudo` (arp-scan needs raw socket access)

---

### Linux — `network-health-linux.sh`

**Interface detection:**
- Reads `/sys/class/net/` for available interfaces
- Checks `operstate` file for each interface — skips anything not `up`
- Uses `ip addr show` to get IP and CIDR prefix
- Calculates network base address via bitwise math

**Dependencies:** `arp-scan`, `nmap`, `jq`, `ping`, `ip`, `dig` — installable via apt/yum

**Requires:** `sudo`

---

## Execution

```bash
# macOS
sudo ./diagnostics/network/health/network-health.sh

# Linux
sudo ./diagnostics/network/health/network-health-linux.sh
```

Run on-demand — no scheduled execution. The user will invoke when needed.

---

## Scan Flow (Step by Step)

1. Detect active interface and subnet
2. Run `arp-scan` against the full subnet
3. For each discovered device:
   - If **new**: run `nmap -sS`, add full record to `clients.json`
   - If **known**: update `ip`, `last_seen`, `status = up`
4. For each device in the DB **not seen** in this scan: set `status = down`
5. Ping every device in the DB — record latency
6. Print health table to stdout and write to report file
7. Print summary: total / up / down / new devices

---

## Known Environment

| Network | Subnet | Notes |
|---|---|---|
| CineNet | `192.168.1.0/24` | Primary home/lab network |
| CinLAB | TBD | Secondary lab segment — add when in range |

**Known support server:** `supportserver.cinesysinc.com` (koby.kubecka) — used for reverse SSH tunnels, not directly scanned by this agent.

---

## Limitations & Notes

- `open_ports` is only captured on **first discovery** — if you want a re-scan of ports on a known device, manually remove the device entry from `clients.json` or add a force-rescan flag
- Hostname resolution (`dns-sd` on macOS, `dig -x` on Linux) may return `unknown` for devices without PTR records — this is normal
- `arp-scan` only sees devices on the **same Layer 2 segment** — devices behind a router on a different subnet will not appear
- MAC addresses can be spoofed or randomized (iOS/Android do this) — treat `unknown` vendors with randomized MACs as expected noise on home networks
- The `notes` field in `clients.json` is safe to populate manually — the scripts will never touch it

---

## Expansion Ideas (not yet built)

- Force re-scan flag for port refresh on existing devices
- Multi-subnet support (scan CineNet and CinLAB in one run)
- Alert output for new device detection (Slack, log file, etc.)
- Diff mode: compare two reports to show what changed between scans

---

*This agent runs on-demand. It learns the network over time through repeated scans. The clients.json database is the memory — protect it and do not delete it between runs.*
