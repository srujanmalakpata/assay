"""End-to-end shopping journeys: browse, add to cart, edit cart, check out."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect

from qa_suite.api_client import BookshopApi
from qa_suite.builders import CreatedBook, CreatedUser, UserBuilder
from qa_suite.db_probe import DbProbe
from qa_suite.pages import BookPage, CartPage, OrderPage
from qa_suite.server import SutHandle

pytestmark = pytest.mark.ui

MakeBook = Callable[..., CreatedBook]


@pytest.mark.smoke
def test_add_to_cart_and_check_out(
    signed_in_page: Page,
    base_url: str,
    make_book: MakeBook,
    api: BookshopApi,
    user_api: BookshopApi,
    user: CreatedUser,
    sut: SutHandle,
    request: pytest.FixtureRequest,
) -> None:
    book = make_book(price_cents=1250, stock=5)

    BookPage(signed_in_page, base_url).open_book(book.id).add_to_cart(quantity=2)

    cart = CartPage(signed_in_page, base_url)
    expect(cart.added_notice).to_have_text(f'Added "{book.title}" to your cart.')
    expect(cart.rows).to_have_count(1)
    expect(cart.total).to_have_text("$25.00")

    cart.checkout()
    order = OrderPage(signed_in_page, base_url)
    expect(order.confirmation).to_contain_text("is confirmed")
    expect(order.total).to_have_text("$25.00")

    # The UI said it worked; check the API (always) and the database (when reachable).
    assert api.get_book(book.id).json()["stock"] == 3
    assert len(user_api.orders().json()) == 1
    if sut.db_path is not None:  # requested lazily, so the journey still runs without it
        db: DbProbe = request.getfixturevalue("db")
        assert db.stock_of(book.id) == 3
        assert db.order_count(user.id) == 1


def test_editing_quantities_updates_totals_and_discount(
    signed_in_page: Page, base_url: str, make_book: MakeBook
) -> None:
    book = make_book(price_cents=2500, stock=10)
    BookPage(signed_in_page, base_url).open_book(book.id).add_to_cart(quantity=1)
    cart = CartPage(signed_in_page, base_url)
    expect(cart.total).to_have_text("$25.00")

    cart.set_quantity(book.id, 4)  # $100.00 reaches the discount threshold
    expect(cart.subtotal).to_have_text("$100.00")
    expect(cart.discount).to_have_text("$10.00")
    expect(cart.total).to_have_text("$90.00")

    cart.set_quantity(book.id, 0)
    expect(cart.empty_message).to_be_visible()


def test_adding_more_than_stock_shows_error(
    signed_in_page: Page, base_url: str, make_book: MakeBook
) -> None:
    book = make_book(stock=2)
    page = BookPage(signed_in_page, base_url).open_book(book.id)
    page.add_to_cart(quantity=3)
    expect(page.alert).to_have_text("only 2 copies in stock")


def test_sold_out_book_has_no_add_button(
    signed_in_page: Page, base_url: str, make_book: MakeBook
) -> None:
    book = make_book(stock=0)
    page = BookPage(signed_in_page, base_url).open_book(book.id)
    expect(page.sold_out).to_be_visible()
    expect(page.add_button).to_have_count(0)


@pytest.mark.regression
def test_checkout_reports_stock_taken_by_another_customer(
    signed_in_page: Page, base_url: str, make_book: MakeBook, api: BookshopApi
) -> None:
    book = make_book(stock=1)
    BookPage(signed_in_page, base_url).open_book(book.id).add_to_cart()

    rival = api.as_user(UserBuilder().create(api).token)
    try:
        rival.set_quantity(book.id, 1)
        assert rival.checkout().status_code == 201
    finally:
        rival.close()

    cart = CartPage(signed_in_page, base_url)
    cart.checkout()
    expect(cart.error).to_have_text(f"'{book.title}' no longer has enough stock")
    expect(cart.rows).to_have_count(1)
