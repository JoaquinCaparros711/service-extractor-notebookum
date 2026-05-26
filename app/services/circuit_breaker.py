"""Circuit breaker primitives for extractor dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic


@dataclass
class CircuitBreaker:
    """Small closed/open/half-open circuit breaker."""

    failure_threshold: int
    reset_seconds: float
    failure_count: int = 0
    opened_at: float | None = None
    half_open: bool = False

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if self.half_open:
            return "half_open"
        return "open"

    def allow_request(self) -> bool:
        if self.opened_at is None:
            return True

        if monotonic() - self.opened_at >= self.reset_seconds:
            self.half_open = True
            return True

        return False

    def record_success(self) -> None:
        self.failure_count = 0
        self.opened_at = None
        self.half_open = False

    def record_failure(self) -> None:
        self.failure_count += 1
        self.half_open = False
        if self.failure_count >= self.failure_threshold:
            self.opened_at = monotonic()

    def configure(self, failure_threshold: int, reset_seconds: float) -> None:
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds


docling_circuit_breaker = CircuitBreaker(failure_threshold=3, reset_seconds=30)
