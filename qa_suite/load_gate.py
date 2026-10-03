"""Pass/fail gate for load-test results (pure logic, unit tested).

Locust measures; this module decides. Keeping the decision separate from Locust
means the thresholds are easy to read, review and test.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Thresholds:
    p95_ms: float = 300.0
    max_error_rate: float = 0.01  # 1 %
    min_requests: int = 100  # guards against a "pass" where almost nothing ran

    @classmethod
    def from_env(cls) -> Thresholds:
        return cls(
            p95_ms=float(os.environ.get("LOAD_P95_MS", cls.p95_ms)),
            max_error_rate=float(os.environ.get("LOAD_MAX_ERROR_RATE", cls.max_error_rate)),
            min_requests=int(os.environ.get("LOAD_MIN_REQUESTS", cls.min_requests)),
        )


@dataclass(frozen=True)
class LoadResult:
    requests: int
    failures: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    rps: float

    @property
    def error_rate(self) -> float:
        return self.failures / self.requests if self.requests else 1.0


def evaluate(result: LoadResult, thresholds: Thresholds) -> list[str]:
    """Return human-readable threshold breaches; an empty list means the run passed."""
    breaches = []
    if result.requests < thresholds.min_requests:
        breaches.append(f"only {result.requests} requests (< {thresholds.min_requests})")
    if result.p95_ms > thresholds.p95_ms:
        breaches.append(f"p95 {result.p95_ms:.0f} ms > {thresholds.p95_ms:.0f} ms")
    if result.error_rate > thresholds.max_error_rate:
        breaches.append(f"error rate {result.error_rate:.2%} > {thresholds.max_error_rate:.2%}")
    return breaches


def summary(result: LoadResult, thresholds: Thresholds) -> dict[str, object]:
    breaches = evaluate(result, thresholds)
    return {
        "passed": not breaches,
        "breaches": breaches,
        "result": {**asdict(result), "error_rate": round(result.error_rate, 5)},
        "thresholds": asdict(thresholds),
    }
