from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import urlparse

from app.core.config import settings


def allowed_fmss_host(url: str) -> bool:
    """Accept values only from the configured FMSS host, never the OA host."""
    parsed = urlparse(url)
    configured = urlparse(settings.fmss_login_url).hostname
    return bool(parsed.scheme in {"http", "https"} and parsed.hostname == configured)


def is_fmss_business_page(url: str) -> bool:
    parsed = urlparse(url)
    return allowed_fmss_host(url) and parsed.path.startswith("/fmss/trip/")


def extract_admin_token(cookies: object) -> str | None:
    """Extract only Admin-Token from pywebview's cookie result."""
    if isinstance(cookies, Mapping):
        direct = cookies.get("Admin-Token")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        if cookies.get("name") == "Admin-Token":
            value = cookies.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested = cookies.get("cookies")
        if nested is not cookies:
            return extract_admin_token(nested)
        return None
    if isinstance(cookies, Sequence) and not isinstance(cookies, (str, bytes, bytearray)):
        for cookie in cookies:
            if isinstance(cookie, Mapping) and cookie.get("name") == "Admin-Token":
                value = cookie.get("value")
                if isinstance(value, str) and value.strip():
                    return value.strip()
            if getattr(cookie, "name", None) == "Admin-Token":
                value = getattr(cookie, "value", None)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None
