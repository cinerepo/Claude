#!/usr/bin/env python3
"""
ingest.py — Cinesys IPAM ingestion script
Usage: python3 ingest.py <discovery_json> [--tenant Cinesys]

Reads a discovery run JSON, merges it into ipam_data.json,
auto-detects anomalies, and computes deltas. No LLM required.
"""

import json, sys, pathlib, argparse
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).parent
DATA_FILE = BASE / "ipam_data.json"

ANOMALY_DEFS = [
    {
        "key": "TELNET_OPEN",
        "port": 23,
        "severity": "high",
        "title": "Telnet (Port 23) Open",
        "detail": "Cleartext management protocol. Credentials visible to any LAN observer.",
        "action": "Disable Telnet. Use SSH or HTTPS management interfaces instead.",
    },
    {
        "key": "RDP_OPEN",
        "port": 3389,
        "severity": "medium",
        "title": "RDP (Port 3389) Exposed on Flat Segment",
        "detail": "Windows Remote Desktop reachable from entire subnet with no VLAN barrier.",
        "action": "Restrict via firewall ACL to specific source IPs, or move behind management VLAN.",
    },
    {
        "key": "VNC_OPEN",
        "port": 5900,
        "severity": "medium",
        "title": "VNC/KVM (Port 5900) Open",
        "detail": "Remote desktop/KVM access reachable from entire subnet.",
        "action": "Restrict VNC access to management jump hosts or disable if unused.",
    },
]

KNOWN_ANOMALIES = {
    "10.1.88.89": {
        "key": "ARP_CONFLICT",
        "severity": "high",
        "title": "ARP Conflict — Possible VRRP/HA VIP",
        "detail": "Two MACs respond to ARP for this IP: 00:50:56:a5:25:59 (VMware) and d4:76:a0:5d:cc:88 (Fortinet, same as gateway .1). Consistent with VRRP/HA VIP.",
        "action": "Confirm with network team whether .89 is an intentional VRRP/HA VIP. If not, investigate immediately.",
    },
    "10.1.88.97": {
        "key": "ROGUE_WIFI_DIRECT",
        "severity": "high",
        "title": "Rogue WiFi Direct Subnet (192.168.223.0/24)",
        "detail": "HP printer HPI7DC36A (Lindas Loft) acting as WiFi Direct AP hosting subnet 192.168.223.0/24 while on corporate LAN.",
        "action": "Log into printer at 10.1.88.97 → disable WiFi Direct / Wireless Direct. Verify wlan interfaces go down.",
    },
    "IOT_VLAN": {
        "key": "IOT_ON_CORP_VLAN",
        "severity": "medium",
        "title": "Alarm.com IoT Devices on Corporate VLAN",
        "detail": "6 Alarm.com security devices (OUI b8:3a:9d) on primary corporate LAN with no VLAN segmentation.",
        "action": "Create dedicated IoT VLAN. Move all 6 devices. Firewall: IoT → Alarm.com cloud only.",
    },
    "IDRAC_VLAN": {
        "key": "OOB_ON_PROD_VLAN",
        "severity": "medium",
        "title": "Dell iDRAC Management IPs on Production VLAN",
        "detail": "iDRAC OOB management controllers (.11/.12) allocated on production subnet. SNMP community 'public' active.",
        "action": "Move iDRACs to dedicated OOB management VLAN. Rotate SNMP community from 'public'.",
    },
    "DUP_MAC": {
        "key": "DUPLICATE_MAC",
        "severity": "medium",
        "title": "Duplicate VMware MAC — Cloned VM",
        "detail": "IPs 10.1.88.130 and 10.1.88.135 both report MAC 00:0c:29:69:69:cc. Indicates a cloned VM without MAC regeneration.",
        "action": "Find the VM in vSphere. Regenerate MAC on the clone.",
    },
    "10.1.88.113": {
        "key": "LOCAL_ADMIN_MAC",
        "severity": "low",
        "title": "Unknown Locally-Administered MAC",
        "detail": "MAC a2:39:35:5b:90:a1 has the locally-administered bit set. Common for VPN, Docker, or privacy-MAC endpoints.",
        "action": "Identify the device. Accept if legitimate; investigate if unexpected.",
    },
}

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def load_existing():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {
        "meta": {"tenant": "Cinesys", "last_updated": None, "run_count": 0},
        "prefixes": [
            {"network": "10.1.88.0/24", "status": "active", "role": "client-LAN",
             "gateway": "10.1.88.1", "tenant": "Cinesys", "total_hosts": 254,
             "discovered": 0, "utilization_pct": "0%"},
            {"network": "192.168.223.0/24", "status": "quarantine",
             "role": "rogue-ap-subnet", "tenant": "Cinesys",
             "note": "HP printer WiFi Direct — not a sanctioned network"},
        ],
        "devices": [],
        "anomalies": [],
        "runs": [],
    }

