import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    # Netdisco
    netdisco_url: str
    netdisco_user: str | None
    netdisco_pass: str | None

    # Diode
    diode_target: str
    diode_client_id: str
    diode_client_secret: str

    # NetBox defaults for infrastructure sync
    default_site: str
    default_role: str
    # Optional, unlike site/role above - None means the field is simply omitted from
    # whatever gets pushed, not defaulted to a placeholder. Only used as the fallback when
    # rules.yaml doesn't have a more specific default_tenant/default_location (per-VLAN) or
    # device_overrides (per-device) entry - see classifier.py/transformer.py.
    default_tenant: str | None
    default_location: str | None
    # Optional per-deployment mgmt/OOB subnet (e.g. "10.1.30.0/24" in the lab,
    # "10.60.80.0/24" at the rodeo) - lets transformer.py confidently attach a device's
    # portless polling IP (device_ips reports port=None for it - see CLAUDE.md) to its
    # real named mgmt interface instead of the less reliable ports[].ip fallback lookup.
    # None means that fallback lookup is all that's used, same as before this existed.
    oob_subnet: str | None

    # Discovery / reconciliation engine
    rules_file: str
    staging_db: str
    consumer_vendors_file: str
    min_days_stable: int
    stale_days: int
    notify_days: int
    decommission_days: int
    prune_days: int

    # Lifecycle reconciler (lifecycle.py) - separate NetBox REST API credential, not Diode.
    # Deliberately distinct from Diode's own identity even though it's not delete-capable
    # yet: the observation pipelines (sync.py/discover.py) should never need write access
    # to Device status/custom fields beyond what Diode ingestion already implies.
    netbox_url: str | None
    netbox_token: str | None
    lifecycle_active_days: int
    lifecycle_stale_days: int
    lifecycle_review_days: int
    lifecycle_decommission_days: int

    # Web UI (webapp.py) - HTTP Basic Auth, since it can promote devices and edit rules.yaml
    webui_user: str | None
    webui_password: str | None
    webui_port: int


def load_config() -> Config:
    return Config(
        # No real-host fallback defaults here on purpose - .env (or the Ansible-templated
        # .env this repo generates from config.yaml's netdisco_netbox_sync block) should
        # always set these explicitly. If NETDISCO_URL/DIODE_TARGET are ever missing, that
        # should surface as an obvious connection failure, not silently point at someone
        # else's host.
        netdisco_url=os.getenv("NETDISCO_URL", "http://netdisco:5000"),
        netdisco_user=os.getenv("NETDISCO_USER"),
        netdisco_pass=os.getenv("NETDISCO_PASS"),
        diode_target=os.getenv("DIODE_TARGET", "grpc://diode:8080/diode"),
        diode_client_id=os.getenv("DIODE_CLIENT_ID", "diode-ingest"),
        diode_client_secret=os.getenv("DIODE_CLIENT_SECRET", "changeme"),
        default_site=os.getenv("DEFAULT_SITE", "Unknown"),
        default_role=os.getenv("DEFAULT_ROLE", "Network Device"),
        default_tenant=os.getenv("DEFAULT_TENANT") or None,
        default_location=os.getenv("DEFAULT_LOCATION") or None,
        oob_subnet=os.getenv("OOB_SUBNET") or None,
        rules_file=os.getenv("RULES_FILE", "rules.yaml"),
        staging_db=os.getenv("STAGING_DB", "data/observed_assets.db"),
        consumer_vendors_file=os.getenv("CONSUMER_VENDORS_FILE", "consumer_oui_vendors.txt"),
        min_days_stable=int(os.getenv("MIN_DAYS_STABLE", "7")),
        stale_days=int(os.getenv("STALE_DAYS", "30")),
        notify_days=int(os.getenv("NOTIFY_DAYS", "90")),
        decommission_days=int(os.getenv("DECOMMISSION_DAYS", "180")),
        prune_days=int(os.getenv("PRUNE_DAYS", "2")),
        netbox_url=os.getenv("NETBOX_URL") or None,
        netbox_token=os.getenv("NETBOX_TOKEN") or None,
        lifecycle_active_days=int(os.getenv("LIFECYCLE_ACTIVE_DAYS", "7")),
        lifecycle_stale_days=int(os.getenv("LIFECYCLE_STALE_DAYS", "30")),
        lifecycle_review_days=int(os.getenv("LIFECYCLE_REVIEW_DAYS", "90")),
        lifecycle_decommission_days=int(os.getenv("LIFECYCLE_DECOMMISSION_DAYS", "180")),
        webui_user=os.getenv("WEBUI_USER") or None,
        webui_password=os.getenv("WEBUI_PASSWORD") or None,
        webui_port=int(os.getenv("WEBUI_PORT", "8090")),
    )
