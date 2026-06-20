"""
discover.py — Reconciliation engine CLI

Pull end-host data from Netdisco, stage it locally, classify it by VLAN
intent and stability, then selectively promote assets to NetBox via Diode.

Nothing reaches NetBox automatically — 'managed' assets in the staging DB
are only pushed when you explicitly run the promote command.
"""
import sys
import argparse
from datetime import datetime, timezone

from config import load_config
from netdisco_client import NetdiscoClient
from staging import StagingDB, ObservedAsset
from classifier import load_rules, load_consumer_vendors, classify, vlan_defaults
from netboxlabs.diode.sdk import DiodeClient
from netboxlabs.diode.sdk.ingester import (
    Device, DeviceRole, DeviceType, Entity, IPAddress,
    Interface, Manufacturer, Site
)

try:
    from mac_vendor_lookup import MacLookup
    _mac_lookup = MacLookup()
except Exception:
    _mac_lookup = None


def _oui_vendor(mac: str) -> str | None:
    if _mac_lookup is None:
        return None
    try:
        return _mac_lookup.lookup(mac)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CLI setup
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="discover",
        description=(
            "Netdisco host discovery reconciliation engine.\n\n"
            "Pulls end-host data from Netdisco's MAC/ARP tables, stages it in a\n"
            "local SQLite database, classifies assets by VLAN intent and stability,\n"
            "and lets you selectively promote assets to NetBox."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Classification states:\n"
            "  unclassified  Seen but not yet stable enough to act on\n"
            "  ignore        Permanently excluded (consumer device / ignored VLAN)\n"
            "  candidate     Stable enough for review — requires manual promote\n"
            "  managed       Promoted to NetBox\n"
            "  stale         Was managed, not seen in STALE_DAYS days\n\n"
            "Workflow:\n"
            "  1. python discover.py run\n"
            "  2. python discover.py list-candidates\n"
            "  3. python discover.py promote <mac|ip> --name myserver --role Server\n"
            "  4. python discover.py list-managed\n\n"
            "Thresholds are set in .env:\n"
            "  MIN_DAYS_STABLE  Days before unclassified → candidate/managed (default 7)\n"
            "  STALE_DAYS       Days before managed → stale warning (default 30)\n"
        ),
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    sub.add_parser(
        "run",
        help="Pull nodes from Netdisco, update staging DB, classify all assets",
        description="Fetches the MAC-table from every discovered device in Netdisco, "
                    "resolves OUI vendors, updates the staging DB, and re-classifies "
                    "all assets according to rules.yaml.",
    )

    sub.add_parser(
        "status",
        help="Summary count of assets by classification",
        description="Prints a one-line-per-state summary of everything in the staging DB.",
    )

    sub.add_parser(
        "list-all",
        help="Show every asset in the staging DB (all classifications)",
        description="Dumps the full staging table — equivalent to "
                    "SELECT mac, ip, vlan, vendor, days_stable, classification, reason "
                    "FROM observed_assets ORDER BY classification, vlan.",
    )

    sub.add_parser(
        "list-candidates",
        help="Show assets stable enough for review (candidate state)",
        description="Assets on lab/corporate VLANs that have been stable long enough "
                    "to promote. Review these and run 'promote' or 'ignore' on each.",
    )

    sub.add_parser(
        "list-managed",
        help="Show assets that have been promoted to NetBox",
    )

    sub.add_parser(
        "list-stale",
        help="Show managed assets not seen recently (STALE_DAYS threshold)",
        description="Managed assets that haven't appeared in the MAC table in STALE_DAYS "
                    "days. These may need to be decommissioned.",
    )

    sub.add_parser(
        "list-unclassified",
        help="Show assets seen but not yet stable enough to classify",
        description="Assets that will graduate to candidate/managed once they hit "
                    "the MIN_DAYS_STABLE threshold.",
    )

    sub.add_parser(
        "list-ignored",
        help="Show permanently ignored assets",
        description="Consumer devices and ignored-VLAN assets. "
                    "Run 'ignore <mac>' to manually add to this list.",
    )

    p_promote = sub.add_parser(
        "promote",
        help="Promote a candidate asset to NetBox",
        description="Pushes the asset to NetBox via Diode and marks it managed. "
                    "Default name is the IP address (or MAC if no IP). "
                    "Default role/site come from rules.yaml for the asset's VLAN.",
    )
    p_promote.add_argument("target", help="MAC address (aa:bb:cc:dd:ee:ff) or IP address")
    p_promote.add_argument("--name",   help="Device name in NetBox (default: IP or MAC)")
    p_promote.add_argument("--role",   help="Device role override (default: from rules.yaml)")
    p_promote.add_argument("--site",   help="Site override (default: from rules.yaml)")
    p_promote.add_argument("--vendor", help="Manufacturer override when OUI lookup has no result")

    p_ignore = sub.add_parser(
        "ignore",
        help="Permanently ignore an asset",
        description="Marks the asset as ignored. It will never be auto-promoted. "
                    "The entry stays in the staging DB for audit purposes.",
    )
    p_ignore.add_argument("target", help="MAC address or IP address")
    p_ignore.add_argument("--reason", default="Manually ignored", help="Reason for ignoring")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    config = load_config()
    db = StagingDB(config.staging_db)

    dispatch = {
        "run":              lambda: cmd_run(config, db),
        "status":           lambda: cmd_status(db),
        "list-all":         lambda: cmd_list_all(db),
        "list-candidates":  lambda: cmd_list(db, "candidate"),
        "list-managed":     lambda: cmd_list(db, "managed"),
        "list-stale":       lambda: cmd_stale(db, config),
        "list-unclassified":lambda: cmd_list(db, "unclassified"),
        "list-ignored":     lambda: cmd_list(db, "ignore"),
        "promote":          lambda: cmd_promote(args, config, db),
        "ignore":           lambda: cmd_ignore(args, db),
    }

    dispatch[args.command]()
    db.close()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_run(config, db):
    rules = load_rules(config.rules_file)
    consumer_vendors = load_consumer_vendors(config.consumer_vendors_file)

    nd = NetdiscoClient(config)
    nd.login()

    # Build MAC→IP lookup from configured subnets before processing nodes
    mac_to_ip: dict[str, str] = {}
    if rules.ip_inventory_subnets:
        print(f"[netdisco] pulling IP inventory for {len(rules.ip_inventory_subnets)} subnet(s)...")
        for subnet in rules.ip_inventory_subnets:
            print(f"  {subnet}...")
            entries = nd.get_ip_inventory(subnet)
            mac_to_ip.update(entries)
        print(f"  {len(mac_to_ip)} MAC→IP mappings found")

    print("[netdisco] fetching infrastructure devices for node discovery...")
    devices = nd.get_all_devices()

    counts = {"new": 0, "updated": 0, "classified": 0}

    for device in devices:
        print(f"  pulling nodes from {device.display_name} ({device.ip})...")
        nodes = nd.get_nodes(device.ip)
        print(f"    {len(nodes)} nodes")

        for node in nodes:
            days_stable = _days_between(node.time_first, node.time_last)

            # OUI vendor lookup — node table rarely carries vendor
            vendor = node.vendor or _oui_vendor(node.mac)

            # IP enrichment from ipinventory report
            node_ip = node.ip or mac_to_ip.get(node.mac)

            existing = db.get_by_mac(node.mac)
            is_new = existing is None

            asset = ObservedAsset(
                mac=node.mac,
                ip=node_ip,
                vlan=node.vlan,
                switch=node.switch,
                port=node.port,
                vendor=vendor,
                hostname=node.dns,
                first_seen=node.time_first,
                last_seen=node.time_last,
                days_stable=days_stable,
                last_evaluated=_now(),
            )

            # Only skip reclassification for human-set states:
            #   managed               → set by 'promote' command
            #   ignore + ignore_reason → set by 'ignore' command
            # Auto-ignores (consumer vendor rule) have no ignore_reason and
            # should be re-evaluated when the vendor list changes.
            is_human_locked = existing and (
                existing.classification == "managed" or
                (existing.classification == "ignore" and existing.ignore_reason)
            )
            if is_human_locked:
                db.upsert(asset)
                continue

            classification, reason = classify(
                asset, rules, consumer_vendors, config.min_days_stable
            )
            asset.classification = classification
            asset.classification_reason = reason

            db.upsert(asset)
            counts["new" if is_new else "updated"] += 1
            if classification != "unclassified":
                counts["classified"] += 1

    nd.close()

    print(f"\n[staging] new={counts['new']}  updated={counts['updated']}  "
          f"classified={counts['classified']}")
    print()
    cmd_status(db)


