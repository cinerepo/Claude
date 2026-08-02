import sys
from config import load_config
from netdisco_client import NetdiscoClient
from transformer import device_to_entities
from netboxlabs.diode.sdk import DiodeClient


def main():
    config = load_config()

    print(f"[netdisco] connecting to {config.netdisco_url}")
    nd = NetdiscoClient(config)
    nd.login()

    print("[netdisco] fetching device list...")
    devices = nd.get_all_devices()
    print(f"[netdisco] found {len(devices)} real devices (pseudo-devices excluded)\n")

    total_ok = 0
    total_err = 0

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
                ports      = nd.get_ports(device.ip)
                device_ips = nd.get_device_ips(device.ip)
                port_vlans = nd.get_port_vlans(device.ip)
                vlans      = nd.get_vlans(device.ip)
                nodes      = nd.get_nodes(device.ip)

                entities = device_to_entities(
                    device, ports, device_ips, port_vlans, vlans, nodes, config
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
    print(f"\n[done] {total_ok} ok / {total_err} errors out of {len(devices)} devices")
    if total_err:
        sys.exit(1)


if __name__ == "__main__":
    main()
