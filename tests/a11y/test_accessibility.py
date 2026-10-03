"""WCAG 2.1 A/AA scans with axe-core on every page template, in realistic states."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

from qa_suite.a11y import scan
from qa_suite.builders import CreatedBook
from qa_suite.pages import BasePage, BookPage, CartPage, LoginPage, OrderPage

pytestmark = pytest.mark.a11y

MakeBook = Callable[..., CreatedBook]


def assert_accessible(page: Page) -> None:
    result = scan(page)
    if result.incomplete:
        print(result.report())  # captured into the HTML report for manual review
    assert not result.violations, result.report()


@pytest.mark.smoke
@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/books",
        "/books?q=austen",
        "/books?q=no-such-thing",
        "/books?page=abc",
        "/books/1",
        "/books/abc",
        "/login",
        "/nope",
    ],
)
def test_public_pages_have_no_axe_violations(page: Page, base_url: str, path: str) -> None:
    page.goto(base_url + path)
    assert_accessible(page)


def test_login_error_state_is_accessible(page: Page, base_url: str) -> None:
    login = LoginPage(page, base_url).open()
    login.login("demo", "wrong-password")
    login.alert.wait_for()
    assert_accessible(page)


def test_cart_and_order_pages_are_accessible(
    signed_in_page: Page, base_url: str, make_book: MakeBook
) -> None:
    page = signed_in_page
    page.goto(f"{base_url}/cart")
    assert_accessible(page)  # empty cart

    for book in (make_book(), make_book(stock=0)):
        page.goto(f"{base_url}/books/{book.id}")
        assert_accessible(page)  # in-stock and sold-out variants

    BookPage(page, base_url).open_book(make_book().id).add_to_cart()
    cart = CartPage(page, base_url)
    cart.added_notice.wait_for()
    assert_accessible(page)  # cart with items and a status message

    cart.checkout()
    OrderPage(page, base_url).confirmation.wait_for()
    assert_accessible(page)  # order confirmation


def test_keyboard_user_can_skip_to_main_content(page: Page, base_url: str) -> None:
    skip = BasePage(page, base_url).open().skip_link
    page.keyboard.press("Tab")
    assert skip.evaluate("el => el === document.activeElement")
    page.keyboard.press("Enter")
    assert page.url.endswith("#main")
    # The next Tab must start inside <main>, i.e. focus really moved past the navigation.
    page.keyboard.press("Tab")
    assert page.evaluate("() => document.getElementById('main').contains(document.activeElement)")
