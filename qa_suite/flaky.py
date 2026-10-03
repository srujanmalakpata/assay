"""Flaky-test detector: rerun a pytest selection N times and compare outcomes.

Unlike retry plugins, this never turns a failure into a pass. Each run writes its
own JUnit XML; afterwards every test is classified:

* ``stable-pass``  passed in every run
* ``stable-fail``  failed in every run (a real, reproducible failure)
* ``flaky``        outcomes differ between runs (passed, failed, skipped or missing);
                   a test that passes in one run and is skipped in another is flaky too,
                   because a nondeterministic skip hides whether it works
* ``skipped``      skipped in every run

A test absent from a run's JUnit file is recorded as ``missing`` for that run, never
as a pass. A run that produced no JUnit file or an unreadable one, or whose pytest exit
code means "the run itself broke" (interrupted, internal error, usage error, no tests
collected), is reported as a broken run.

Exit codes: 0 all stable-pass/skipped; 1 a test failed or was flaky; 2 a run broke or
the report contains no tests at all. Nothing is ever retried into a pass.

    python -m qa_suite.flaky --runs 5 -- tests/api -m smoke
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path


class Outcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    MISSING = "missing"  # not reported in this run (crash, collection error, deselection)


# pytest exit codes: 0 all passed, 1 some tests failed. Anything else means the run
# itself did not complete normally (2 interrupted, 3 internal error, 4 usage error,
# 5 no tests collected), so its results cannot be trusted.
PYTEST_OK_EXIT_CODES = frozenset({0, 1})


class Verdict(StrEnum):
    STABLE_PASS = "stable-pass"
    STABLE_FAIL = "stable-fail"
    FLAKY = "flaky"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class TestHistory:
    test_id: str
    outcomes: tuple[Outcome, ...]

    @property
    def verdict(self) -> Verdict:
        seen = set(self.outcomes)
        if seen == {Outcome.SKIPPED}:
            return Verdict.SKIPPED
        if seen == {Outcome.PASSED}:
            return Verdict.STABLE_PASS
        if seen == {Outcome.FAILED}:
            return Verdict.STABLE_FAIL
        return Verdict.FLAKY


@dataclass(frozen=True)
class BrokenRun:
    run: int
    returncode: int
    reason: str


@dataclass
class FlakyReport:
    runs: int
    tests: list[TestHistory] = field(default_factory=list)
    broken_runs: list[BrokenRun] = field(default_factory=list)

    def by_verdict(self, verdict: Verdict) -> list[TestHistory]:
        return [t for t in self.tests if t.verdict is verdict]

    @property
    def exit_code(self) -> int:
        if self.broken_runs or not self.tests:
            return 2
        if self.by_verdict(Verdict.STABLE_FAIL) or self.by_verdict(Verdict.FLAKY):
            return 1
        return 0

    def summary(self) -> dict[str, int]:
        counts = Counter(t.verdict.value for t in self.tests)
        return {v.value: counts.get(v.value, 0) for v in Verdict}

    def to_json(self) -> str:
        return json.dumps(
            {
                "runs": self.runs,
                "summary": self.summary(),
                "broken_runs": [asdict(b) for b in self.broken_runs],
                "tests": [
                    {**asdict(t), "verdict": t.verdict.value}
                    for t in sorted(self.tests, key=lambda t: t.test_id)
                ],
            },
            indent=2,
        )

    def to_markdown(self) -> str:
        lines = [f"# Flaky-test report ({self.runs} runs)", ""]
        lines += [f"- **{name}**: {count}" for name, count in self.summary().items()]
        if not self.tests:
            lines += ["", "**No test results were recorded: nothing was verified.**"]
        if self.broken_runs:
            lines += [
                "",
                "## broken runs",
                "",
                "| run | pytest exit code | reason |",
                "|---|---|---|",
            ]
            lines += [f"| {b.run} | {b.returncode} | {b.reason} |" for b in self.broken_runs]
        for verdict in (Verdict.FLAKY, Verdict.STABLE_FAIL):
            tests = self.by_verdict(verdict)
            if tests:
                lines += ["", f"## {verdict.value}", "", "| test | outcomes per run |", "|---|---|"]
                lines += [
                    f"| `{t.test_id}` | {' '.join(o.value for o in t.outcomes)} |" for t in tests
                ]
        return "\n".join(lines) + "\n"


def parse_junit(xml_text: str) -> dict[str, Outcome]:
    """Map ``classname::name`` to the outcome of each <testcase> in a JUnit XML document."""
    root = ET.fromstring(xml_text)
    results: dict[str, Outcome] = {}
    for case in root.iter("testcase"):
        test_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        if case.find("failure") is not None or case.find("error") is not None:
            outcome = Outcome.FAILED
        elif case.find("skipped") is not None:
            outcome = Outcome.SKIPPED
        else:
            outcome = Outcome.PASSED
        # A test that errors in teardown appears twice; any failure wins.
        if results.get(test_id) is not Outcome.FAILED:
            results[test_id] = outcome
    return results


def classify(
    runs: list[dict[str, Outcome]], broken_runs: list[BrokenRun] | None = None
) -> FlakyReport:
    """Combine per-run results. A test absent from a run is recorded as MISSING there."""
    all_ids = sorted({test_id for run in runs for test_id in run})
    report = FlakyReport(runs=len(runs), broken_runs=list(broken_runs or []))
    for test_id in all_ids:
        outcomes = tuple(run.get(test_id, Outcome.MISSING) for run in runs)
        report.tests.append(TestHistory(test_id, outcomes))
    return report


def check_run(run: int, returncode: int, junit: Path) -> BrokenRun | None:
    """Return why a pytest run cannot be trusted, or None if it completed normally."""
    if returncode not in PYTEST_OK_EXIT_CODES:
        return BrokenRun(run, returncode, "pytest did not complete a normal test run")
    if not junit.exists():
        return BrokenRun(run, returncode, "no JUnit XML was written")
    return None


def read_run(run: int, returncode: int, junit: Path) -> tuple[dict[str, Outcome], BrokenRun | None]:
    """Parse one run's JUnit file; a missing or unreadable file makes the run broken."""
    problem = check_run(run, returncode, junit)
    if not junit.exists():
        return {}, problem
    try:
        return parse_junit(junit.read_text()), problem
    except ET.ParseError as exc:  # e.g. pytest was killed while writing the file
        return {}, problem or BrokenRun(run, returncode, f"JUnit XML is unreadable: {exc}")


