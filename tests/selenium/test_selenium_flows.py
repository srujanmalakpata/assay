"""The same critical journeys as the Playwright suite, driven by Selenium WebDriver.

Run with:  pytest -m selenium
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from selenium.webdriver.remote.webdriver import WebDriver

from qa_suite.builders import CreatedBook, CreatedUser
from qa_suite.selenium_pages import SeleniumBookPage, SeleniumLoginPage, SeleniumSearchPage

pytestmark = pytest.mark.selenium


def test_login_with_selenium(driver: WebDriver, base_url: str, user: CreatedUser) -> None:
    page = SeleniumLoginPage(driver, base_url)
    page.login(user.username, user.password)
    assert page.signed_in_text() == f"Signed in as {user.username}"


def test_search_with_selenium(driver: WebDriver, base_url: str) -> None:
    page = SeleniumSearchPage(driver, base_url)
    page.search("tolstoy")
    assert page.titles() == ["Anna Karenina", "War and Peace"]


def test_add_to_cart_with_selenium(
    driver: WebDriver,
    base_url: str,
    user: CreatedUser,
    make_book: Callable[..., CreatedBook],
) -> None:
    book = make_book(price_cents=999, stock=3)
    SeleniumLoginPage(driver, base_url).login(user.username, user.password)

    page = SeleniumBookPage(driver, base_url)
    page.add_to_cart(book.id, quantity=3)
    assert page.added_notice() == f'Added "{book.title}" to your cart.'
    assert page.cart_total() == "$29.97"
