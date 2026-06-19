import re
from netboxlabs.diode.sdk.ingester import (
    Device,
    DeviceRole,
    DeviceType,
    Entity,
    IPAddress,
    Interface,
    Manufacturer,
    Platform,
    Prefix,
    Site,
    VLAN,
)
from models import NetdiscoDevice, NetdiscoPort, NetdiscoDeviceIP, NetdiscoPortVlan, NetdiscoVlan
from config import Config

# Legacy Cisco internal VLANs — never meaningful in NetBox
_SKIP_VLANS = {1002, 1003, 1004, 1005}


def device_to_entities(
    device: NetdiscoDevice,
    ports: list[NetdiscoPort],
    device_ips: list[NetdiscoDeviceIP],
    port_vlans: list[NetdiscoPortVlan],
    vlans: list[NetdiscoVlan],
    config: Config,
) -> list[Entity]:
    entities: list[Entity] = []
    name = device.display_name
    site_name = device.location or config.default_site

    # --- Device ---
    nb_device = Device(
        name=name,
        device_type=DeviceType(
            model=device.model or "Unknown",
            manufacturer=Manufacturer(name=_normalize_vendor(device.vendor)),
        ),
        role=DeviceRole(name=_device_role(device.vendor, device.model)),
        platform=Platform(name=_platform_name(device)) if device.os else None,
        site=Site(name=site_name),
        serial=device.serial or "",
    )
    entities.append(Entity(device=nb_device))

    # Full device stub reused in Interface and IPAddress entities so Diode
    # can resolve the FK without trying to create an incomplete device record.
    device_stub = Device(
        name=name,
        device_type=DeviceType(
            model=device.model or "Unknown",
            manufacturer=Manufacturer(name=_normalize_vendor(device.vendor)),
        ),
        role=DeviceRole(name=_device_role(device.vendor, device.model)),
        site=Site(name=site_name),
    )

    # --- VLAN name lookup (vid → name) used when referencing VLANs in interfaces ---
    vlan_name: dict[int, str] = {}
    for v in vlans:
        vid = _to_vid(v.vlan)
        if vid:
            vlan_name[vid] = v.description or f"VLAN{vid}"

    def _named_vlan(vid: int) -> VLAN:
        return VLAN(vid=vid, name=vlan_name.get(vid, f"VLAN{vid}"))

    # --- Build tagged VLAN map from port_vlans ---
    # egress_tag=1 means the VLAN is sent tagged (trunk). Skip legacy VLANs.
    tagged_by_port: dict[str, list[int]] = {}
    for pv in port_vlans:
        if pv.egress_tag == 1 and pv.vlan not in _SKIP_VLANS:
            tagged_by_port.setdefault(pv.port, []).append(pv.vlan)

    # --- Interfaces ---
    for port in ports:
        vid = _to_vid(port.pvid) if _valid_vlan(port.pvid) else None
        tagged_vids = tagged_by_port.get(port.port, [])
        tagged_vlans_objs = [_named_vlan(v) for v in tagged_vids if v not in _SKIP_VLANS]

        # Mode: tagged if trunk VLANs present, access if only native, None if neither
        if tagged_vlans_objs:
            mode = "tagged"
        elif vid:
            mode = "access"
        else:
            mode = None

        iface = Interface(
            name=port.port,
            device=device_stub,
            type=_map_interface_type(port.type, port.speed),
            description=_interface_description(port.name, port.descr),
            primary_mac_address=_clean_mac(port.mac),
            mtu=port.mtu or None,
            enabled=_is_up(port.up_admin),
            mode=mode,
            untagged_vlan=_named_vlan(vid) if vid else None,
            tagged_vlans=tagged_vlans_objs if tagged_vlans_objs else None,
        )
        entities.append(Entity(interface=iface))

    # --- IP Addresses (with interface assignment and real prefix length) ---
    seen_ips: set[str] = set()
    for addr in device_ips:
        if addr.alias in seen_ips:
            continue
        seen_ips.add(addr.alias)

        prefix_len = _prefix_len(addr.subnet)
        iface_stub = Interface(name=addr.port, device=device_stub) if addr.port else None

        ip = IPAddress(
            address=f"{addr.alias}/{prefix_len}",
            dns_name=addr.dns or "",
            assigned_object_interface=iface_stub,
        )
        entities.append(Entity(ip_address=ip))

    # Management IP fallback if not already covered by device_ips
    if device.ip not in seen_ips:
        entities.append(Entity(ip_address=IPAddress(address=f"{device.ip}/32")))

    # --- Prefixes (one per unique subnet, linked to its VLAN if we can match) ---
    seen_prefixes: set[str] = set()
    vlan_by_svi: dict[str, int] = {}  # "Vlan20" → 20
    for v in vlans:
        vid = _to_vid(v.vlan)
        if vid:
            vlan_by_svi[f"Vlan{vid}"] = vid

    for addr in device_ips:
        if not addr.subnet or addr.subnet in seen_prefixes:
            continue
        seen_prefixes.add(addr.subnet)

        linked_vid = vlan_by_svi.get(addr.port or "") if addr.port else None
        prefix = Prefix(
            prefix=addr.subnet,
            scope_site=Site(name=site_name),
            vlan=VLAN(vid=linked_vid) if linked_vid else None,
        )
        entities.append(Entity(prefix=prefix))

    # --- VLANs (skip legacy Cisco internal VLANs) ---
    seen_vids: set[int] = set()
    for vlan in vlans:
        vid = _to_vid(vlan.vlan)
        if vid is None or vid in seen_vids or vid in _SKIP_VLANS:
            continue
        seen_vids.add(vid)
        entities.append(Entity(vlan=VLAN(
            vid=vid,
            name=vlan.description or f"VLAN{vid}",
        )))

    return entities


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_vendor(vendor: str | None) -> str:
    mapping = {"cisco": "Cisco", "fortinet": "Fortinet", "arista": "Arista"}
    v = (vendor or "").lower()
    return mapping.get(v, vendor or "Unknown")


