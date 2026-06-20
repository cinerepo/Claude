from pydantic import BaseModel
from typing import Optional


class NetdiscoDevice(BaseModel):
    ip: str
    name: Optional[str] = None
    dns: Optional[str] = None
    location: Optional[str] = None
    contact: Optional[str] = None
    vendor: Optional[str] = None
    os: Optional[str] = None
    os_ver: Optional[str] = None
    model: Optional[str] = None
    serial: Optional[str] = None
    chassis_id: Optional[str] = None
    description: Optional[str] = None
    snmp_ver: Optional[int] = None
    uptime: Optional[int] = None
    mac: Optional[str] = None
    vtp_domain: Optional[str] = None
    is_pseudo: Optional[bool] = False
    last_discover: Optional[str] = None
    last_arpnip: Optional[str] = None
    last_macsuck: Optional[str] = None

    @property
    def display_name(self) -> str:
        return self.name or self.dns or self.ip


class NetdiscoPort(BaseModel):
    ip: str
    port: str
    name: Optional[str] = None
    descr: Optional[str] = None
    type: Optional[str] = None
    remote_ip: Optional[str] = None
    remote_port: Optional[str] = None
    remote_type: Optional[str] = None
    duplex: Optional[str] = None
    speed: Optional[str] = None
    mac: Optional[str] = None
    mtu: Optional[int] = None
    pvid: Optional[int | str] = None
    up: Optional[str] = None
    up_admin: Optional[str] = None
    is_uplink: Optional[bool] = None


class NetdiscoDeviceIP(BaseModel):
    """A routed IP address assigned to a device interface (device_ips endpoint)."""
    ip: str        # device management IP (canonical key)
    alias: str     # the actual IP address on this interface
    subnet: Optional[str] = None   # CIDR subnet e.g. "10.1.20.0/24"
    port: Optional[str] = None     # interface name e.g. "Vlan20"
    dns: Optional[str] = None


class NetdiscoPortVlan(BaseModel):
    """Per-port VLAN membership record (port_vlans endpoint)."""
    ip: str
    port: str
    vlan: int
    native: int       # 1 = native/untagged VLAN for this port
    egress_tag: int   # 0 = untagged egress, 1 = tagged egress (trunk)
    vlantype: Optional[str] = None


class NetdiscoNode(BaseModel):
    """A MAC-table entry — an end host seen on a switch port (nodes endpoint)."""
    mac: str
    switch: str
    port: str
    vlan: Optional[str] = None
    ip: Optional[str] = None          # populated if ARP was correlated by Netdisco
    dns: Optional[str] = None
    vendor: Optional[str] = None
    active: Optional[int] = None
    time_first: Optional[str] = None
    time_last: Optional[str] = None
    time_recent: Optional[str] = None


class NetdiscoVlan(BaseModel):
    ip: str
    vlan: int | str
    description: Optional[str] = None
