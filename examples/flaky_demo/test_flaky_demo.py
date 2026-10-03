"""Demo input for the flaky-test detector (deliberately NOT part of the real suite).

    python -m qa_suite.flaky --runs 4 --out reports/flaky-demo -- examples/flaky_demo

* test_stable passes every run.
* test_order_dependent fails on every other run: it depends on hidden state left
  behind by a previous run (a counter file).
* test_real_bug fails every run: the detector must report it as a stable failure,
  never hide it as "flaky".
"""

from __future__ import annotations

from pathlib import Path

COUNTER = Path(__file__).resolve().parents[2] / "test-results" / "flaky-demo-counter"


def test_stable() -> None:
    assert sum([1, 2, 3]) == 6


def test_order_dependent() -> None:
    COUNTER.parent.mkdir(parents=True, exist_ok=True)
    runs = int(COUNTER.read_text()) if COUNTER.exists() else 0
    COUNTER.write_text(str(runs + 1))
    assert runs % 2 == 0, f"leftover state from run {runs} changed the outcome"


def test_real_bug() -> None:
    assert 0.1 + 0.2 == 0.3, "a deterministic, reproducible failure (float rounding)"
