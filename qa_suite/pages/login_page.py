"""Sign-in page."""

from __future__ import annotations

from playwright.sync_api import Locator

from qa_suite.pages.base_page import BasePage


class LoginPage(BasePage):
    path = "/login"

    @property
    def username(self) -> Locator:
        return self.page.get_by_label("Username")

    @property
    def password(self) -> Locator:
        return self.page.get_by_label("Password")

    @property
    def error(self) -> Locator:
        return self.page.get_by_test_id("login-error")

    def login(self, username: str, password: str) -> None:
        self.username.fill(username)
        self.password.fill(password)
        self.page.get_by_role("button", name="Sign in").click()
