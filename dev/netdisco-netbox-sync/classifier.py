"""
Classification engine.
Reads rules.yaml + consumer_oui_vendors.txt and classifies each ObservedAsset.
Returns (classification, reason) — never writes to DB itself.
"""
import yaml
from dataclasses import dataclass
from typing import Optional
from staging import ObservedAsset


@dataclass
class VlanPolicy:
    intent: str              # infrastructure / lab / corporate / ignore
    default_role: str = "Server"
    default_site: str = "Unknown"
    # Unlike role/site (every device needs one), tenant/location are genuinely optional -
    # None means "don't set this field at all" (Diode/NetBox leave it blank), not "unknown".
    default_tenant: Optional[str] = None
    default_location: Optional[str] = None
    description: str = ""


@dataclass
class DeviceOverride:
    # Explicit per-device site/tenant/location for infrastructure devices (sync.py) -
    # deliberately NOT derived from VLAN membership, since a switch typically serves many
    # VLANs and its site/tenant/location is about physical/organizational ownership, not
    # traffic it carries.
    # Real bug this fixes: NetBox's own Device uniqueness is (name, site, tenant) together -
    # manually changing a device's Site OR Tenant in the NetBox UI without this tool also
    # sending the same value every run caused sync.py's next push to create a duplicate
    # (see transformer.py's own comment). site was added after tenant/location - the same
    # bug existed for it too, just hadn't been hit yet since nothing overrode it at all.
    site: Optional[str] = None
    tenant: Optional[str] = None
    location: Optional[str] = None
    # Role override - falls back to transformer.py's _device_role() vendor/model heuristic
    # when unset. That heuristic can't reliably tell e.g. a core switch from an access
    # switch from a model number alone - this is the escape hatch for those cases,
    # editable from the Config page without a code change.
    role: Optional[str] = None


@dataclass
class Rules:
    vlan_policy: dict[str, VlanPolicy]
    gateway_suffixes: list[str]
    ip_inventory_subnets: list[str]
    device_overrides: dict[str, DeviceOverride]


def load_rules(rules_file: str) -> Rules:
    with open(rules_file) as f:
        raw = yaml.safe_load(f)

    policies = {}
    for vid, cfg in raw.get("vlan_policy", {}).items():
        policies[str(vid)] = VlanPolicy(
            intent=cfg.get("intent", "unclassified"),
            default_role=cfg.get("default_role", "Server"),
            default_site=cfg.get("default_site", "Unknown"),
            default_tenant=cfg.get("default_tenant") or None,
            default_location=cfg.get("default_location") or None,
            description=cfg.get("description", ""),
        )

    overrides = {}
    for name, cfg in (raw.get("device_overrides") or {}).items():
        overrides[name] = DeviceOverride(
            site=(cfg or {}).get("site") or None,
            tenant=(cfg or {}).get("tenant") or None,
            location=(cfg or {}).get("location") or None,
            role=(cfg or {}).get("role") or None,
        )

    return Rules(
        vlan_policy=policies,
        gateway_suffixes=raw.get("gateway_suffixes", [".1", ".2"]),
        ip_inventory_subnets=raw.get("ip_inventory_subnets", []),
        device_overrides=overrides,
    )


def load_consumer_vendors(vendors_file: str) -> list[str]:
    try:
        with open(vendors_file) as f:
            return [
                line.strip() for line in f
                if line.strip() and not line.startswith("#")
            ]
    except FileNotFoundError:
        return []


def classify(
    asset: ObservedAsset,
    rules: Rules,
    consumer_vendors: list[str],
    min_days_stable: int,
) -> tuple[str, str]:
    """
    Returns (classification, reason).
    Classification: unclassified / ignore / candidate / managed
    """

    # --- 1. Consumer device (universal ignore, regardless of VLAN) ---
    vendor = (asset.vendor or "").lower()
    for cv in consumer_vendors:
        if cv.lower() in vendor:
            return "ignore", f"Consumer device ({asset.vendor})"

    # --- 2. Gateway IP (already managed as a Device SVI) ---
    if asset.ip:
        for suffix in rules.gateway_suffixes:
            if asset.ip.endswith(suffix):
                return "ignore", f"Gateway IP {asset.ip}"

    # --- 3. VLAN intent ---
    vlan_key = str(asset.vlan or "")
    policy = rules.vlan_policy.get(vlan_key)
    days = asset.days_stable or 0.0

    if not policy:
        # Unknown VLAN — become candidate after stability threshold
        if days >= min_days_stable:
            return "candidate", f"Unknown VLAN {asset.vlan}, stable {days:.1f} days — needs review"
        return "unclassified", f"Unknown VLAN {asset.vlan}, only {days:.1f}/{min_days_stable} days"

    intent = policy.intent

    if intent == "ignore":
        return "ignore", f"VLAN {vlan_key} policy: {policy.description or 'ignore'}"

    if intent == "infrastructure":
        if days >= min_days_stable:
            if not asset.ip:
                return "ignore", (
                    f"Infrastructure VLAN {vlan_key} ({policy.description}), "
                    f"stable {days:.1f} days but never seen in ARP/IP inventory — "
                    f"likely a non-addressed interface (bridge/uplink), not a host"
                )
            return "managed", (
                f"Infrastructure VLAN {vlan_key} ({policy.description}), "
                f"stable {days:.1f} days"
            )
        return "unclassified", (
            f"Infrastructure VLAN {vlan_key}, only {days:.1f}/{min_days_stable} days"
        )

    if intent in ("lab", "corporate"):
        if days >= min_days_stable:
            return "candidate", (
                f"{intent.title()} VLAN {vlan_key} ({policy.description}), "
                f"stable {days:.1f} days — manual promote required"
            )
        return "unclassified", (
            f"{intent.title()} VLAN {vlan_key}, only {days:.1f}/{min_days_stable} days"
        )

    return "unclassified", f"No matching rule for VLAN {vlan_key}"


def vlan_defaults(
    vlan: Optional[str], rules: Rules, fallback_site: str, fallback_role: str,
    fallback_tenant: Optional[str] = None, fallback_location: Optional[str] = None,
) -> tuple[str, str, Optional[str], Optional[str]]:
    """Return (site, role, tenant, location) for a given VLAN based on rules.

    tenant/location are genuinely optional throughout - a None fallback plus no
    per-VLAN default_tenant/default_location means the field is simply omitted from
    whatever gets pushed, not defaulted to some placeholder value.
    """
    policy = rules.vlan_policy.get(str(vlan or ""))
    if policy:
        return (
            policy.default_site or fallback_site,
            policy.default_role or fallback_role,
            policy.default_tenant or fallback_tenant,
            policy.default_location or fallback_location,
        )
    return fallback_site, fallback_role, fallback_tenant, fallback_location
