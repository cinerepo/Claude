import httpx
from typing import Optional
from models import NetdiscoDevice, NetdiscoPort, NetdiscoDeviceIP, NetdiscoPortVlan, NetdiscoVlan, NetdiscoNode
from config import Config


class NetdiscoClient:
    def __init__(self, config: Config):
        self._base = config.netdisco_url.rstrip("/")
        self._user = config.netdisco_user
        self._pass = config.netdisco_pass
        self._api_key: Optional[str] = None
        self._http = httpx.Client(timeout=30)

    def _headers(self) -> dict:
        h = {"Accept": "application/json"}
        if self._api_key:
            h["Authorization"] = self._api_key
        return h

    def login(self):
        if not self._user:
            print("  no_auth mode — skipping login")
            return
        resp = self._http.post(
            f"{self._base}/api/v1/login",
            json={"username": self._user, "password": self._pass},
        )
        resp.raise_for_status()
        self._api_key = resp.json()["api_key"]
        print("  logged in, got API key")

    def get_all_devices(self) -> list[NetdiscoDevice]:
        resp = self._http.get(
            f"{self._base}/api/v1/report/device/deviceinventory",
            headers=self._headers(),
        )
        resp.raise_for_status()
        rows = resp.json()
        print(f"  deviceinventory returned {len(rows)} rows")
        return _parse_inventory_rows(rows)

    def get_ports(self, ip: str) -> list[NetdiscoPort]:
        resp = self._http.get(
            f"{self._base}/api/v1/object/device/{ip}/ports",
            headers=self._headers(),
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        ports = []
        for item in resp.json():
            try:
                ports.append(NetdiscoPort(**item))
            except Exception as e:
                print(f"  WARN: could not parse port on {ip}: {e}")
        return ports

    def get_device_ips(self, ip: str) -> list[NetdiscoDeviceIP]:
        """Routed IPs assigned to interfaces (replaces old /addresses endpoint)."""
        resp = self._http.get(
            f"{self._base}/api/v1/object/device/{ip}/device_ips",
            headers=self._headers(),
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        result = []
        for item in resp.json():
            try:
                result.append(NetdiscoDeviceIP(**item))
            except Exception as e:
                print(f"  WARN: could not parse device_ip on {ip}: {e}")
        return result

    def get_port_vlans(self, ip: str) -> list[NetdiscoPortVlan]:
        """All port-VLAN memberships including tagged trunk entries."""
        resp = self._http.get(
            f"{self._base}/api/v1/object/device/{ip}/port_vlans",
            headers=self._headers(),
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        result = []
        for item in resp.json():
            try:
                result.append(NetdiscoPortVlan(**item))
            except Exception as e:
                print(f"  WARN: could not parse port_vlan on {ip}: {e}")
        return result

    def get_nodes(self, ip: str) -> list[NetdiscoNode]:
        """MAC-table nodes seen on a device — the raw host discovery data."""
        resp = self._http.get(
            f"{self._base}/api/v1/object/device/{ip}/nodes",
            headers=self._headers(),
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        result = []
        for item in resp.json():
            try:
                result.append(NetdiscoNode(**item))
            except Exception as e:
                print(f"  WARN: could not parse node on {ip}: {e}")
        return result

    def get_ip_inventory(self, subnet: str) -> dict[str, str]:
        """
        Query the IP Inventory report for a subnet.
        Returns {mac: ip} for all entries found.
        The subnet parameter is required by Netdisco (e.g. '10.1.0.0/18').
        """
        resp = self._http.get(
            f"{self._base}/api/v1/report/ip/ipinventory",
            params={"subnet": subnet, "limit": "8192"},
            headers=self._headers(),
        )
        if resp.status_code in (404, 400):
            return {}
        resp.raise_for_status()
        try:
            rows = resp.json()
        except Exception:
            return {}
        mac_to_ip: dict[str, str] = {}
        for row in rows:
            mac = row.get("mac")
            ip  = row.get("ip")
            if mac and ip:
                mac_to_ip[mac] = ip
        return mac_to_ip

    def get_vlans(self, ip: str) -> list[NetdiscoVlan]:
        resp = self._http.get(
            f"{self._base}/api/v1/object/device/{ip}/vlans",
            headers=self._headers(),
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        vlans = []
        for item in resp.json():
            try:
                vlans.append(NetdiscoVlan(**item))
            except Exception as e:
                print(f"  WARN: could not parse vlan on {ip}: {e}")
        return vlans

    def close(self):
        self._http.close()


def _parse_inventory_rows(rows: list[dict]) -> list[NetdiscoDevice]:
    by_ip: dict[str, NetdiscoDevice] = {}
    for row in rows:
        ip = row.get("ip")
        if not ip:
            continue
        device = NetdiscoDevice(
            ip=ip,
            name=row.get("device_name"),
            vendor=row.get("vendor"),
            model=_clean_model(row.get("model")),
            serial=row.get("serial") or None,
            location=row.get("location") or None,
            os=row.get("os"),
            os_ver=row.get("version"),
            description=row.get("device_details"),
        )
        if ip not in by_ip:
            by_ip[ip] = device
        else:
            existing = by_ip[ip]
            if device.serial and not existing.serial:
                by_ip[ip] = device
    return list(by_ip.values())


def _clean_model(model: str | None) -> str | None:
    if not model:
        return None
    return model.split("|")[0].strip() or None
