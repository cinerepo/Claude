import ipaddress
import re
import datetime
from google.protobuf.timestamp_pb2 import Timestamp
from netboxlabs.diode.sdk.ingester import (
    CustomFieldValue,
    Device,
    DeviceRole,
    DeviceType,
    Entity,
    IPAddress,
    Interface,
    Location,
    MACAddress,
    Manufacturer,
    Platform,
    Prefix,
    Site,
    Tenant,
    VLAN,
)
from models import NetdiscoDevice, NetdiscoPort, NetdiscoDeviceIP, NetdiscoPortVlan, NetdiscoVlan, NetdiscoNode
from config import Config
from classifier import Rules

# Legacy Cisco internal VLANs — never meaningful in NetBox
_SKIP_VLANS = {1002, 1003, 1004, 1005}


def resolve_device_identity(
    device: NetdiscoDevice, config: Config, rules: Rules
) -> tuple[str, str, str | None, str | None, str]:
    """Compute (name, site_name, tenant_name, location_name, role_name) for a Pipeline 1
    device - the same identity fields device_to_entities() pushes, factored out so
    sync.py can resolve them ahead of the Diode push too (see sync.py's pre-flight
    site/tenant self-heal - it needs to know what identity a device is ABOUT to be
    pushed under before deciding whether the one already in NetBox needs correcting)."""
    name = device.display_name
    override = rules.device_overrides.get(name)
    site_name = (override.site if override else None) or config.default_site
    tenant_name = (override.tenant if override else None) or config.default_tenant
    location_name = (override.location if override else None) or config.default_location
    role_name = (override.role if override else None) or _device_role(device.vendor, device.model)
    return name, site_name, tenant_name, location_name, role_name


