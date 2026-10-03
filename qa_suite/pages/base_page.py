"""Page Object Model base class for Playwright UI tests."""

from __future__ import annotations

from typing import Self

from playwright.sync_api import Locator, Page


class BasePage:
    """Shared navigation and header behaviour; subclasses set ``path``."""

    path = "/"

    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url.rstrip("/")

    def open(self, path: str | None = None) -> Self:
        self.page.goto(self.base_url + (path or self.path))
        return self

    # Header (present on every page) ------------------------------------------------
    @property
    def signed_in_as(self) -> Locator:
        return self.page.get_by_test_id("nav-user")

    @property
    def sign_in_link(self) -> Locator:
        return self.page.get_by_test_id("nav-login")

    def sign_out(self) -> None:
        self.page.get_by_test_id("logout").click()

    def go_to_cart(self) -> None:
        self.page.get_by_test_id("nav-cart").click()

    @property
    def heading(self) -> Locator:
        return self.page.get_by_role("heading", level=1)

    @property
    def alert(self) -> Locator:
        return self.page.get_by_role("alert")

    @property
    def skip_link(self) -> Locator:
        return self.page.get_by_role("link", name="Skip to main content")