def detect_anomalies(devices, existing_anomalies):
    anomalies = {a["id"]: a for a in existing_anomalies}
    run_label = f"Run {len(anomalies)//3 + 1}"  # rough label

    def add(anid, severity, title, detail, action, ip):
        if anid not in anomalies:
            anomalies[anid] = {
                "id": anid, "severity": severity, "title": title,
                "detail": detail, "action": action, "ip": ip,
                "status": "open", "discovered": now_iso(),
            }

    # Port-based anomalies
    telnet_hosts, rdp_hosts, vnc_hosts = [], [], []
    for d in devices:
        ports = d.get("open_ports", [])
        ip = d["ip"]
        if 23 in ports:
            telnet_hosts.append(ip)
        if 3389 in ports:
            rdp_hosts.append(ip)
        if 5900 in ports:
            vnc_hosts.append(ip)

    if telnet_hosts:
        add("TELNET_OPEN", "high", "Telnet (Port 23) Open — Cleartext Management",
            f"Telnet open on: {', '.join(telnet_hosts)}. Cleartext protocol exposes credentials to any LAN observer. Two are NETGEAR network infrastructure.",
            "Disable Telnet on all affected hosts. Use SSH or HTTPS management instead.",
            ", ".join(telnet_hosts))
    if rdp_hosts:
        add("RDP_OPEN", "medium", "RDP (Port 3389) Exposed on Flat Segment",
            f"Windows RDP open on: {', '.join(rdp_hosts)}. No VLAN barrier — reachable from entire subnet.",
            "Restrict RDP via firewall ACL to specific source IPs or move behind management VLAN.",
            ", ".join(rdp_hosts))
    if vnc_hosts:
        add("VNC_OPEN", "medium", f"VNC/KVM (Port 5900) Open on {len(vnc_hosts)} Hosts",
            f"Port 5900 open on: {', '.join(vnc_hosts)}. Includes Apple workstations (Screen Sharing) and BMC/iDRAC interfaces.",
            "Disable Screen Sharing on Apple workstations or restrict to specific IPs. ACL-restrict BMC/iDRAC KVM.",
            ", ".join(vnc_hosts))

    # Known static anomalies
    ip_set = {d["ip"] for d in devices}
    device_map = {d["ip"]: d for d in devices}

    if "10.1.88.89" in ip_set:
        ka = KNOWN_ANOMALIES["10.1.88.89"]
        add("ARP_CONFLICT_89", ka["severity"], ka["title"], ka["detail"], ka["action"], "10.1.88.89")

    if "10.1.88.97" in ip_set:
        ka = KNOWN_ANOMALIES["10.1.88.97"]
        add("ROGUE_WIFI_DIRECT_97", ka["severity"], ka["title"], ka["detail"], ka["action"], "10.1.88.97")
        # Crash loop check
        d97 = device_map["10.1.88.97"]
        if d97.get("uptime_ticks") and d97["uptime_ticks"] < 5000000:  # < ~14h uptime
            add("CRASH_LOOP_97", "medium", "HP Printer Crash Loop — Lindas Loft",
                f"Printer at 10.1.88.97 (HPI7DC36A, Lindas Loft) shows short uptime ({d97['uptime_ticks']//100//3600}h). Device appears to reboot repeatedly.",
                "Physically inspect printer in Lindas Loft. Check power supply, firmware, event log via web UI at 10.1.88.97. Also disable WiFi Direct.",
                "10.1.88.97")

    # IoT on corporate VLAN
    alarm_hosts = [d["ip"] for d in devices if "Alarm.com" in d.get("vendor_oui", d.get("vendor", ""))]
    if alarm_hosts:
        ka = KNOWN_ANOMALIES["IOT_VLAN"]
        add("IOT_CORP_VLAN", ka["severity"], ka["title"],
            f"Alarm.com devices on corporate LAN: {', '.join(alarm_hosts)}. " + ka["detail"],
            ka["action"], ", ".join(alarm_hosts))

    # iDRAC on prod VLAN
    idrac_hosts = [d["ip"] for d in devices if d.get("inferred_type") == "dell_idrac"]
    if idrac_hosts:
        ka = KNOWN_ANOMALIES["IDRAC_VLAN"]
        add("IDRAC_PROD_VLAN", ka["severity"], ka["title"],
            f"iDRAC interfaces on production subnet: {', '.join(idrac_hosts)}. " + ka["detail"],
            ka["action"], ", ".join(idrac_hosts))

    # Duplicate MACs
    mac_map = {}
    for d in devices:
        m = d.get("mac_address", d.get("mac"))
        if m:
            mac_map.setdefault(m, []).append(d["ip"])
    for mac, ips in mac_map.items():
        if len(ips) > 1:
            add(f"DUP_MAC_{mac.replace(':','')}",
                "medium", f"Duplicate MAC Address — {mac}",
                f"MAC {mac} appears on multiple IPs: {', '.join(ips)}. Likely a cloned VM without MAC regeneration.",
                "Identify both VMs in vSphere. Regenerate MAC on the clone.",
                ", ".join(ips))

    # Locally-administered MAC
    if "10.1.88.113" in ip_set:
        ka = KNOWN_ANOMALIES["10.1.88.113"]
        add("LOCAL_ADMIN_MAC_113", ka["severity"], ka["title"], ka["detail"], ka["action"], "10.1.88.113")

    # Non-standard ports
    nonstd = {8888: "Jupyter/dev server?", 9000: "Portainer/SonarQube?", 9090: "Cockpit/Prometheus?"}
    for d in devices:
        for port, guess in nonstd.items():
            if port in d.get("open_ports", []):
                add(f"NONSTD_PORT_{d['ip'].replace('.','_')}_{port}",
                    "low", f"Non-Standard Service Port :{port} on {d['ip']}",
                    f"{d['ip']} has port {port} open ({guess}). Vendor: {d.get('vendor',d.get('vendor_oui','?'))}.",
                    f"Identify the service on :{port}. Ensure it requires auth and consider whether it belongs on the flat corporate LAN.",
                    d["ip"])

    return list(anomalies.values())

