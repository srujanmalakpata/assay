"""The load-test gate must fail slow, erroring or empty runs."""

from __future__ import annotations

import pytest

from qa_suite.load_gate import LoadResult, Thresholds, evaluate, summary

pytestmark = pytest.mark.unit

T = Thresholds(p95_ms=300, max_error_rate=0.01, min_requests=100)


def result(**kw: float) -> LoadResult:
    base = {"requests": 1000, "failures": 0, "p50_ms": 20, "p95_ms": 120, "p99_ms": 200, "rps": 30}
    return LoadResult(**{**base, **kw})


def test_healthy_run_passes() -> None:
    assert evaluate(result(), T) == []
    assert summary(result(), T)["passed"] is True


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"p95_ms": 301}, "p95 301 ms > 300 ms"),
        ({"failures": 11}, "error rate 1.10% > 1.00%"),
        ({"requests": 50, "failures": 0}, "only 50 requests (< 100)"),
    ],
)
def test_each_threshold_breach_is_reported(overrides: dict[str, float], expected: str) -> None:
    assert evaluate(result(**overrides), T) == [expected]


def test_boundaries_are_inclusive() -> None:
    assert evaluate(result(p95_ms=300, failures=10), T) == []  # exactly at the limit passes


def test_zero_requests_counts_as_total_failure() -> None:
    assert result(requests=0).error_rate == 1.0
