"""Selenium WebDriver fixture (Chrome, headless) with a screenshot on failure.

Selenium Manager resolves a chromedriver that matches the installed browser. Set
CHROME_BINARY to drive a specific Chrome/Chromium build (for example Playwright's).
If no matching driver can be obtained the tests are skipped with the reason, so a
missing driver is reported as NOT RUN rather than as a pass. In CI, SELENIUM_REQUIRED=1
turns that skip into a failure, so the job cannot go green without running anything.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.common.exceptions import WebDriverException

ARTIFACTS = Path(__file__).resolve().parents[2] / "test-results" / "selenium"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    report = yield
    setattr(item, f"rep_{report.when}", report)
    return report


@pytest.fixture(scope="session")
def chrome_options() -> webdriver.ChromeOptions:
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1280,900")
    if binary := os.environ.get("CHROME_BINARY"):
        options.binary_location = binary
    return options


@pytest.fixture
def driver(
    request: pytest.FixtureRequest, chrome_options: webdriver.ChromeOptions
) -> Iterator[webdriver.Chrome]:
    try:
        drv = webdriver.Chrome(options=chrome_options)
    except WebDriverException as exc:
        reason = f"no usable chromedriver for this browser ({exc.msg})"
        if os.environ.get("SELENIUM_REQUIRED") == "1":
            pytest.fail(f"SELENIUM_REQUIRED=1 but {reason}")
        pytest.skip(f"NOT RUN: {reason}")
    try:
        yield drv
        report = getattr(request.node, "rep_call", None)
        if report is not None and report.failed:
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            drv.save_screenshot(str(ARTIFACTS / f"{request.node.name}.png"))
    finally:
        drv.quit()