def device_to_entities(
    device: NetdiscoDevice,
    ports: list[NetdiscoPort],
    device_ips: list[NetdiscoDeviceIP],
    port_vlans: list[NetdiscoPortVlan],
    vlans: list[NetdiscoVlan],
    nodes: list[NetdiscoNode],
    config: Config,
    rules: Rules,
    vlan_cache: dict[int, VLAN] | None = None,
    seen_vids: set[int] | None = None,
    seen_tenants: set[str] | None = None,
    seen_locations: set[str] | None = None,
) -> list[Entity]:
    # Both shared across the whole sync.py run (passed in by the caller, not reset per
    # device) - real bug found live, worse than first thought: this function actually
    # constructs a VLAN(...) object in FOUR separate places (tagged_vlans on every trunk
    # port, untagged_vlan on every access port, Prefix.vlan, and the standalone VLAN
    # entity), each independently, with no caching - a VTP-fed switch alone can reference
    # the same VID dozens of times across its own ports. Confirmed live: even after this
    # file's first fix (deduping only the standalone entity) and a full NetBox wipe +
    # fresh sync, ~400 VLANs came back duplicated 1-4x each.
    #
    # vlan_cache ensures every reference to a given VID anywhere in this run - any port, any
    # prefix, any device - resolves to the exact same (vid, name) pair via _get_vlan() below,
    # instead of each call site independently building its own (sometimes even inconsistent -
    # Prefix.vlan previously carried no name at all) VLAN object. seen_vids still gates the
    # standalone top-level Entity(vlan=...) so it's only actually emitted once per VID across
    # the whole run, not just object-consistent.
    if vlan_cache is None:
        vlan_cache = {}
    if seen_vids is None:
        seen_vids = set()
    if seen_tenants is None:
        seen_tenants = set()
    if seen_locations is None:
        seen_locations = set()
    entities: list[Entity] = []

    # Explicit per-device override (rules.yaml device_overrides), falling back to
    # config.yaml's flat default_site/default_tenant/default_location. Deliberately NOT
    # derived from which VLANs this device serves - a switch/firewall typically trunks
    # many VLANs, and its site/tenant/location is about physical/organizational
    # ownership, not passing traffic. Real bug this fixes: NetBox's own Device
    # uniqueness is (name, site, tenant) together (confirmed against
    # dcim/models/devices.py) - this function used to never set tenant at all (implicit
    # tenant=None every push) and site was ALWAYS the flat config.default_site with no
    # override at all. Manually changing Site or Tenant directly in the NetBox UI meant
    # the next sync couldn't find that device anymore (its natural key changed) and
    # created a duplicate instead of updating it - true for site exactly the same way
    # it was for tenant, just not hit yet since nothing overrode site until now.
    #
    # site_name is deliberately NOT device.location (netdisco's own SNMP sysLocation
    # string) even as a fallback - real bug found live: garbage/one-off location strings
    # like "Rack 19" or an old event code were being taken at face value and turned into
    # brand new NetBox Sites. device_overrides is the only sanctioned way to give a
    # specific device a non-default site.
    #
    # sync.py resolves this same identity ahead of time (resolve_device_identity, right
    # above) to self-heal an existing device's site/tenant via a direct PATCH before this
    # function's Diode push runs - see sync.py's pre-flight step. Keep the two in sync if
    # this logic ever changes; that's the whole reason it's factored out now.
    name, site_name, tenant_name, location_name, role_name = resolve_device_identity(device, config, rules)
    tenant_obj = Tenant(name=tenant_name) if tenant_name else None
    # site=... required here too, not just name - a Device's nested location reference
    # without it validates as an incomplete dcim.location stub on the reconciler side
    # (fails "Field site is required" even when the referenced Location already exists
    # correctly) - confirmed live against the real netbox_diode_plugin generate_changeset
    # path on 2026-08-20, see the standalone Location entity above which already got this
    # right; this nested one didn't.
    location_obj = Location(name=location_name, site=Site(name=site_name)) if location_name else None

    # oob_net: parsed once, reused both for Device.oob_ip below and the mgmt-interface
    # attachment fallback further down (the IP-address loop). config.oob_subnet is
    # optional per-deployment (e.g. "10.1.30.0/24" here, "10.60.80.0/24" at the rodeo) -
    # None/invalid just means neither of those two things happen, same as before this existed.
    oob_net = None
    if config.oob_subnet:
        try:
            oob_net = ipaddress.ip_network(config.oob_subnet, strict=False)
        except ValueError:
            oob_net = None
    device_ip_is_oob = bool(oob_net) and _in_subnet(device.ip, oob_net)

    # Diode only auto-creates a referenced sub-object (Tenant, Location) when it also
    # appears as its own top-level Entity somewhere in the ingest batch - a nested
    # reference inside Device(tenant=...) alone is not enough. Confirmed live: sending
    # only the nested reference left NetBox with tenant/location=None on the device and
    # no Tenant/Location object created at all, with no error surfaced anywhere - same
    # "silently incomplete, not silently failed" shape as the custom-fields gotcha
    # (see lifecycle.py). seen_tenants/seen_locations just avoid resending an identical
    # standalone entity once per device when many devices share the same tenant/location -
    # not required for correctness, since the natural key (name) is idempotent either way.
    if tenant_name and tenant_name not in seen_tenants:
        seen_tenants.add(tenant_name)
        entities.append(Entity(tenant=tenant_obj))
    if location_name and location_name not in seen_locations:
        seen_locations.add(location_name)
        entities.append(Entity(location=Location(name=location_name, site=Site(name=site_name))))

    # discovery_source/last_discovered custom fields - the "observation" half of lifecycle
    # tracking (see lifecycle.py for the "classification" half: computing staleness from
    # last_discovered and setting discovery_state). Deliberately NOT setting
    # first_discovered here - this function has no way to know if this is a device's first
    # observation or its thousandth; lifecycle.py sets it once, the first time it sees a
    # device with no first_discovered value yet.
    custom_fields = {
        "discovery_source": CustomFieldValue(text="netdisco"),
        "last_discovered": CustomFieldValue(datetime=_now_ts()),
    }

    # --- Device ---
    # primary_ip4 = device.ip (Netdisco's own polling address) - this pipeline never set
    # it at all before, so every infrastructure device's NetBox "Primary IP" field stayed
    # permanently blank even though the underlying IPAddress objects were correctly
    # attached to real interfaces the whole time (confirmed live: interfaces had the
    # right IPs, primary_ip4 was just never set on the Device). device.ip always has a
    # matching IPAddress entity somewhere in this function's output (either a real
    # device_ips row or the fallback below), same pattern discover.py's own promote path
    # already uses successfully for Pipeline 2.
    #
    # oob_ip is NetBox's own dedicated out-of-band-address field on Device - distinct from
    # primary_ip4, which is what most other tooling actually looks at as "the" address.
    # Only set when device.ip is confirmed to be on the configured OOB subnet (see
    # device_ip_is_oob above) - for devices where the polling IP is really just an
    # in-band SVI address (no separate OOB subnet configured, or it's outside the
    # configured range), oob_ip stays unset and primary_ip4 alone is the right call.
    nb_device = Device(
        name=name,
        device_type=DeviceType(
            model=device.model or "Unknown",
            manufacturer=Manufacturer(name=_normalize_vendor(device.vendor)),
        ),
        role=DeviceRole(name=role_name),
        platform=Platform(name=_platform_name(device)) if device.os else None,
        site=Site(name=site_name),
        tenant=tenant_obj,
        location=location_obj,
        primary_ip4=IPAddress(address=f"{device.ip}/32"),
        oob_ip=IPAddress(address=f"{device.ip}/32") if device_ip_is_oob else None,
        serial=device.serial or "",
        custom_fields=custom_fields,
    )
    # Appended at the end of this function, not here - Diode doesn't guarantee resolving
    # forward references within one ingest() batch (same documented gotcha as
    # IPAddress.assigned_object_interface elsewhere in this file). primary_ip4 references
    # an IPAddress this function hasn't built yet at this point - appending nb_device now,
    # before that IPAddress entity exists in the batch, left primary_ip4 silently unset
    # even though the IP itself landed correctly (confirmed live: IP was attached to the
    # right interface, but Device.primary_ip4 stayed None until this was fixed).

    # Full device stub reused in Interface and IPAddress entities so Diode
    # can resolve the FK without trying to create an incomplete device record.
    # tenant must match nb_device exactly - it's part of NetBox's own uniqueness
    # constraint (name, site, tenant), so a mismatched stub would itself become a second,
    # incorrect natural key and reintroduce the exact duplication bug this fixes.
    device_stub = Device(
        name=name,
        device_type=DeviceType(
            model=device.model or "Unknown",
            manufacturer=Manufacturer(name=_normalize_vendor(device.vendor)),
        ),
        role=DeviceRole(name=role_name),
        site=Site(name=site_name),
        tenant=tenant_obj,
        location=location_obj,
    )

    # --- VLAN name lookup (vid → name) used when referencing VLANs in interfaces ---
    vlan_name: dict[int, str] = {}
    for v in vlans:
        vid = _to_vid(v.vlan)
        if vid:
            vlan_name[vid] = v.description or f"VLAN{vid}"

    def _get_vlan(vid: int) -> VLAN:
        # Cache-first-wins: whichever device this run first references a given VID from
        # sets its canonical name for every other reference (this device's other ports,
        # every other device's ports/prefixes, and the standalone entity below) - one
        # consistent (vid, name) pair per VID for the reconciler to match against, instead
        # of each call site building its own, sometimes differently-named, object.
        if vid not in vlan_cache:
            vlan_cache[vid] = VLAN(vid=vid, name=vlan_name.get(vid, f"VLAN{vid}"))
        return vlan_cache[vid]

    # --- Build tagged VLAN map from port_vlans ---
    # egress_tag=1 means the VLAN is sent tagged (trunk). Skip legacy VLANs.
    tagged_by_port: dict[str, list[int]] = {}
    for pv in port_vlans:
        if pv.egress_tag == 1 and pv.vlan not in _SKIP_VLANS:
            tagged_by_port.setdefault(pv.port, []).append(pv.vlan)

    # --- Interfaces ---
    access_ports: set[str] = set()
    for port in ports:
        vid = _to_vid(port.pvid) if _valid_vlan(port.pvid) else None
        tagged_vids = tagged_by_port.get(port.port, [])
        tagged_vlans_objs = [_get_vlan(v) for v in tagged_vids if v not in _SKIP_VLANS]

        # Mode: tagged if trunk VLANs present, access if only native, None if neither
        if tagged_vlans_objs:
            mode = "tagged"
        elif vid:
            mode = "access"
        else:
            mode = None

        if mode == "access" and not port.is_uplink:
            access_ports.add(port.port)

        iface = Interface(
            name=port.port,
            device=device_stub,
            type=_map_interface_type(port.type, port.speed),
            description=_interface_description(port.name, port.descr),
            primary_mac_address=_clean_mac(port.mac),
            mtu=port.mtu or None,
            enabled=_is_up(port.up_admin),
            mode=mode,
            untagged_vlan=_get_vlan(vid) if vid else None,
            tagged_vlans=tagged_vlans_objs if tagged_vlans_objs else None,
        )
        entities.append(Entity(interface=iface))

    # --- Connected nodes (learned MACs) — access ports only, to avoid dumping
    # every downstream MAC ever seen through a trunk/uplink onto one interface ---
    for node in nodes:
        if node.port not in access_ports:
            continue
        mac = _clean_mac(node.mac)
        if not mac:
            continue
        iface_stub = Interface(name=node.port, device=device_stub)
        details = ", ".join(
            f"{label}={value}" for label, value in (
                ("ip", node.ip),
                ("vendor", node.vendor),
                ("last_seen", node.time_last),
            ) if value
        )
        entities.append(Entity(mac_address=MACAddress(
            mac_address=mac,
            assigned_object_interface=iface_stub,
            description=node.dns or node.ip or "",
            comments=f"learned via netdisco: {details}" if details else "learned via netdisco",
        )))

    # --- IP Addresses (with interface assignment and real prefix length) ---
    # Netdisco's device_ips report doesn't always know which interface an address
    # belongs to - specifically the device's own polling/management IP (alias ==
    # device.ip) is reported with port=None, since Netdisco treats "the address I poll
    # this device on" as a device-level fact, not tied to any interface in that report.
    # Confirmed live against a real Nexus mgmt0 port: device_ips returned port=null for
    # that exact IP. Without a fallback, that IP silently never attaches to anything -
    # Diode drops an IPAddress with no assigned_object_interface rather than creating a
    # floating one, so the device's own OOB/mgmt address just never showed up in NetBox
    # at all. Two fallback strategies, tried in this order:
    #
    # 1. Name match against the real ports list (mgmt0, mgmt, Management1, etc.) - only
    #    attempted when config.oob_subnet is set AND the portless address actually falls
    #    within it, so this never fires on some unrelated portless address by accident.
    #    Preferred over ports[].ip below because that field isn't reliably per-port -
    #    confirmed live on a real Nexus where *every* port reported the same ip value
    #    (the device's own polling address, not that port's own), which would make an
    #    ip-only lookup a coin flip on any device shaped that way.
    # 2. ports[].ip lookup (pre-existing, less reliable per the caveat above, but still a
    #    reasonable last resort when oob_subnet isn't configured or nothing named "mgmt"
    #    is found) - each port's own "ip" field, when it IS trustworthy, is the address
    #    Netdisco reached it on.
    mgmt_port_name = _find_mgmt_port(ports)
    # oob_net computed earlier, alongside device_ip_is_oob - reused here.
    port_by_ip: dict[str, str] = {p.ip: p.port for p in ports if p.ip}

    seen_ips: set[str] = set()
    for addr in device_ips:
        if addr.alias in seen_ips:
            continue
        seen_ips.add(addr.alias)

        prefix_len = _prefix_len(addr.subnet)
        port_name = addr.port
        if not port_name and oob_net and mgmt_port_name and _in_subnet(addr.alias, oob_net):
            port_name = mgmt_port_name
        if not port_name:
            port_name = port_by_ip.get(addr.alias)
        iface_stub = Interface(name=port_name, device=device_stub) if port_name else None

        ip = IPAddress(
            address=f"{addr.alias}/{prefix_len}",
            dns_name=addr.dns or "",
            assigned_object_interface=iface_stub,
        )
        entities.append(Entity(ip_address=ip))

    # Management IP fallback if not already covered by device_ips - device.ip normally
    # already comes through the loop above (Netdisco includes its own polling IP in
    # device_ips, just without a port - see the fallback lookup above), so this only
    # fires in the rarer case where device_ips omits it entirely. Still can't resolve an
    # interface here since there's no device_ips row to look up port_by_ip against; a
    # bare device.ip alone doesn't tell us which port it was reached on.
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
            vlan=_get_vlan(linked_vid) if linked_vid else None,
        )
        entities.append(Entity(prefix=prefix))

    # --- VLANs (skip legacy Cisco internal VLANs) - only emitted as a standalone
    # top-level entity once per VID across the whole run (seen_vids), reusing the same
    # cached object every other reference above already used ---
    for vlan in vlans:
        vid = _to_vid(vlan.vlan)
        if vid is None or vid in seen_vids or vid in _SKIP_VLANS:
            continue
        seen_vids.add(vid)
        entities.append(Entity(vlan=_get_vlan(vid)))

    entities.append(Entity(device=nb_device))
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


_MGMT_NAME_RE = re.compile(r"mgmt|management", re.IGNORECASE)


def _find_mgmt_port(ports: list) -> str | None:
    """First port whose name/port field looks like a management interface (mgmt0, mgmt,
    Management1, ManagementEthernet0/0, etc.) - used only as the OOB-subnet-gated fallback
    in the IP-address loop above, never for anything else."""
    for p in ports:
        if _MGMT_NAME_RE.search(p.port or "") or _MGMT_NAME_RE.search(p.name or ""):
            return p.port
    return None


def _in_subnet(ip: str | None, net: "ipaddress.IPv4Network | ipaddress.IPv6Network") -> bool:
    if not ip:
        return False
    try:
        return ipaddress.ip_address(ip) in net
    except ValueError:
        return False


def _clean_mac(mac: str | None) -> str | None:
    return mac if mac and mac != "00:00:00:00:00:00" else None


def _now_ts() -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(datetime.datetime.now(datetime.timezone.utc))
    return ts
