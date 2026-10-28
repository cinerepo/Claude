"""
discover.py — Reconciliation engine CLI

Pull end-host data from Netdisco, stage it locally, classify it by VLAN
intent and stability, then push assets to NetBox via Diode.

Assets on 'infrastructure' VLANs (rules.yaml) are pushed to NetBox
automatically once they've been stable for MIN_DAYS_STABLE days. Assets on
'lab'/'corporate' VLANs only become 'candidate' and require an explicit
'promote' command — those device classes are too unpredictable to trust
with auto-generated names/roles.
"""
import re
import sys
import argparse
from collections import defaultdict
from datetime import datetime, timezone

from config import load_config
from netdisco_client import NetdiscoClient
from staging import StagingDB, ObservedAsset, days_until_prune
from classifier import load_rules, load_consumer_vendors, classify, vlan_defaults
from models import NetdiscoNode
from lifecycle import NetBoxClient
from netboxlabs.diode.sdk import DiodeClient
from netboxlabs.diode.sdk.ingester import (
    CustomFieldValue, Device, DeviceRole, DeviceType, Entity, IPAddress,
    Interface, Location, Manufacturer, Site, Tenant
)
from google.protobuf.timestamp_pb2 import Timestamp

# Matches aggregate/uplink interface names (Port-channel9, Po9, Trunk1, Bundle-Ether9,
# Eth-Trunk9) - used to prefer a real access-layer sighting over a transit uplink when
# the same MAC is seen on multiple devices in one run (see _pick_best_sighting below).
_UPLINK_PORT_RE = re.compile(r"^(port-channel|po|trunk|bundle-ether|eth-trunk)\d", re.IGNORECASE)


def _is_uplink_port(port: str | None) -> bool:
    return bool(port) and bool(_UPLINK_PORT_RE.match(port))


