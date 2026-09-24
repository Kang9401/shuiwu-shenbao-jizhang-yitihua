from app.core.config import settings


def api_base_url() -> str:
    return settings.fmss_api_base_url.rstrip("/")
