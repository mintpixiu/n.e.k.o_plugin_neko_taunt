"""Read N.E.K.O's own proactive-chat switch over loopback HTTP.

The host exposes ``GET /api/proactive/mode`` on the main server (default
``127.0.0.1:48911``).  This module only talks to that literal loopback endpoint;
it cannot be pointed at an external host.  The request is tiny, read-only and
cached briefly so the plugin's 60-second timer does not poll the host.

The SDK-free parser is separated from the HTTP call so the Linux CI tests can
validate it without a host.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "http://127.0.0.1:48911"
_PATH = "/api/proactive/mode"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True, slots=True)
class HostProactiveState:
    """A small, immutable snapshot of the host's proactive-chat setting."""

    available: bool
    enabled: bool
    interval_seconds: int
    mode: str
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "mode": self.mode,
            "error": self.error,
        }


def is_loopback_base_url(base_url: str) -> bool:
    """Accept only a plain http loopback base URL with no path or credentials."""

    try:
        parsed = urlparse(str(base_url))
    except ValueError:
        return False
    if parsed.scheme != "http" or parsed.hostname not in _LOOPBACK_HOSTS:
        return False
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    if parsed.path not in ("", "/"):
        return False
    if parsed.port is not None and not (1 <= parsed.port <= 65535):
        return False
    return True


def parse_host_proactive_payload(payload: Any) -> HostProactiveState:
    """Parse the documented ``/api/proactive/mode`` response."""

    if not isinstance(payload, Mapping):
        return HostProactiveState(False, False, 0, "unknown", "invalid_payload")
    if payload.get("success") is not True:
        return HostProactiveState(False, False, 0, "unknown", "unsuccessful")
    settings = payload.get("settings")
    if not isinstance(settings, Mapping):
        return HostProactiveState(False, False, 0, "unknown", "invalid_settings")
    enabled = settings.get("proactiveChatEnabled") is True
    try:
        interval = int(settings.get("proactiveChatInterval") or 0)
    except (TypeError, ValueError):
        interval = 0
    interval = max(0, min(3600, interval))
    mode = payload.get("mode")
    if not isinstance(mode, str) or not mode.strip():
        mode = "custom"
    return HostProactiveState(True, enabled, interval, mode.strip())


def fetch_host_proactive(
    base_url: str = DEFAULT_BASE_URL,
    *,
    timeout: float = 2.5,
) -> HostProactiveState:
    """Read the host setting; any transport failure becomes ``available=False``."""

    if not is_loopback_base_url(base_url):
        return HostProactiveState(False, False, 0, "unknown", "non_loopback_url")
    url = str(base_url).rstrip("/") + _PATH
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=max(0.2, min(10.0, float(timeout)))) as response:
            raw = response.read(65536)
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - all failures are a non-fatal probe failure
        return HostProactiveState(False, False, 0, "unknown", type(exc).__name__)
    return parse_host_proactive_payload(payload)


class HostProactiveProbe:
    """Short-lived cache around :func:`fetch_host_proactive`."""

    def __init__(
        self,
        *,
        fetcher: Callable[[], HostProactiveState] = fetch_host_proactive,
        ttl_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetcher = fetcher
        self._ttl = max(1.0, float(ttl_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._state: HostProactiveState | None = None
        self._fetched_at = 0.0

    def get(self, *, force: bool = False) -> HostProactiveState:
        now = self._clock()
        with self._lock:
            if (
                not force
                and self._state is not None
                and now - self._fetched_at < self._ttl
            ):
                return self._state
        state = self._fetcher()
        with self._lock:
            self._state = state
            self._fetched_at = now
        return state

    def invalidate(self) -> None:
        with self._lock:
            self._state = None
            self._fetched_at = 0.0