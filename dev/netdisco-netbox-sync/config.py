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

    # Discovery / reconciliation engine
    rules_file: str
    staging_db: str
    consumer_vendors_file: str
    min_days_stable: int
    stale_days: int
    notify_days: int
    decommission_days: int


def load_config() -> Config:
    return Config(
        netdisco_url=os.getenv("NETDISCO_URL", "http://10.1.88.114:5000"),
        netdisco_user=os.getenv("NETDISCO_USER"),
        netdisco_pass=os.getenv("NETDISCO_PASS"),
        diode_target=os.getenv("DIODE_TARGET", "grpc://10.1.88.114:8080/diode"),
        diode_client_id=os.getenv("DIODE_CLIENT_ID", "diode-ingest"),
        diode_client_secret=os.getenv("DIODE_CLIENT_SECRET", "changeme"),
        default_site=os.getenv("DEFAULT_SITE", "Unknown"),
        default_role=os.getenv("DEFAULT_ROLE", "Network Device"),
        rules_file=os.getenv("RULES_FILE", "rules.yaml"),
        staging_db=os.getenv("STAGING_DB", "data/observed_assets.db"),
        consumer_vendors_file=os.getenv("CONSUMER_VENDORS_FILE", "consumer_oui_vendors.txt"),
        min_days_stable=int(os.getenv("MIN_DAYS_STABLE", "7")),
        stale_days=int(os.getenv("STALE_DAYS", "30")),
        notify_days=int(os.getenv("NOTIFY_DAYS", "90")),
        decommission_days=int(os.getenv("DECOMMISSION_DAYS", "180")),
    )