def _device_role(vendor: str | None, model: str | None) -> str:
    v = (vendor or "").lower()
    m = (model or "").lower()
    if v == "fortinet":
        return "Firewall"
    if v == "cisco":
        if any(x in m for x in ("9300", "9200", "3850", "3650", "2960", "catalyst")):
            return "Switch"
        if any(x in m for x in ("asr", "isr", "csr", "nxos", "nexus")):
            return "Router"
    return "Network Device"


def _interface_description(name: str | None, descr: str | None) -> str:
    # Netdisco stores ifAlias (user-configured description) in 'name'.
    # When no description is set it falls back to the short form (e.g. "Te1/0/1").
    if name and (" " in name or not _looks_like_short_iface(name)):
        return name
    return ""


def _looks_like_short_iface(s: str) -> bool:
    return bool(re.match(r'^[A-Za-z]{1,4}\d+(/\d+)*$', s))


def _map_interface_type(snmp_type: str | None, speed: str | None) -> str:
    t = (snmp_type or "").lower()
    if t in ("softwareloopback", "propvirtual", "tunnel", "other"):
        return "virtual"
    if t == "ieee8023adlag":
        return "lag"
    if t == "ethernetcsmacd":
        s = (speed or "").lower()
        if "100 gbps" in s:   return "100gbase-x-qsfp28"
        if "40 gbps" in s:    return "40gbase-x-qsfpp"
        if "25 gbps" in s:    return "25gbase-x-sfp28"
        if "10 gbps" in s:    return "10gbase-x-sfpp"
        if "2.5 gbps" in s:   return "2.5gbase-t"
        if "1 gbps" in s or "1.0 gbps" in s: return "1000base-t"
        if "100 mbps" in s:   return "100base-tx"
    return "other"


def _platform_name(device: NetdiscoDevice) -> str:
    if device.os and device.os_ver:
        return f"{device.os} {device.os_ver}"
    return device.os or "Unknown"


def _is_up(up_admin: str | None) -> bool:
    if up_admin is None:
        return True
    return up_admin.lower() == "up"


def _valid_vlan(pvid: int | str | None) -> bool:
    vid = _to_vid(pvid)
    return vid is not None and 1 <= vid <= 4094


def _to_vid(value: int | str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _prefix_len(subnet: str | None) -> str:
    if subnet and "/" in subnet:
        return subnet.split("/")[1]
    return "32"


def _clean_mac(mac: str | None) -> str | None:
    return mac if mac and mac != "00:00:00:00:00:00" else None
