import sys
from config import load_config
from classifier import load_rules
from netdisco_client import NetdiscoClient
from transformer import device_to_entities, resolve_device_identity
from lifecycle import NetBoxClient
from netboxlabs.diode.sdk import DiodeClient
from netboxlabs.diode.sdk.ingester import VLAN


def main():
    config = load_config()
    # device_overrides (per-device tenant/location for infrastructure devices) lives here -
    # sync.py didn't need rules.yaml at all before tenant/location support existed.
    rules = load_rules(config.rules_file)

    print(f"[netdisco] connecting to {config.netdisco_url}")
    nd = NetdiscoClient(config)
    nd.login()

    print("[netdisco] fetching device list...")
    devices = nd.get_all_devices()
    print(f"[netdisco] found {len(devices)} real devices (pseudo-devices excluded)\n")

    total_ok = 0
    total_err = 0
    # Shared across all devices, not reset per device - see transformer.py's own comment.
    # vlan_cache keeps every reference to a given VID (any port, any prefix, any device)
    # consistent; seen_vids gates the standalone top-level VLAN entity to once per VID.
    vlan_cache: dict[int, VLAN] = {}
    seen_vids: set[int] = set()
    seen_tenants: set[str] = set()
    seen_locations: set[str] = set()

    # Direct-PATCH self-heal, same fix already shipped for Pipeline 2's edit-managed-device
    # route (see webapp.py/lifecycle.py) applied here pre-flight instead of on-demand:
    # NetBox's Device uniqueness is (name, site, tenant) together, so if a device's site or
    # tenant already in NetBox doesn't match what this run is about to push (a
    # device_overrides change in rules.yaml, a DEFAULT_SITE/DEFAULT_TENANT change, or someone
    # editing it by hand in the NetBox UI), Diode's natural-key match fails and it creates a
    # duplicate instead of updating the existing device - exactly the bug class documented in
    # transformer.py's resolve_device_identity(). Optional: NETBOX_URL/NETBOX_TOKEN not being
    # set just means this self-heal step never runs, same as lifecycle.py's own "skip cleanly
    # if not configured" behavior - the Diode push below still runs either way.
    nb_client = None
    if config.netbox_url and config.netbox_token:
        nb_client = NetBoxClient(config.netbox_url, config.netbox_token)

    print(f"[diode] connecting to {config.diode_target}")
    with DiodeClient(
        target=config.diode_target,
        app_name="netdisco-netbox-sync",
        app_version="0.1.0",
        client_id=config.diode_client_id,
        client_secret=config.diode_client_secret,
    ) as diode:
        for i, device in enumerate(devices, 1):
            label = f"[{i}/{len(devices)}] {device.display_name} ({device.ip})"
            try:
                if nb_client:
                    name, site_name, tenant_name, _loc, _role = resolve_device_identity(device, config, rules)
                    found = nb_client.find_device(name, site=site_name, tenant=tenant_name)
                    if found:
                        found_site = (found.get("site") or {}).get("name")
                        found_tenant = (found.get("tenant") or {}).get("name")
                        if found_site != site_name or found_tenant != tenant_name:
                            print(f"  FIX  {label}: site/tenant drifted "
                                  f"({found_site!r}/{found_tenant!r} -> {site_name!r}/{tenant_name!r}) "
                                  f"- patching in place before push")
                            try:
                                nb_client.update_device_fields(
                                    found["id"], site=site_name, tenant=tenant_name or "",
                                )
                            except Exception as e:
                                print(f"  WARN {label}: site/tenant self-heal failed, "
                                      f"push below may create a duplicate: {e}")

                ports      = nd.get_ports(device.ip)
                device_ips = nd.get_device_ips(device.ip)
                port_vlans = nd.get_port_vlans(device.ip)
                vlans      = nd.get_vlans(device.ip)
                nodes      = nd.get_nodes(device.ip)

                entities = device_to_entities(
                    device, ports, device_ips, port_vlans, vlans, nodes, config, rules,
                    vlan_cache=vlan_cache, seen_vids=seen_vids,
                    seen_tenants=seen_tenants, seen_locations=seen_locations,
                )

                by_type = {}
                for e in entities:
                    kind = e.WhichOneof("entity")
                    by_type[kind] = by_type.get(kind, 0) + 1

                response = diode.ingest(entities=entities)

                if response.errors:
                    print(f"  WARN {label}: {response.errors}")
                    total_err += 1
                else:
                    summary = ", ".join(f"{v} {k}" for k, v in sorted(by_type.items()))
                    print(f"  OK   {label} — {summary}")
                    total_ok += 1

            except Exception as e:
                print(f"  ERR  {label}: {e}", file=sys.stderr)
                total_err += 1

    nd.close()
    if nb_client:
        nb_client.close()
    print(f"\n[done] {total_ok} ok / {total_err} errors out of {len(devices)} devices")
    if total_err:
        sys.exit(1)


if __name__ == "__main__":
    main()