def merge_device(existing_map, new_dev, run_ts):
    ip = new_dev["management_ip"]
    mac = new_dev.get("mac_address")
    ports = [p["port"] for p in new_dev.get("open_ports", [])]

    if ip in existing_map:
        d = existing_map[ip]
        d["last_seen"] = run_ts
        d["status"] = "live" if new_dev.get("icmp_responsive", True) else "intermittent"
        if mac:
            d["mac"] = mac
        d["vendor"] = new_dev.get("vendor") or new_dev.get("vendor_oui") or d.get("vendor")
        d["vendor_oui"] = new_dev.get("vendor_oui") or d.get("vendor_oui")
        d["snmp_reachable"] = new_dev.get("snmp_reachable", False)
        if new_dev.get("uptime_ticks"):
            d["uptime_ticks"] = new_dev["uptime_ticks"]
        if new_dev.get("hostname"):
            d["hostname"] = new_dev["hostname"]
        if new_dev.get("location"):
            d["location"] = new_dev["location"]
        d["open_ports"] = ports
        d["inferred_type"] = new_dev.get("inferred_type") or d.get("inferred_type")
        d["device_class"] = new_dev.get("device_class") or d.get("device_class")
    else:
        existing_map[ip] = {
            "ip": ip,
            "mac": mac,
            "vendor": new_dev.get("vendor") or new_dev.get("vendor_oui"),
            "vendor_oui": new_dev.get("vendor_oui"),
            "device_class": new_dev.get("device_class", "unknown"),
            "inferred_type": new_dev.get("inferred_type", "unknown"),
            "hostname": new_dev.get("hostname"),
            "location": new_dev.get("location"),
            "status": "live" if new_dev.get("icmp_responsive", True) else "intermittent",
            "snmp_reachable": new_dev.get("snmp_reachable", False),
            "uptime_ticks": new_dev.get("uptime_ticks"),
            "open_ports": ports,
            "first_seen": run_ts,
            "last_seen": run_ts,
            "anomaly_flags": [],
        }