def run_pytest_repeatedly(pytest_args: list[str], runs: int, out_dir: Path) -> FlakyReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Never leave (or read) run files from an earlier invocation next to this report.
    for stale in out_dir.glob("run-*.xml"):
        stale.unlink()
    results: list[dict[str, Outcome]] = []
    broken: list[BrokenRun] = []
    for i in range(1, runs + 1):
        junit = out_dir / f"run-{i}.xml"
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *pytest_args]
        cmd.append(f"--junitxml={junit}")
        print(f"[flaky] run {i}/{runs}: {' '.join(cmd)}", flush=True)
        returncode = subprocess.run(cmd, check=False).returncode
        outcomes, problem = read_run(i, returncode, junit)
        if problem:
            broken.append(problem)
        results.append(outcomes)
    return classify(results, broken)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, default=5, help="how many times to run the suite")
    parser.add_argument("--out", type=Path, default=Path("reports/flaky"), help="output dir")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER, help="arguments after --")
    args = parser.parse_args(argv)
    pytest_args = list(args.pytest_args)
    if pytest_args[:1] == ["--"]:  # drop only the separator; later "--" belong to pytest
        pytest_args = pytest_args[1:]
    if args.runs < 2:
        parser.error("--runs must be at least 2 to compare outcomes")

    report = run_pytest_repeatedly(pytest_args, args.runs, args.out)
    (args.out / "flaky-report.json").write_text(report.to_json())
    (args.out / "flaky-report.md").write_text(report.to_markdown())
    print(report.to_markdown())
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
