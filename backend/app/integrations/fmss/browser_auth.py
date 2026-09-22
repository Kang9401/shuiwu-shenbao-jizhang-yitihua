from __future__ import annotations

from urllib.parse import urlparse

from app.core.config import settings

from .client import FmssClient
from .errors import FmssApiError
from .identity import FmssIdentityResolver
from .session import FmssSession, fmss_session


def allowed_fmss_host(url: str) -> bool:
    """Only the configured FMSS host may provide an Authorization value."""
    parsed = urlparse(url)
    configured = {urlparse(settings.fmss_login_url).hostname, urlparse(settings.fmss_api_base_url).hostname}
    return bool(parsed.scheme in {"http", "https"} and parsed.hostname and parsed.hostname in configured)


def allowed_fmss_business_page(url: str) -> bool:
    """Only a loaded FMSS business page may submit a captured token."""
    parsed = urlparse(url)
    if not allowed_fmss_host(url):
        return False
    api_path = urlparse(settings.fmss_api_base_url).path.rstrip("/")
    login_path = urlparse(settings.fmss_login_url).path.rstrip("/")
    return parsed.path.startswith("/fmss/trip/") or parsed.path.startswith(api_path + "/") and not parsed.path.startswith(login_path)


def bearer_token(value: str) -> str | None:
    prefix, _, token = value.strip().partition(" ")
    if prefix.lower() != "bearer" or not token.strip() or any(char.isspace() for char in token.strip()):
        return None
    return token.strip()


class FmssBrowserAuthBridge:
    """pywebview bridge for a user-authenticated FMSS page.

    It accepts only a Bearer value from the configured FMSS host. Cookies,
    request bodies and all other headers are intentionally not exposed.
    """

    def __init__(self, session: FmssSession = fmss_session, on_connected=None) -> None:
        self.session = session
        self.on_connected = on_connected

    def set_fmss_token(self, token: str, page_url: str) -> dict[str, object]:
        if not allowed_fmss_business_page(page_url):
            raise ValueError("FMSS token capture is allowed only on an FMSS business page")
        token = bearer_token(token) or token.strip()
        if not token or any(char.isspace() for char in token):
            raise ValueError("A valid FMSS token is required")
        self.session.connect(token)
        try:
            # A read-only validation is the only request made during capture.
            FmssClient(self.session).sheets("PRE")
            identity = FmssIdentityResolver().resolve(FmssClient(self.session))
            self.session.set_identity(identity.username, identity.display_name)
        except Exception:
            self.session.clear()
            raise FmssApiError("FMSS会话验证失败，请重新登录。")
        if self.on_connected:
            self.on_connected()
        snapshot = self.session.snapshot()
        return {"connected": True, "username": snapshot.username, "displayName": snapshot.display_name}


def capture_script(api_path: str | None = None) -> str:
    """Return a host-scoped hook; no storage enumeration or cookie access."""
    api_path = api_path or f"{urlparse(settings.fmss_api_base_url).path.rstrip('/')}/"
    safe_path = api_path.replace("\\", "\\\\").replace("'", "\\'")
    return f"""
(() => {{
  const allowedHost = {urlparse(settings.fmss_login_url).hostname!r};
  const apiPath = {safe_path!r};
  if (location.hostname !== allowedHost) return;
  let captured = false;
  const isApiRequest = (requestUrl) => {{
    try {{
      const parsed = new URL(requestUrl || '', location.href);
      return parsed.origin === location.origin && parsed.pathname.startsWith(apiPath);
    }} catch (_) {{
      return false;
    }}
  }};
  const restore = () => {{
    window.fetch = originalFetch;
    XMLHttpRequest.prototype.open = originalOpen;
    XMLHttpRequest.prototype.setRequestHeader = originalSet;
  }};
  const headerValue = (headers) => {{
    if (!headers) return '';
    if (typeof headers.get === 'function') return headers.get('Authorization') || headers.get('authorization') || '';
    if (Array.isArray(headers)) {{
      const pair = headers.find((item) => String(item?.[0]).toLowerCase() === 'authorization');
      return pair?.[1] || '';
    }}
    return headers.Authorization || headers.authorization || '';
  }};
  const deliver = (value, requestUrl) => {{
    if (captured) return;
    if (!value || !value.startsWith('Bearer ')) return;
    if (!isApiRequest(requestUrl)) return;
    if (window.pywebview?.api?.set_fmss_token) {{
      captured = true;
      restore();
      window.pywebview.api.set_fmss_token(value.slice(7).trim(), location.href);
    }}
  }};
  const originalFetch = window.fetch;
  window.fetch = function(input, init) {{
    const value = headerValue(init?.headers);
    const requestUrl = typeof input === 'string' ? input : input?.url;
    deliver(value, requestUrl);
    return originalFetch.apply(this, arguments);
  }};
  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSet = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.open = function() {{ this.__fmss_url = arguments[1]; return originalOpen.apply(this, arguments); }};
  XMLHttpRequest.prototype.setRequestHeader = function(name, value) {{
    if (String(name).toLowerCase() === 'authorization') deliver(value, this.__fmss_url);
    return originalSet.apply(this, arguments);
  }};
}})();
"""