def cmd_status(db):
    summary = db.summary()
    total = sum(summary.values())
    print(f"\n{'Classification':<20} {'Count':>6}")
    print("-" * 28)
    for state in ("managed", "candidate", "unclassified", "ignore"):
        print(f"  {state:<18} {summary.get(state, 0):>6}")
    others = {k: v for k, v in summary.items()
              if k not in ("managed", "candidate", "unclassified", "ignore")}
    for k, v in others.items():
        print(f"  {k:<18} {v:>6}")
    print("-" * 28)
    print(f"  {'TOTAL':<18} {total:>6}\n")


def cmd_list_all(db):
    """Show every asset in the staging DB regardless of classification."""
    import sqlite3
    conn = sqlite3.connect(db._path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT mac, ip, vlan, vendor,
               ROUND(days_stable, 1) AS days,
               classification, classification_reason
        FROM observed_assets
        ORDER BY classification, CAST(vlan AS INTEGER), mac
    """).fetchall()
    conn.close()

    if not rows:
        print("Staging DB is empty. Run: python discover.py run")
        return

    print(f"\n{'ALL ASSETS'} ({len(rows)} total)\n")
    hdr = f"{'MAC':<20} {'IP':<16} {'VLAN':<6} {'Vendor':<32} {'Days':>5}  {'State':<14} Reason"
    print(hdr)
    print("-" * 115)

    current_state = None
    for r in rows:
        if r["classification"] != current_state:
            current_state = r["classification"]
            print(f"\n  -- {current_state.upper()} --")
        vendor  = (r["vendor"] or "—")[:31]
        ip      = r["ip"] or "—"
        vlan    = r["vlan"] or "—"
        days    = f"{r['days']:.1f}" if r["days"] is not None else "—"
        reason  = r["classification_reason"] or ""
        print(f"  {r['mac']:<18} {ip:<16} {vlan:<6} {vendor:<32} {days:>5}  {r['classification']:<14} {reason}")
    print()


def cmd_list(db, classification):
    assets = db.list_by_classification(classification)
    if not assets:
        print(f"\nNo {classification} assets.\n")
        return

    label = classification.upper()
    print(f"\n{label} ({len(assets)})\n")
    print(f"{'MAC':<20} {'IP':<16} {'VLAN':<6} {'Vendor':<32} {'Days':>5}  Reason")
    print("-" * 108)
    for a in assets:
        vendor = (a.vendor or "—")[:31]
        ip     = a.ip or "—"
        vlan   = a.vlan or "—"
        days   = f"{a.days_stable:.1f}" if a.days_stable is not None else "—"
        reason = a.classification_reason or ""
        print(f"  {a.mac:<18} {ip:<16} {vlan:<6} {vendor:<32} {days:>5}  {reason}")
    print()


def cmd_stale(db, config):
    assets = db.stale_managed(config.stale_days)
    if not assets:
        print(f"\nNo managed assets stale beyond {config.stale_days} days.\n")
        return
    print(f"\nSTALE MANAGED (not seen in {config.stale_days}+ days) — {len(assets)}\n")
    print(f"{'MAC':<20} {'IP':<16} {'Name':<25} Last Seen")
    print("-" * 75)
    for a in assets:
        print(f"  {a.mac:<18} {a.ip or '—':<16} {a.netbox_name or '—':<25} {a.last_seen}")
    print()


def cmd_promote(args, config, db):
    rules = load_rules(config.rules_file)
    asset = _resolve_target(db, args.target)
    if not asset:
        print(f"Asset not found: {args.target}")
        sys.exit(1)

    site, role = vlan_defaults(asset.vlan, rules, config.default_site, config.default_role)
    effective_site = args.site or site
    effective_role = args.role or role
    effective_name = args.name or asset.ip or asset.mac
    vendor_clean   = _clean_vendor(getattr(args, 'vendor', None) or asset.vendor or _oui_vendor(asset.mac))

    print(f"\nPromoting {asset.mac} ({asset.ip or 'no IP'}) → NetBox")
    print(f"  name={effective_name!r}  role={effective_role!r}  site={effective_site!r}  vendor={vendor_clean!r}")

    model = _default_model(vendor_clean)

    # Build entities — order matters for Diode reconciliation:
    # 1. Interface (must exist before IP can be assigned to it)
    # 2. IPAddress assigned to the interface
    # 3. Device with primary_ip4 pointing to that IP
    entities = []

    if asset.ip:
        # 'primary' is a placeholder interface name until SNMP enrichment
        # provides the real NIC name.
        device_ref = Device(
            name=effective_name,
            role=DeviceRole(name=effective_role),
            site=Site(name=effective_site),
            device_type=DeviceType(model=model, manufacturer=Manufacturer(name=vendor_clean)),
        )
        entities.append(Entity(interface=Interface(
            name="primary",
            type="virtual",
            device=device_ref,
        )))
        ip = IPAddress(
            address=f"{asset.ip}/32",
            assigned_object_interface=Interface(
                name="primary",
                device=Device(name=effective_name),
            ),
        )
        entities.append(Entity(ip_address=ip))
        entities.append(Entity(device=Device(
            name=effective_name,
            role=DeviceRole(name=effective_role),
            site=Site(name=effective_site),
            device_type=DeviceType(model=model, manufacturer=Manufacturer(name=vendor_clean)),
            primary_ip4=IPAddress(address=f"{asset.ip}/32"),
        )))
    else:
        entities.append(Entity(device=Device(
            name=effective_name,
            role=DeviceRole(name=effective_role),
            site=Site(name=effective_site),
            device_type=DeviceType(model=model, manufacturer=Manufacturer(name=vendor_clean)),
        )))

    with DiodeClient(
        target=config.diode_target,
        app_name="netdisco-netbox-sync",
        app_version="0.1.0",
        client_id=config.diode_client_id,
        client_secret=config.diode_client_secret,
    ) as diode:
        response = diode.ingest(entities=entities)
        if response.errors:
            print(f"  Diode errors: {response.errors}")
            sys.exit(1)

    db.set_classification(
        asset.mac, "managed",
        reason="Manually promoted by operator",
        netbox_name=effective_name,
        netbox_site=effective_site,
        netbox_role=effective_role,
        promoted_at=_now(),
    )
    print(f"  Done. {effective_name!r} is now managed in NetBox.\n")


def cmd_ignore(args, db):
    asset = _resolve_target(db, args.target)
    if not asset:
        print(f"Asset not found: {args.target}")
        sys.exit(1)
    db.set_classification(asset.mac, "ignore", reason=args.reason,
                          ignore_reason=args.reason)
    print(f"Ignored: {asset.mac} ({asset.ip or 'no IP'}) — {args.reason}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_target(db, target: str):
    return db.get_by_mac(target) if ":" in target else db.get_by_ip(target)


def _days_between(t1: str | None, t2: str | None) -> float:
    if not t1 or not t2:
        return 0.0
    try:
        d1 = datetime.strptime(t1, "%Y-%m-%d %H:%M:%S.%f")
        d2 = datetime.strptime(t2, "%Y-%m-%d %H:%M:%S.%f")
        return abs((d2 - d1).total_seconds()) / 86400
    except Exception:
        return 0.0


def _default_model(vendor: str) -> str:
    """
    Returns a vendor-specific default model name when no model data is available.
    This keeps each DeviceType slug unique in NetBox so multiple vendors don't
    collapse onto the same 'Unknown' record.
    Refine the actual model in NetBox once you know the hardware.
    """
    v = vendor.lower()
    if "proxmox" in v:   return "Proxmox VM"
    if "mellanox" in v:  return "Mellanox NIC"
    if "intel" in v:     return "Intel Device"
    if "super micro" in v or "supermicro" in v: return "Supermicro Server"
    if "apple" in v:     return "Apple Device"
    if "dell" in v:      return "Dell Device"
    if "hp" in v:        return "HP Device"
    if "fortinet" in v:  return "Fortinet Device"
    if "vmware" in v:    return "VMware VM"
    if "cisco" in v:     return "Cisco Device"
    if vendor == "Unknown": return "Unknown Device"
    return f"{vendor} Device"


def _clean_vendor(vendor: str | None) -> str:
    if not vendor:
        return "Unknown"
    for suffix in [", Inc.", ", Inc", " Inc.", " Inc", " GmbH", " Ltd.", " Ltd",
                   " Corp.", " Corp", " Co.", " LLC", " Technologies", " Technology",
                   " Solutions", " Communications", " Computer"]:
        vendor = vendor.replace(suffix, "")
    return vendor.strip() or "Unknown"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
