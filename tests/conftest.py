"""Shared fixtures: one SUT per test session (per xdist worker), API clients, builders.

Set SUT_BASE_URL to run the suite against an already running server (for example the
docker-compose stack). Set SUT_DB_PATH as well to enable the database-state tests;
without it they are skipped with a clear reason rather than silently passing.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page

from qa_suite.api_client import BookshopApi
from qa_suite.builders import BookBuilder, CreatedBook, CreatedUser, UserBuilder
from qa_suite.db_probe import DbProbe
from qa_suite.server import SutHandle, SutServer, wait_until_healthy

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def sut(tmp_path_factory: pytest.TempPathFactory, worker_id: str) -> Iterator[SutHandle]:
    external = os.environ.get("SUT_BASE_URL")
    admin_token = os.environ.get("BOOKSHOP_ADMIN_TOKEN", "dev-admin-token")
    if external:
        wait_until_healthy(external.rstrip("/"))
        db_path = os.environ.get("SUT_DB_PATH")
        yield SutHandle(external.rstrip("/"), Path(db_path) if db_path else None, admin_token)
        return
    workdir = tmp_path_factory.mktemp(f"sut-{worker_id}")
    log_path = PROJECT_ROOT / "test-results" / f"sut-{worker_id}.log"
    with SutServer(workdir / "bookshop.sqlite3", log_path, admin_token) as handle:
        yield handle


@pytest.fixture(scope="session")
def base_url(sut: SutHandle) -> str:
    """Overrides pytest-base-url so Playwright's page.goto('/x') targets the SUT."""
    return sut.base_url


@pytest.fixture(scope="session")
def api(sut: SutHandle) -> Iterator[BookshopApi]:
    client = BookshopApi(sut.base_url)
    yield client
    client.close()


@pytest.fixture(scope="session")
def admin_api(sut: SutHandle) -> Iterator[BookshopApi]:
    client = BookshopApi(sut.base_url, admin_token=sut.admin_token)
    yield client
    client.close()


@pytest.fixture(scope="session")
def db(sut: SutHandle) -> DbProbe:
    if sut.db_path is None:
        pytest.skip("database not reachable: set SUT_DB_PATH when using SUT_BASE_URL")
    return DbProbe(sut.db_path)


@pytest.fixture
def user(api: BookshopApi) -> CreatedUser:
    return UserBuilder().create(api)


@pytest.fixture
def user_api(sut: SutHandle, user: CreatedUser) -> Iterator[BookshopApi]:
    client = BookshopApi(sut.base_url, token=user.token)
    yield client
    client.close()


@pytest.fixture
def make_book(admin_api: BookshopApi) -> Callable[..., CreatedBook]:
    """Factory fixture: make_book(price_cents=..., stock=..., title=...)."""

    def _make(**overrides: object) -> CreatedBook:
        return replace(BookBuilder(), **overrides).create(admin_api)

    return _make


@pytest.fixture
def signed_in_page(page: Page, base_url: str, user: CreatedUser) -> Page:
    """A Playwright page already signed in as a fresh user.

    The UI shares sessions with the API, so the API token is set as the session cookie
    directly. Logging in through the form is covered by tests/ui/test_login.py.
    """
    host = urlparse(base_url).hostname
    page.context.add_cookies(
        [{"name": "session", "value": user.token, "domain": host, "path": "/"}]
    )
    return page


def _selects_selenium(markexpr: str) -> bool:
    """True if the -m expression names the selenium marker other than as `not selenium`.

    Whole tokens are compared, so a marker such as `selenium_grid` does not opt in.
    """
    tokens = re.findall(r"\w+", markexpr)
    return any(
        token == "selenium" and (i == 0 or tokens[i - 1] != "not") for i, token in enumerate(tokens)
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Selenium tests are opt-in (they may download a driver): run them with -m selenium."""
    if _selects_selenium(config.option.markexpr or ""):
        return
    skip = pytest.mark.skip(reason="Selenium suite is opt-in: run with `-m selenium`")
    for item in items:
        if "selenium" in item.keywords:
            item.add_marker(skip)