def main():
    parser = argparse.ArgumentParser(description="Ingest a discovery JSON into ipam_data.json")
    parser.add_argument("discovery_json", help="Path to discovery run JSON file")
    parser.add_argument("--tenant", default="Cinesys")
    args = parser.parse_args()

    src = pathlib.Path(args.discovery_json)
    if not src.exists():
        print(f"ERROR: {src} not found"); sys.exit(1)

    print(f"Loading {src.name}...")
    run_data = json.loads(src.read_text())

    print(f"Loading existing IPAM data...")
    ipam = load_existing()
    ipam["meta"]["tenant"] = args.tenant

    run_ts = run_data.get("completed_at", now_iso())
    run_id = run_data.get("discovery_run_id", "unknown")
    run_num = run_data.get("run_number", len(ipam["runs"]) + 1)

    # Build current device map
    existing_map = {d["ip"]: d for d in ipam["devices"]}
    prev_ips = set(existing_map.keys())

    # Merge all devices from this run
    print(f"Merging {len(run_data['devices'])} devices...")
    run_ips = set()
    for dev in run_data["devices"]:
        merge_device(existing_map, dev, run_ts)
        run_ips.add(dev["management_ip"])

    # Mark missing devices
    gone = prev_ips - run_ips
    new_ips = run_ips - prev_ips
    for ip in gone:
        if existing_map[ip]["status"] == "live":
            existing_map[ip]["status"] = "offline"
            print(f"  {ip} → offline (not seen this run)")

    # Rebuild devices list sorted by IP
    def ip_sort(d):
        return tuple(int(x) for x in d["ip"].split("."))
    ipam["devices"] = sorted(existing_map.values(), key=ip_sort)

    # Update prefix utilization
    live_count = sum(1 for d in ipam["devices"] if d["status"] == "live")
    for p in ipam["prefixes"]:
        if p["network"] == "10.1.88.0/24":
            p["discovered"] = live_count
            p["utilization_pct"] = f"{live_count/254*100:.1f}%"
            p["last_run_id"] = run_id

    # Detect anomalies
    print("Detecting anomalies...")
    prev_count = len(ipam["anomalies"])
    ipam["anomalies"] = detect_anomalies(ipam["devices"], ipam["anomalies"])
    new_anomalies = len(ipam["anomalies"]) - prev_count

    # Add run record
    ipam["runs"].append({
        "run_id": run_id,
        "run_number": run_num,
        "scope": run_data.get("scope"),
        "source_ip": run_data.get("source_ip"),
        "source_interface": run_data.get("source_interface"),
        "started_at": run_data.get("started_at"),
        "completed_at": run_data.get("completed_at"),
        "hosts_found": len(run_ips),
        "hosts_gone": len(gone),
        "hosts_new": len(new_ips),
        "methods_used": run_data.get("discovery_methods_used", []),
        "methods_skipped": [m["method"] for m in run_data.get("discovery_methods_skipped", [])],
        "port_scan": run_data.get("port_scan_details"),
    })

    ipam["meta"]["last_updated"] = now_iso()
    ipam["meta"]["run_count"] = len(ipam["runs"])

    DATA_FILE.write_text(json.dumps(ipam, indent=2))
    print(f"\nDone. ipam_data.json updated.")
    print(f"  Devices total : {len(ipam['devices'])}")
    print(f"  Live          : {live_count}")
    print(f"  Offline       : {sum(1 for d in ipam['devices'] if d['status']=='offline')}")
    print(f"  Intermittent  : {sum(1 for d in ipam['devices'] if d['status']=='intermittent')}")
    print(f"  New this run  : {len(new_ips)}")
    print(f"  Gone this run : {len(gone)}")
    print(f"  Anomalies     : {len(ipam['anomalies'])} ({new_anomalies:+d})")
    print(f"  Runs logged   : {len(ipam['runs'])}")

if __name__ == "__main__":
    main()
