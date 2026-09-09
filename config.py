import os

from dotenv import load_dotenv


load_dotenv()

PHIZ_BASE_URL = os.getenv("PHIZ_BASE_URL", "https://app.phiz.chat").rstrip("/")
PHIZ_APP_ID = os.getenv("PHIZ_APP_ID", "").strip()
PHIZ_APP_SECRET = os.getenv("PHIZ_APP_SECRET", "").strip()
PHIZ_CHANNEL_ID = os.getenv("PHIZ_CHANNEL_ID", "").strip()

ACADEMIC_API_BASE_URL = os.getenv(
    "ACADEMIC_API_BASE_URL",
    "https://ijf-dev-api.onrender.com",
).rstrip("/")
ACADEMIC_API_TIMEOUT_SECONDS = float(
    os.getenv("ACADEMIC_API_TIMEOUT_SECONDS", "60")
)

SECRETARY_INBOUND_API_KEY = os.getenv("SECRETARY_INBOUND_API_KEY", "").strip()
CONTENT_ALLOWED_HOSTS = {
    host.strip().lower()
    for host in os.getenv("CONTENT_ALLOWED_HOSTS", "").split(",")
    if host.strip()
}
CONTENT_TIMEOUT_SECONDS = float(os.getenv("CONTENT_TIMEOUT_SECONDS", "30"))
MAX_JSON_SIZE_BYTES = int(os.getenv("MAX_JSON_SIZE_BYTES", str(1024 * 1024)))
MAX_CONTENT_SIZE_BYTES = int(
    os.getenv("MAX_CONTENT_SIZE_BYTES", str(1024 * 1024))
)

QUEUE_WORKERS = max(1, int(os.getenv("QUEUE_WORKERS", "4")))
QUEUE_MAX_SIZE = max(1, int(os.getenv("QUEUE_MAX_SIZE", "1000")))


def missing_required_settings():
    settings = {
        "SECRETARY_INBOUND_API_KEY": SECRETARY_INBOUND_API_KEY,
        "PHIZ_APP_ID": PHIZ_APP_ID,
        "PHIZ_APP_SECRET": PHIZ_APP_SECRET,
        "PHIZ_CHANNEL_ID": PHIZ_CHANNEL_ID,
    }
    return [name for name, value in settings.items() if not value]
