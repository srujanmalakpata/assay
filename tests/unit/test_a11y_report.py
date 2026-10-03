"""The axe report must surface 'incomplete' checks for manual review, not drop them."""

from __future__ import annotations

import pytest

from qa_suite.a11y import AxeResult, Violation

pytestmark = pytest.mark.unit


def test_report_lists_violations_and_checks_needing_manual_review() -> None:
    contrast = Violation(
        rule_id="color-contrast",
        impact="serious",
        help="Elements must meet minimum color contrast ratio thresholds",
        help_url="https://dequeuniversity.com/rules/axe/4.12/color-contrast",
        targets=(".hero h1",),
    )
    result = AxeResult(
        url="http://127.0.0.1/",
        axe_version="4.12.1",
        violations=(),
        passes=30,
        incomplete=(contrast,),
    )
    report = result.report()
    assert "found 0 violation(s)" in report
    assert "1 check(s) need manual review" in report
    assert "color-contrast" in report
    assert ".hero h1" in report
