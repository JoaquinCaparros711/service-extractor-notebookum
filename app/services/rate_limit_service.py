"""In-memory fixed-window rate limiting."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Dict, Tuple


@dataclass(frozen=True)
class RateLimitDecision:
    """Decision returned after checking a client quota."""

    allowed: bool
    retry_after: int


class FixedWindowRateLimiter:
    """Simple fixed-window limiter for internal service consumers."""

    def __init__(self):
        self._clients: Dict[str, Tuple[float, int]] = {}
        self._lock = Lock()

    def check(self, client_id: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = monotonic()
        with self._lock:
            window_start, count = self._clients.get(client_id, (now, 0))
            elapsed = now - window_start

            if elapsed >= window_seconds:
                self._clients[client_id] = (now, 1)
                return RateLimitDecision(allowed=True, retry_after=0)

            if count >= limit:
                retry_after = max(1, int(window_seconds - elapsed))
                return RateLimitDecision(allowed=False, retry_after=retry_after)

            self._clients[client_id] = (window_start, count + 1)
            return RateLimitDecision(allowed=True, retry_after=0)


rate_limiter = FixedWindowRateLimiter()
