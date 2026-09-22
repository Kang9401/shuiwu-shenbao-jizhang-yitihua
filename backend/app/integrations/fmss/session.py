from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from .errors import FmssNotAuthenticated


@dataclass(frozen=True)
class FmssSessionSnapshot:
    connected: bool
    username: str | None
    display_name: str | None
    generation: int


class FmssSession:
    """Process-only identity state.  Deliberately has no persistence method."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._token: str | None = None
        self._username: str | None = None
        self._display_name: str | None = None
        self._connected_at: datetime | None = None
        self._generation = 0

    def connect(self, token: str, username: str | None = None, display_name: str | None = None) -> int:
        if not token.strip():
            raise ValueError("FMSS token is required")
        with self._lock:
            self._token = token.strip()
            self._username = username.strip() if username and username.strip() else None
            self._display_name = display_name.strip() if display_name and display_name.strip() else None
            self._connected_at = datetime.utcnow()
            self._generation += 1
            return self._generation

    def clear(self) -> None:
        with self._lock:
            self._token = None
            self._username = None
            self._display_name = None
            self._connected_at = None
            self._generation += 1

    def set_identity(self, username: str | None, display_name: str | None) -> None:
        with self._lock:
            self._username = username.strip() if username and username.strip() else None
            self._display_name = display_name.strip() if display_name and display_name.strip() else None

    def snapshot(self) -> FmssSessionSnapshot:
        with self._lock:
            return FmssSessionSnapshot(bool(self._token), self._username, self._display_name, self._generation)

    def authorization_header(self) -> tuple[str, int]:
        with self._lock:
            if not self._token:
                raise FmssNotAuthenticated()
            return f"Bearer {self._token}", self._generation


fmss_session = FmssSession()
