"""Sign-in flows through the real HTML form."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from qa_suite.builders import CreatedUser
from qa_suite.pages import BasePage, CartPage, LoginPage

pytestmark = pytest.mark.ui


@pytest.mark.smoke
def test_home_page_loads(page: Page, base_url: str) -> None:
    home = BasePage(page, base_url).open()
    expect(page).to_have_title("Home | Bookshop")
    expect(home.heading).to_have_text("Welcome to the Bookshop")


@pytest.mark.smoke
def test_user_can_sign_in_and_out(page: Page, base_url: str, user: CreatedUser) -> None:
    login = LoginPage(page, base_url).open()
    login.login(user.username, user.password)

    expect(login.signed_in_as).to_have_text(f"Signed in as {user.username}")
    login.sign_out()
    expect(login.sign_in_link).to_be_visible()
    expect(login.signed_in_as).to_have_count(0)


@pytest.mark.parametrize(
    ("username", "password"), [("demo", "wrong-password"), ("nobody_here", "demo-password")]
)
def test_bad_credentials_show_an_error(
    page: Page, base_url: str, username: str, password: str
) -> None:
    login = LoginPage(page, base_url).open()
    with page.expect_response(re.compile(r"/login$")) as response_info:
        login.login(username, password)
    assert response_info.value.status == 401
    expect(login.error).to_have_text("Invalid username or password.")
    expect(login.username).to_have_value(username)  # the username is kept for correction
    expect(login.password).to_have_value("")  # the password is not echoed back


def test_cart_requires_login_and_returns_there_after(
    page: Page, base_url: str, user: CreatedUser
) -> None:
    page.goto(base_url + "/cart")
    expect(page).to_have_url(re.compile(r"/login\?next=/cart$"))

    LoginPage(page, base_url).login(user.username, user.password)
    expect(page).to_have_url(base_url + "/cart")
    expect(CartPage(page, base_url).empty_message).to_be_visible()


@pytest.mark.parametrize(
    "evil_next",
    # Browsers read "\\" as "/" in URLs, so "/\\evil.example" means "//evil.example".
    ["//evil.example", "https://evil.example/", "/\\evil.example"],
)
def test_login_never_redirects_off_site(
    page: Page, base_url: str, user: CreatedUser, evil_next: str
) -> None:
    LoginPage(page, base_url).open(f"/login?next={evil_next}").login(user.username, user.password)
    expect(page).to_have_url(base_url + "/")
