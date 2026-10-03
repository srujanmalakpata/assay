"""Unit tests for the flaky-test detector's parsing and classification logic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qa_suite.flaky import (
    BrokenRun,
    Outcome,
    Verdict,
    check_run,
    classify,
    main,
    parse_junit,
    read_run,
    run_pytest_repeatedly,
)

pytestmark = pytest.mark.unit

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4">
  <testcase classname="tests.test_a" name="test_pass" time="0.01"/>
  <testcase classname="tests.test_a" name="test_fail" time="0.01">
    <failure message="assert 1 == 2">trace</failure>
  </testcase>
  <testcase classname="tests.test_a" name="test_skip" time="0.0">
    <skipped message="not today"/>
  </testcase>
  <testcase classname="tests.test_a" name="test_teardown" time="0.01"/>
  <testcase classname="tests.test_a" name="test_teardown" time="0.01">
    <error message="teardown blew up"/>
  </testcase>
</testsuite></testsuites>
"""


def test_parse_junit_maps_each_outcome() -> None:
    results = parse_junit(JUNIT)
    assert results == {
        "tests.test_a::test_pass": Outcome.PASSED,
        "tests.test_a::test_fail": Outcome.FAILED,
        "tests.test_a::test_skip": Outcome.SKIPPED,
        # A setup/teardown error is reported as a second <testcase>: it must count as a failure.
        "tests.test_a::test_teardown": Outcome.FAILED,
    }


def test_classify_separates_flaky_from_real_failures() -> None:
    p, f, s = Outcome.PASSED, Outcome.FAILED, Outcome.SKIPPED
    runs = [
        {"stable": p, "broken": f, "flaky": p, "skip": s},
        {"stable": p, "broken": f, "flaky": f, "skip": s},
        {"stable": p, "broken": f, "flaky": p, "skip": s},
    ]
    report = classify(runs)
    verdicts = {t.test_id: t.verdict for t in report.tests}
    assert verdicts == {
        "stable": Verdict.STABLE_PASS,
        "broken": Verdict.STABLE_FAIL,
        "flaky": Verdict.FLAKY,
        "skip": Verdict.SKIPPED,
    }
    assert report.exit_code == 1


def test_a_test_missing_from_a_run_is_recorded_as_missing_never_passed() -> None:
    # e.g. the worker crashed before the test reported: that must not look like a pass.
    report = classify([{"t": Outcome.PASSED}, {}])
    assert report.tests[0].outcomes == (Outcome.PASSED, Outcome.MISSING)
    assert report.tests[0].verdict is Verdict.FLAKY
    assert report.exit_code == 1


def test_a_collection_error_in_one_run_is_not_reported_as_three_failures() -> None:
    error_once = [{"tests/test_x.py": Outcome.FAILED}, {}, {}]
    report = classify(error_once)
    assert report.tests[0].outcomes == (Outcome.FAILED, Outcome.MISSING, Outcome.MISSING)
    assert report.tests[0].verdict is Verdict.FLAKY
    assert "failed missing missing" in report.to_markdown()


def test_an_empty_report_is_never_green() -> None:
    report = classify([{}, {}])
    assert report.exit_code == 2
    assert "nothing was verified" in report.to_markdown()


@pytest.mark.parametrize(
    ("returncode", "junit_written", "broken"),
    [(0, True, False), (1, True, False), (1, False, True), (2, True, True), (4, False, True)],
)
def test_check_run_flags_runs_that_did_not_complete(
    tmp_path: Path, returncode: int, junit_written: bool, broken: bool
) -> None:
    junit = tmp_path / "run-1.xml"
    if junit_written:
        junit.write_text(JUNIT)
    assert (check_run(1, returncode, junit) is not None) is broken


def test_a_broken_run_fails_the_report_even_if_every_test_passed() -> None:
    report = classify(
        [{"a": Outcome.PASSED}, {"a": Outcome.PASSED}],
        [BrokenRun(run=2, returncode=3, reason="pytest did not complete a normal test run")],
    )
    assert report.exit_code == 2
    assert "| 2 | 3 |" in report.to_markdown()
    assert json.loads(report.to_json())["broken_runs"][0]["returncode"] == 3


@pytest.mark.parametrize(
    "pytest_args",
    [
        ["--no-such-option"],  # usage error: pytest exits 4 and writes no JUnit file
        ["tests/unit/test_pricing.py", "-k", "no_such_test_name"],  # exit 5: nothing collected
    ],
)
def test_detector_exits_non_zero_when_pytest_itself_fails(
    tmp_path: Path, pytest_args: list[str]
) -> None:
    assert main(["--runs", "2", "--out", str(tmp_path), "--", *pytest_args]) == 2


def test_all_green_exits_zero_and_serialises() -> None:
    report = classify([{"a": Outcome.PASSED}, {"a": Outcome.PASSED}])
    assert report.exit_code == 0
    data = json.loads(report.to_json())
    assert data["summary"]["stable-pass"] == 1
    assert data["tests"][0]["verdict"] == "stable-pass"
    assert "Flaky-test report (2 runs)" in report.to_markdown()


def test_a_test_that_is_sometimes_skipped_is_flaky_not_stable() -> None:
    # A nondeterministic skip hides whether the test works, so it must not read as green.
    p, s = Outcome.PASSED, Outcome.SKIPPED
    report = classify([{"t": p}, {"t": s}, {"t": p}])
    assert report.tests[0].verdict is Verdict.FLAKY
    assert report.exit_code == 1


def test_an_unreadable_junit_file_is_a_broken_run_not_a_crash(tmp_path: Path) -> None:
    junit = tmp_path / "run-1.xml"
    junit.write_text(JUNIT[:200])  # truncated, as if pytest was killed mid-write
    outcomes, problem = read_run(1, 1, junit)
    assert outcomes == {}
    assert problem is not None
    assert "unreadable" in problem.reason


def test_stale_run_files_from_an_earlier_invocation_are_removed(tmp_path: Path) -> None:
    stale = tmp_path / "run-3.xml"
    stale.write_text(JUNIT)
    report = run_pytest_repeatedly(["tests/unit/test_pricing.py", "-k", "no_such"], 2, tmp_path)
    assert not stale.exists()
    assert sorted(p.name for p in tmp_path.glob("run-*.xml")) == ["run-1.xml", "run-2.xml"]
    assert report.exit_code == 2  # nothing collected


def test_only_the_leading_separator_is_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    def fake_run(args: list[str], runs: int, out_dir: Path) -> object:
        seen.append(args)
        return classify([{"a": Outcome.PASSED}, {"a": Outcome.PASSED}])

    monkeypatch.setattr("qa_suite.flaky.run_pytest_repeatedly", fake_run)
    assert main(["--runs", "2", "--out", str(tmp_path), "--", "-k", "x", "--", "y"]) == 0
    assert seen == [["-k", "x", "--", "y"]]
