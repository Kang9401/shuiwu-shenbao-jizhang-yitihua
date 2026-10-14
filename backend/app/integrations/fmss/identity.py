from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings

from .client import FmssClient


@dataclass(frozen=True)
class FmssIdentity:
    username: str | None = None
    display_name: str | None = None


class FmssIdentityResolver:
    """Resolve FMSS identity without borrowing submitter/reviewer fields.

    The current FMSS contract supplied to this project does not define a
    current-user endpoint.  Until one is confirmed, no speculative request is
    made and the session remains connected with a nullable identity.
    """

    def resolve(self, client: FmssClient) -> FmssIdentity:
        path = settings.fmss_current_user_path.strip()
        if not path:
            return FmssIdentity()
        payload = client.current_user(path)
        return self._parse(payload)

    @staticmethod
    def _parse(payload: Any) -> FmssIdentity:
        value = payload.get("user", payload) if isinstance(payload, dict) else {}
        if not isinstance(value, dict):
            return FmssIdentity()
        username = value.get("username") or value.get("userName") or value.get("loginName") or value.get("account")
        display_name = value.get("displayName") or value.get("name") or value.get("nickName")
        return FmssIdentity(
            username=str(username).strip() if username else None,
            display_name=str(display_name).strip() if display_name else None,
        )
