import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    netdisco_url: str
    netdisco_user: str | None
    netdisco_pass: str | None
    diode_target: str
    diode_client_id: str
    diode_client_secret: str
    default_site: str
    default_role: str

def load_config() -> Config:
    return Config(
        netdisco_url=os.getenv("NETDISCO_URL", "http://10.1.88.114:5000"),
        netdisco_user=os.getenv("NETDISCO_USER"),
        netdisco_pass=os.getenv("NETDISCO_PASS"),
        diode_target=os.getenv("DIODE_TARGET", "grpc://10.1.88.114:8080"),
        diode_client_id=os.getenv("DIODE_CLIENT_ID", "diode"),
        diode_client_secret=os.getenv("DIODE_CLIENT_SECRET", "changeme"),
        default_site=os.getenv("DEFAULT_SITE", "Unknown"),
        default_role=os.getenv("DEFAULT_ROLE", "Network Device"),
    )