def _pick_best_sighting(
    nodes: list[NetdiscoNode], port_mac_counts: dict[tuple[str, str], int]
) -> NetdiscoNode:
    """On a large L2 network, the same end host legitimately shows up in multiple
    devices' own MAC tables at once - the real edge switch's access port, AND every
    core/agg switch it transits through via an uplink (that's how L2 topology mapping
    works at all). Naively using whichever device happens to be processed last in a
    given run flaps the recorded switch/port back and forth between the real access
    port and a transit uplink with zero correctness signal behind it - confirmed live,
    exactly the "Ethernet1/24 <-> Port-channel9" flapping this exists to fix.

    Two-tier heuristic: (1) prefer sightings whose port name doesn't look like an
    aggregate/uplink interface - a real host is never plugged into a Port-channel
    itself. (2) Among whatever's left, prefer the port with the fewest total MACs
    learned on it this run - a genuine access port serves one host (or a handful),
    while an uplink/aggregate port relays an entire downstream segment's worth of
    traffic and will always have a much higher MAC count.
    """
    if len(nodes) == 1:
        return nodes[0]
    non_uplink = [n for n in nodes if not _is_uplink_port(n.port)]
    candidates = non_uplink or nodes
    return min(candidates, key=lambda n: port_mac_counts[(n.switch, n.port)])

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
            "  unclassified      Seen but not yet stable enough to act on\n"
            "  ignore            Permanently excluded (consumer device / ignored VLAN)\n"
            "  candidate         Stable enough for review — requires manual promote\n"
            "  managed           Actually pushed to NetBox (auto for infra VLANs, or via promote)\n"
            "  promotion_failed  Infra VLAN auto-promote attempt failed — retried on next 'run'\n"
            "  stale             Was managed, not seen in STALE_DAYS days\n\n"
            "Workflow:\n"
            "  1. python discover.py run                 (infra VLANs auto-promote to NetBox)\n"
            "  2. python discover.py list-candidates      (lab/corporate VLANs need review)\n"
            "  3. python discover.py promote <mac|ip> --name myserver --role Server\n"
            "  4. python discover.py list-managed\n\n"
            "Thresholds are set in .env:\n"
            "  MIN_DAYS_STABLE  Days before unclassified → candidate/managed (default 7)\n"
            "  STALE_DAYS       Days before managed → stale warning (default 30)\n"
            "  PRUNE_DAYS       Days an unclassified/candidate asset can go unseen before\n"
            "                   'run' deletes it (default 2). Never touches managed/ignore/\n"
            "                   promotion_failed — only still-undecided noise. See\n"
            "                   'list-expiring' for a live countdown before that happens.\n"
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
                    "SELECT mac, ip, vlan, vendor, hostname, days_stable, classification, reason "
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

    sub.add_parser(
        "list-expiring",
        help="Show unclassified/candidate assets counting down to auto-deletion",
        description="Unclassified/candidate assets sorted soonest-to-expire first, "
                    "with a live countdown to when 'run' will delete them if they "
                    "aren't re-observed (PRUNE_DAYS, default 2 days). Use this to catch "
                    "transient noise (temporary test cabling, bridged ports, etc.) "
                    "before it either self-cleans or, if it's real, before it's gone — "
                    "promote or ignore it explicitly to take it off this list for good.",
    )

    p_promote = sub.add_parser(
        "promote",
        help="Promote a candidate asset to NetBox",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Pushes the asset to NetBox via Diode and marks it managed.\n\n"
            "Every flag below already has a value pulled from the staging DB and\n"
            "rules.yaml — in most cases the target is the ONLY thing you need to pass.\n"
            "Only add a flag when you want to override what's already on file for\n"
            "that asset (check with 'list-all' or 'list-candidates' first if unsure)."
        ),
        epilog=(
            "Where each default actually comes from:\n"
            "  --name    asset.hostname (Netdisco reverse-DNS) → asset.ip → asset.mac\n"
            "  --role    rules.yaml vlan_policy[<asset's VLAN>].default_role\n"
            "  --site    rules.yaml vlan_policy[<asset's VLAN>].default_site\n"
            "  --vendor  asset.vendor, already resolved by OUI lookup during 'run'\n\n"
            "Examples:\n"
            "  discover promote 10.1.20.53\n"
            "      No flags needed — uses everything already staged for this asset.\n\n"
            "  discover promote 10.1.20.53 --name labnet-nfs-01\n"
            "      Same as above, just with a real hostname instead of the bare IP.\n\n"
            "  discover promote aa:bb:cc:dd:ee:ff --role Storage --site NRG-Park\n"
            "      Target by MAC instead of IP; override role/site, keep the rest.\n\n"
            "Note: -h is always reserved for --help by argparse, on this command and\n"
            "every other one — it can't be repurposed as a custom flag.\n"
        ),
    )
    p_promote.add_argument("target", help="MAC address (aa:bb:cc:dd:ee:ff) or IP address — "
                                           "look it up with 'list-all' or 'list-candidates' first")
    p_promote.add_argument("--name",   help="Override device name (default: staged hostname, then IP, then MAC)")
    p_promote.add_argument("--role",   help="Override device role (default: rules.yaml VLAN policy)")
    p_promote.add_argument("--site",   help="Override site (default: rules.yaml VLAN policy)")
    p_promote.add_argument("--vendor", help="Override manufacturer (default: already-resolved OUI vendor)")

    p_ignore = sub.add_parser(
        "ignore",
        help="Permanently ignore an asset",
        description="Marks the asset as ignored. It will never be auto-promoted. "
                    "The entry stays in the staging DB for audit purposes.",
    )
    p_ignore.add_argument("target", help="MAC address or IP address")
    p_ignore.add_argument("--reason", default="Manually ignored", help="Reason for ignoring")

    p_unpromote = sub.add_parser(
        "unpromote",
        help="Reset a managed asset back to candidate",
        description="Clears the netbox_name/promoted_at/site/role fields and resets "
                    "classification to 'candidate'. Use this when an asset was removed "
                    "from NetBox out-of-band and needs to be re-promoted from scratch — "
                    "'promote' alone already bypasses the human-lock check and can be "
                    "run directly, but 'unpromote' is useful when you want the asset to "
                    "show up under list-candidates instead of being re-pushed immediately.",
    )
    p_unpromote.add_argument("target", help="MAC address or IP address")
    p_unpromote.add_argument("--reason", default="Manually unpromoted", help="Reason for unpromoting")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    config = load_config()
    db = StagingDB(config.staging_db)

    dispatch = {
        "run":              lambda: cmd_run(config, db),
        "status":           lambda: cmd_status(db),
        "list-all":         lambda: cmd_list_all(db, config),
        "list-candidates":  lambda: cmd_list(db, "candidate", config),
        "list-managed":     lambda: cmd_list(db, "managed"),
        "list-stale":       lambda: cmd_stale(db, config),
        "list-unclassified":lambda: cmd_list(db, "unclassified", config),
        "list-ignored":     lambda: cmd_list(db, "ignore"),
        "list-expiring":    lambda: cmd_list_expiring(db, config),
        "promote":          lambda: cmd_promote(args, config, db),
        "ignore":           lambda: cmd_ignore(args, db),
        "unpromote":        lambda: cmd_unpromote(args, db),
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

    # Build MAC→(IP, DNS) lookup from configured subnets before processing nodes
    mac_to_ip_dns: dict[str, tuple[str, str | None]] = {}
    if rules.ip_inventory_subnets:
        print(f"[netdisco] pulling IP inventory for {len(rules.ip_inventory_subnets)} subnet(s)...")
        for subnet in rules.ip_inventory_subnets:
            print(f"  {subnet}...")
            entries = nd.get_ip_inventory(subnet)
            mac_to_ip_dns.update(entries)
        print(f"  {len(mac_to_ip_dns)} MAC→IP mappings found")

    print("[netdisco] fetching infrastructure devices for node discovery...")
    devices = nd.get_all_devices()
    known_device_ips = {device.ip for device in devices}

    counts = {"new": 0, "updated": 0, "classified": 0}
    to_auto_promote: list[ObservedAsset] = []
    # Real gap found live: once an asset reached "managed" with a netbox_name, this run
    # only ever updated the LOCAL staging DB's own last_seen for it - never touched Diode/
    # NetBox again. A promoted device's NetBox record was effectively frozen forever, with
    # no way to tell "still there, just quiet" from "gone six months ago" (see lifecycle.py
    # for the staleness state machine this heartbeat data actually feeds). Collected here,
    # pushed in the same DiodeClient session as to_auto_promote below.
    to_heartbeat: list[ObservedAsset] = []

    # Collect every sighting across all devices before deciding which switch/port is
    # each MAC's real access-layer location - see _pick_best_sighting's own docstring
    # for why this can't be decided per-device as each one is pulled.
    sightings: dict[str, list[NetdiscoNode]] = defaultdict(list)
    port_mac_counts: dict[tuple[str, str], int] = defaultdict(int)
    for device in devices:
        print(f"  pulling nodes from {device.display_name} ({device.ip})...")
        nodes = nd.get_nodes(device.ip)
        print(f"    {len(nodes)} nodes")
        for node in nodes:
            sightings[node.mac].append(node)
            port_mac_counts[(node.switch, node.port)] += 1

    for mac, mac_nodes in sightings.items():
        node = _pick_best_sighting(mac_nodes, port_mac_counts)

        days_stable = _days_between(node.time_first, node.time_last)

        # OUI vendor lookup — node table rarely carries vendor
        vendor = node.vendor or _oui_vendor(node.mac)

        # IP/DNS enrichment from ipinventory report - node.ip/node.dns are always empty
        # from the /nodes endpoint itself (Netdisco's node table has no ip/dns columns at
        # all, see get_ip_inventory()'s own docstring), so this ipinventory lookup is the
        # only real source for both.
        ip_dns = mac_to_ip_dns.get(node.mac)
        node_ip = node.ip or (ip_dns[0] if ip_dns else None)
        node_dns = node.dns or (ip_dns[1] if ip_dns else None)

        existing = db.get_by_mac(node.mac)
        is_new = existing is None

        asset = ObservedAsset(
            mac=node.mac,
            ip=node_ip,
            vlan=node.vlan,
            switch=node.switch,
            port=node.port,
            vendor=vendor,
            hostname=node_dns,
            first_seen=node.time_first,
            last_seen=node.time_last,
            days_stable=days_stable,
            last_evaluated=_now(),
        )

        # Only skip reclassification for states confirmed outside the classifier:
        #   managed + netbox_name  → actually pushed to NetBox (promote command or auto-promote)
        #   ignore + ignore_reason → set by 'ignore' command
        # A "managed" row with no netbox_name never actually reached NetBox
        # (e.g. a promotion_failed retry, or a legacy row from before
        # auto-promote existed) — re-evaluate and retry it.
        # Auto-ignores (consumer vendor rule) have no ignore_reason and
        # should be re-evaluated when the vendor list changes.
        is_human_locked = existing and (
            (existing.classification == "managed" and existing.netbox_name) or
            (existing.classification == "ignore" and existing.ignore_reason)
        )
        if is_human_locked:
            db.upsert(asset)
            # Only "managed" gets a heartbeat - "ignore" was never pushed to NetBox in
            # the first place, nothing to refresh. Re-fetch after upsert rather than
            # reusing `existing` (the pre-upsert snapshot) or the freshly-built `asset`
            # (has no netbox_* fields at all) - upsert() just refreshed switch/port/ip/
            # last_seen for this row, and move detection below needs that FRESH
            # switch/port sitting alongside the tracked_switch/port upsert()
            # deliberately never touches, in one consistent row.
            if existing.classification == "managed" and existing.netbox_name:
                to_heartbeat.append(db.get_by_mac(node.mac))
            continue

        if node_ip and node_ip in known_device_ips:
            # This IP belongs to a device Netdisco already polls via SNMP —
            # it's sync.py's job to push it with full inventory data.
            # Promoting it here too would create a duplicate NetBox device
            # (host workaround is for devices sync.py can't reach via SNMP).
            classification, reason = "ignore", (
                f"{node_ip} is an SNMP-polled device in Netdisco's inventory — "
                f"managed via sync.py, not the host workaround"
            )
        else:
            classification, reason = classify(
                asset, rules, consumer_vendors, config.min_days_stable
            )
        asset.classification = classification
        asset.classification_reason = reason

        db.upsert(asset)
        counts["new" if is_new else "updated"] += 1
        if classification != "unclassified":
            counts["classified"] += 1
        if classification == "managed":
            to_auto_promote.append(asset)

    nd.close()

    print(f"\n[staging] new={counts['new']}  updated={counts['updated']}  "
          f"classified={counts['classified']}")

    if to_auto_promote or to_heartbeat:
        with DiodeClient(
            target=config.diode_target,
            app_name="netdisco-netbox-sync",
            app_version="0.1.0",
            client_id=config.diode_client_id,
            client_secret=config.diode_client_secret,
        ) as diode:
            if to_auto_promote:
                print(f"\n[auto-promote] {len(to_auto_promote)} infrastructure asset(s) "
                      f"newly stable — pushing to NetBox...")
                promoted, failed = 0, 0
                for asset in to_auto_promote:
                    ok = _promote_asset(
                        diode, db, config, rules, asset,
                        reason=f"{asset.classification_reason} — auto-promoted",
                    )
                    if ok:
                        promoted += 1
                    else:
                        failed += 1
                print(f"[auto-promote] promoted={promoted}  failed={failed}")

            if to_heartbeat:
                # Refreshes last_discovered on already-managed devices - the fix for the
                # "promoted device's NetBox record is frozen forever" gap. Failures here are
                # deliberately silent/non-fatal (no classification change, no retry
                # bookkeeping) - a transient heartbeat miss just means lifecycle.py sees a
                # slightly older last_discovered next time, not a real problem worth
                # disturbing an already-successfully-managed device's state over.
                print(f"\n[heartbeat] refreshing last_discovered for "
                      f"{len(to_heartbeat)} already-managed asset(s)...")
                ok_count, err_count, moved_count = 0, 0, 0
                # Opportunistic netbox_device_id backfill - for any asset promoted before
                # this existed (or where the lookup right after promote didn't find it yet,
                # Diode's write being async), try again on every heartbeat until it
                # succeeds. Non-fatal and entirely optional: NETBOX_TOKEN/NETBOX_URL not
                # being set just means this never fills in, same as lifecycle.py's own
                # "skip cleanly if not configured" behavior. Once set, the webui's edit
                # route can PATCH the real device directly instead of re-pushing through
                # Diode's create-or-match (see webapp.py's discover_edit_managed route).
                nb_client = None
                if config.netbox_url and config.netbox_token:
                    nb_client = NetBoxClient(config.netbox_url, config.netbox_token)
                for existing in to_heartbeat:
                    try:
                        vendor_clean = _clean_vendor(existing.vendor or _oui_vendor(existing.mac))
                        entities = _build_entities(
                            existing.netbox_name, existing.netbox_role, existing.netbox_site,
                            vendor_clean, _default_model(vendor_clean), existing.ip,
                            effective_tenant=existing.netbox_tenant,
                            effective_location=existing.netbox_location,
                            custom_fields={
                                "discovery_source": CustomFieldValue(text="netdisco"),
                                "last_discovered": CustomFieldValue(datetime=_now_ts()),
                            },
                            dns_name=existing.hostname or "",
                        )
                        response = diode.ingest(entities=entities)
                        if response.errors:
                            print(f"    WARN {existing.netbox_name}: {response.errors}")
                            err_count += 1
                            continue
                        ok_count += 1

                        if nb_client and not existing.netbox_device_id:
                            try:
                                found = nb_client.find_device(
                                    existing.netbox_name, site=existing.netbox_site,
                                    tenant=existing.netbox_tenant,
                                )
                                if found:
                                    db.update_netbox_fields(existing.mac, netbox_device_id=found["id"])
                            except Exception as e:
                                # Best-effort - a lookup failure here shouldn't count as a
                                # heartbeat error, the heartbeat push itself already succeeded.
                                print(f"    (netbox_device_id lookup failed for {existing.netbox_name}: {e})")

                        # Switch/port move tracking is purely local bookkeeping (staging DB
                        # only, see staging.py's own comment) - Diode doesn't support Cable
                        # ingestion yet (confirmed live), so this was deliberately scoped
                        # back from "push a real NetBox Cable" to "keep a record of when a
                        # device's port changed" instead of hand-rolling that reconciliation
                        # directly against NetBox's REST API.
                        if existing.switch and existing.port and (
                            existing.switch != existing.tracked_switch
                            or existing.port != existing.tracked_port
                        ):
                            if existing.tracked_switch:
                                db.record_port_change(
                                    existing.mac, existing.netbox_name,
                                    existing.tracked_switch, existing.tracked_port,
                                    existing.switch, existing.port,
                                )
                                print(f"    MOVED {existing.netbox_name}: "
                                      f"{existing.tracked_switch}/{existing.tracked_port} "
                                      f"-> {existing.switch}/{existing.port}")
                                moved_count += 1
                            else:
                                db.set_cabled_port(existing.mac, existing.switch, existing.port)
                    except Exception as e:
                        print(f"    WARN {existing.netbox_name}: {e}")
                        err_count += 1
                print(f"[heartbeat] refreshed={ok_count}  errors={err_count}  moved={moved_count}")
                if nb_client:
                    nb_client.close()

    pruned = db.prune_expired(config.prune_days)
    if pruned:
        print(f"\n[prune] {len(pruned)} unclassified/candidate asset(s) not re-observed "
              f"in {config.prune_days}+ days — removed from staging:")
        for a in pruned:
            print(f"    {a.mac}  ip={a.ip or '—'}  vlan={a.vlan or '—'}  "
                  f"switch={a.switch or '—'}  port={a.port or '—'}  "
                  f"vendor={a.vendor or '—'}  last_seen={a.last_seen}")

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


def cmd_list_all(db, config):
    """Show every asset in the staging DB regardless of classification."""
    import sqlite3
    conn = sqlite3.connect(db._path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT mac, ip, vlan, vendor, hostname, last_seen,
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
    hdr = (f"{'MAC':<20} {'IP':<16} {'VLAN':<6} {'Hostname':<24} {'Vendor':<32} "
           f"{'Days':>5}  {'State':<14} {'Prune In':>12}  Reason")
    print(hdr)
    print("-" * 154)

    current_state = None
    for r in rows:
        if r["classification"] != current_state:
            current_state = r["classification"]
            print(f"\n  -- {current_state.upper()} --")
        vendor   = (r["vendor"] or "—")[:31]
        ip       = r["ip"] or "—"
        vlan     = r["vlan"] or "—"
        hostname = (r["hostname"] or "—")[:23]
        days     = f"{r['days']:.1f}" if r["days"] is not None else "—"
        reason   = r["classification_reason"] or ""
        prune_str = "—"
        if r["classification"] in ("unclassified", "candidate"):
            stub = ObservedAsset(mac=r["mac"], last_seen=r["last_seen"], classification=r["classification"])
            prune_str = _format_prune_countdown(days_until_prune(stub, config.prune_days))
        print(f"  {r['mac']:<18} {ip:<16} {vlan:<6} {hostname:<24} {vendor:<32} "
              f"{days:>5}  {r['classification']:<14} {prune_str:>12}  {reason}")
    print()


def cmd_list(db, classification, config=None):
    assets = db.list_by_classification(classification)
    if not assets:
        print(f"\nNo {classification} assets.\n")
        return

    prunable = config is not None and classification in ("unclassified", "candidate")
    label = classification.upper()
    print(f"\n{label} ({len(assets)})\n")
    if prunable:
        print(f"{'MAC':<20} {'IP':<16} {'VLAN':<6} {'Vendor':<32} {'Days':>5}  {'Prune In':>12}  Reason")
        print("-" * 123)
    else:
        print(f"{'MAC':<20} {'IP':<16} {'VLAN':<6} {'Vendor':<32} {'Days':>5}  Reason")
        print("-" * 108)
    for a in assets:
        vendor = (a.vendor or "—")[:31]
        ip     = a.ip or "—"
        vlan   = a.vlan or "—"
        days   = f"{a.days_stable:.1f}" if a.days_stable is not None else "—"
        reason = a.classification_reason or ""
        if prunable:
            prune_str = _format_prune_countdown(days_until_prune(a, config.prune_days))
            print(f"  {a.mac:<18} {ip:<16} {vlan:<6} {vendor:<32} {days:>5}  {prune_str:>12}  {reason}")
        else:
            print(f"  {a.mac:<18} {ip:<16} {vlan:<6} {vendor:<32} {days:>5}  {reason}")
    print()


def cmd_list_expiring(db, config):
    """Unclassified/candidate assets sorted soonest-to-expire first — the
    'ticking timer' view for whatever's about to be auto-pruned."""
    assets = db.list_by_classification("unclassified") + db.list_by_classification("candidate")
    scored = [(days_until_prune(a, config.prune_days), a) for a in assets]
    scored = [(d, a) for d, a in scored if d is not None]
    scored.sort(key=lambda pair: pair[0])

    if not scored:
        print("\nNothing expiring — no unclassified/candidate assets with a last_seen timestamp yet.\n")
        return

    print(f"\nEXPIRING SOON — prune window is {config.prune_days} day(s) since last_seen — {len(scored)} asset(s)\n")
    print(f"{'MAC':<20} {'IP':<16} {'VLAN':<6} {'Switch':<12} {'Port':<20} {'Vendor':<28} {'State':<12} {'Prune In':>12}")
    print("-" * 138)
    for d, a in scored:
        vendor = (a.vendor or "—")[:27]
        switch = (a.switch or "—")[:11]
        port   = (a.port or "—")[:19]
        print(f"  {a.mac:<18} {a.ip or '—':<16} {a.vlan or '—':<6} {switch:<12} {port:<20} "
              f"{vendor:<28} {a.classification:<12} {_format_prune_countdown(d):>12}")
    print()


def _format_prune_countdown(days_remaining: float | None) -> str:
    if days_remaining is None:
        return "—"
    if days_remaining <= 0:
        return "DUE NOW"
    hours = days_remaining * 24
    if hours < 24:
        return f"{hours:.1f}h left"
    return f"{days_remaining:.1f}d left"


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

    print(f"\nPromoting {asset.mac} ({asset.ip or 'no IP'}) → NetBox")
    with DiodeClient(
        target=config.diode_target,
        app_name="netdisco-netbox-sync",
        app_version="0.1.0",
        client_id=config.diode_client_id,
        client_secret=config.diode_client_secret,
    ) as diode:
        ok = _promote_asset(
            diode, db, config, rules, asset,
            name=args.name, role=args.role, site=args.site, vendor=args.vendor,
        )
    print()
    if not ok:
        sys.exit(1)


def _build_entities(effective_name, effective_role, effective_site, vendor_clean, model, ip,
                     effective_tenant=None, effective_location=None, custom_fields=None,
                     dns_name=""):
    """Build Diode entities for a device. Order matters for reconciliation:
    1. Interface (must exist before IP can be assigned to it)
    2. IPAddress assigned to the interface
    3. Device with primary_ip4 pointing to that IP

    effective_tenant/effective_location must match device_ref exactly - tenant is part of
    NetBox's own Device uniqueness constraint (name, site, tenant), so a mismatch between
    device_ref (the interface/IP stub) and the real device entity would itself become a
    second, incorrect natural key (see transformer.py's own comment for the full story).
    custom_fields (discovery_source/last_discovered) only needs to be on the real device
    entity, not the stub - it isn't part of any uniqueness constraint.
    """
    entities = []
    tenant_obj = Tenant(name=effective_tenant) if effective_tenant else None
    location_obj = Location(name=effective_location) if effective_location else None

    # Diode only auto-creates a referenced sub-object (Tenant, Location) when it also
    # appears as its own top-level Entity in the ingest batch - a nested reference inside
    # Device(tenant=...) alone is not enough to make Diode create it (confirmed live
    # against the real lab NetBox: nested-only left tenant/location=None on the device and
    # no Tenant/Location object created, with no error surfaced - see transformer.py's
    # matching comment for the full story). No cross-call dedup here since each call to
    # this function already gets its own single diode.ingest() - an idempotent resend of
    # the same Tenant/Location natural key across separate promote calls is harmless.
    if tenant_obj:
        entities.append(Entity(tenant=tenant_obj))
    if location_obj:
        entities.append(Entity(location=Location(name=effective_location, site=Site(name=effective_site))))

    if ip:
        # 'primary' is a placeholder interface name until SNMP enrichment
        # provides the real NIC name.
        device_ref = Device(
            name=effective_name,
            role=DeviceRole(name=effective_role),
            site=Site(name=effective_site),
            tenant=tenant_obj,
            location=location_obj,
            device_type=DeviceType(model=model, manufacturer=Manufacturer(name=vendor_clean)),
        )
        entities.append(Entity(interface=Interface(
            name="primary",
            type="virtual",
            device=device_ref,
        )))
        ip_addr = IPAddress(
            address=f"{ip}/32",
            dns_name=dns_name or "",
            assigned_object_interface=Interface(
                name="primary",
                type="virtual",
                device=device_ref,
            ),
        )
        entities.append(Entity(ip_address=ip_addr))
        entities.append(Entity(device=Device(
            name=effective_name,
            role=DeviceRole(name=effective_role),
            site=Site(name=effective_site),
            tenant=tenant_obj,
            location=location_obj,
            device_type=DeviceType(model=model, manufacturer=Manufacturer(name=vendor_clean)),
            primary_ip4=IPAddress(address=f"{ip}/32"),
            custom_fields=custom_fields or {},
        )))
    else:
        entities.append(Entity(device=Device(
            name=effective_name,
            role=DeviceRole(name=effective_role),
            site=Site(name=effective_site),
            tenant=tenant_obj,
            location=location_obj,
            device_type=DeviceType(model=model, manufacturer=Manufacturer(name=vendor_clean)),
            custom_fields=custom_fields or {},
        )))

    return entities


def _promote_asset(diode, db, config, rules, asset, *, name=None, role=None, site=None,
                    vendor=None, reason="Manually promoted by operator"):
    """Push a single asset to NetBox over an already-open Diode session.

    On success, marks the asset 'managed' with netbox_name/promoted_at set.
    On failure, marks it 'promotion_failed' — since that state isn't human-locked,
    the next 'run' will re-classify and retry it automatically.
    Returns True on success, False on failure.
    """
    site_default, role_default, tenant_default, location_default = vlan_defaults(
        asset.vlan, rules, config.default_site, config.default_role,
        config.default_tenant, config.default_location,
    )
    effective_site = site or site_default
    effective_role = role or role_default
    effective_tenant = tenant_default
    effective_location = location_default
    effective_name = name or asset.hostname or asset.ip or asset.mac
    vendor_clean   = _clean_vendor(vendor or asset.vendor or _oui_vendor(asset.mac))
    model          = _default_model(vendor_clean)

    print(f"  {asset.mac} ({asset.ip or 'no IP'})  name={effective_name!r}  "
          f"role={effective_role!r}  site={effective_site!r}  vendor={vendor_clean!r}")

    custom_fields = {
        "discovery_source": CustomFieldValue(text="netdisco"),
        "last_discovered": CustomFieldValue(datetime=_now_ts()),
    }
    entities = _build_entities(
        effective_name, effective_role, effective_site, vendor_clean, model, asset.ip,
        effective_tenant=effective_tenant, effective_location=effective_location,
        custom_fields=custom_fields,
        dns_name=asset.hostname or "",
    )
    response = diode.ingest(entities=entities)

    if response.errors:
        print(f"    Diode errors: {response.errors}")
        db.set_classification(asset.mac, "promotion_failed",
                               reason=f"Auto-promote failed: {response.errors}")
        return False

    db.set_classification(
        asset.mac, "managed",
        reason=reason,
        netbox_name=effective_name,
        netbox_site=effective_site,
        netbox_role=effective_role,
        netbox_tenant=effective_tenant,
        netbox_location=effective_location,
        promoted_at=_now(),
    )
    # Purely local bookkeeping - not pushed to NetBox as any kind of object (Diode doesn't
    # support Cable ingestion yet, confirmed live; hand-rolling that reconciliation directly
    # against NetBox's REST API was considered and explicitly not worth it just for this -
    # see this project's own notes). First-time here, so no history row, nothing to compare
    # against yet - real move detection happens on later heartbeats (cmd_run()).
    if asset.switch and asset.port:
        db.set_cabled_port(asset.mac, asset.switch, asset.port)
    print(f"    Done. {effective_name!r} is now managed in NetBox.")
    return True


def cmd_ignore(args, db):
    asset = _resolve_target(db, args.target)
    if not asset:
        print(f"Asset not found: {args.target}")
        sys.exit(1)
    db.set_classification(asset.mac, "ignore", reason=args.reason,
                          ignore_reason=args.reason)
    print(f"Ignored: {asset.mac} ({asset.ip or 'no IP'}) — {args.reason}")


def cmd_unpromote(args, db):
    asset = _resolve_target(db, args.target)
    if not asset:
        print(f"Asset not found: {args.target}")
        sys.exit(1)
    if asset.classification != "managed":
        print(f"{asset.mac} is not managed (current state: {asset.classification}) — nothing to do.")
        return
    db.set_classification(
        asset.mac, "candidate",
        reason=args.reason,
        netbox_name=None, netbox_site=None, netbox_role=None,
        netbox_device_id=None, promoted_at=None,
    )
    print(f"Unpromoted: {asset.mac} ({asset.ip or 'no IP'}) — back to candidate. "
          f"Run 'promote' again to re-push to NetBox.")


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


def _now_ts() -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(datetime.now(timezone.utc))
    return ts


if __name__ == "__main__":
    main()
