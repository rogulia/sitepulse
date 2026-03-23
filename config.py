import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]

# Monitoring target
BASE_URL = os.getenv("BASE_URL", "https://example.com")
SITEMAP_URL = f"{BASE_URL}{os.getenv('SITEMAP_PATH', '/sitemap.xml')}"

# Monitoring thresholds
MIN_RESPONSE_SIZE = int(os.getenv("MIN_RESPONSE_SIZE", "1000"))
CONNECT_TIMEOUT = int(os.getenv("CONNECT_TIMEOUT", "20"))
READ_TIMEOUT = int(os.getenv("READ_TIMEOUT", "60"))
SLOW_RESPONSE_THRESHOLD = int(os.getenv("SLOW_RESPONSE_THRESHOLD", "10"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "10"))

# Notification flags
NOTIFY_SUCCESS = os.getenv("NOTIFY_SUCCESS", "false").lower() == "true"
NOTIFY_WARNING = os.getenv("NOTIFY_WARNING", "false").lower() == "true"
NOTIFY_ERROR = os.getenv("NOTIFY_ERROR", "true").lower() == "true"

# Domain expiry warning
EXPIRY_WARNING_DAYS = int(os.getenv("EXPIRY_WARNING_DAYS", "90"))

# Log retention
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "10"))

# Log file path
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "website_monitor.log")


def parse_domains(raw: str) -> dict:
    """Parse DOMAINS_TO_CHECK env var.

    Format: domain1,domain2:expiry=2025-02-11,domain3
    """
    domains = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":expiry=" in entry:
            domain, expiry = entry.split(":expiry=", 1)
            domains[domain.strip()] = {"expiry": expiry.strip()}
        else:
            domains[entry] = {}
    return domains


def parse_nameservers(raw: str) -> list:
    return [ns.strip() for ns in raw.split(",") if ns.strip()]


DOMAINS_TO_CHECK = parse_domains(os.getenv("DOMAINS_TO_CHECK", ""))
OUR_NAMESERVERS = parse_nameservers(os.getenv("OUR_NAMESERVERS", ""))
