"""Cart and checkout behaviour through the REST API."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from qa_suite.api_client import BookshopApi
from qa_suite.builders import CreatedBook, UserBuilder
from qa_suite.contracts import assert_matches_schema

pytestmark = pytest.mark.api

MakeBook = Callable[..., CreatedBook]


@pytest.mark.contract
def test_new_user_has_an_empty_cart(user_api: BookshopApi) -> None:
    response = user_api.cart()
    assert response.status_code == 200
    assert_matches_schema(response.json(), "cart")
    assert response.json() == {
        "items": [],
        "subtotal_cents": 0,
        "discount_cents": 0,
        "total_cents": 0,
    }


@pytest.mark.smoke
def test_set_quantity_updates_line_and_totals(user_api: BookshopApi, make_book: MakeBook) -> None:
    book = make_book(price_cents=1250)
    cart = user_api.set_quantity(book.id, 3).json()
    assert_matches_schema(cart, "cart")
    assert cart["items"] == [
        {
            "book_id": book.id,
            "title": book.title,
            "quantity": 3,
            "unit_price_cents": 1250,
            "line_total_cents": 3750,
        }
    ]
    assert cart["total_cents"] == 3750

    cart = user_api.set_quantity(book.id, 1).json()
    assert cart["items"][0]["quantity"] == 1  # PUT replaces the quantity, it does not add


def test_zero_quantity_and_delete_both_remove_the_line(
    user_api: BookshopApi, make_book: MakeBook
) -> None:
    a, b = make_book(), make_book()
    user_api.set_quantity(a.id, 1)
    user_api.set_quantity(b.id, 2)
    assert [i["book_id"] for i in user_api.set_quantity(a.id, 0).json()["items"]] == [b.id]
    assert user_api.remove_item(b.id).json()["items"] == []


@pytest.mark.parametrize(
    ("subtotal_items", "expected_discount"),
    [
        ([(4999, 2)], 0),  # $99.98: below threshold
        ([(5000, 2)], 1000),  # exactly $100.00: 10% off
        ([(3335, 3)], 1001),  # $100.05: 1000.5 rounds half up
    ],
)
def test_discount_is_applied_from_100_dollars(
    user_api: BookshopApi,
    make_book: MakeBook,
    subtotal_items: list[tuple[int, int]],
    expected_discount: int,
) -> None:
    for price, qty in subtotal_items:
        cart = user_api.set_quantity(make_book(price_cents=price).id, qty).json()
    assert cart["discount_cents"] == expected_discount
    assert cart["total_cents"] == cart["subtotal_cents"] - expected_discount


def test_cannot_add_more_than_in_stock(user_api: BookshopApi, make_book: MakeBook) -> None:
    book = make_book(stock=2)
    response = user_api.set_quantity(book.id, 3)
    assert response.status_code == 409
    assert response.json() == {"detail": "only 2 copies in stock"}


@pytest.mark.parametrize("quantity", [-1, 100])
def test_quantity_out_of_range_is_422(
    user_api: BookshopApi, make_book: MakeBook, quantity: int
) -> None:
    assert user_api.set_quantity(make_book().id, quantity).status_code == 422


@pytest.mark.regression
@pytest.mark.parametrize("quantity", [True, False, 2.0, "2", None, [2]])
def test_quantity_must_be_a_json_integer(
    user_api: BookshopApi, make_book: MakeBook, quantity: object
) -> None:
    """JSON true used to be accepted as a quantity of 1 (lax int coercion)."""
    book = make_book()
    response = user_api.send_raw_json("PUT", f"/api/cart/items/{book.id}", {"quantity": quantity})
    assert response.status_code == 422, response.text
    assert user_api.cart().json()["items"] == []


def test_adding_unknown_book_is_404(user_api: BookshopApi) -> None:
    assert user_api.set_quantity(999_999, 1).status_code == 404


def test_checkout_with_empty_cart_is_400(user_api: BookshopApi) -> None:
    response = user_api.checkout()
    assert response.status_code == 400
    assert response.json() == {"detail": "cart is empty"}


@pytest.mark.smoke
@pytest.mark.contract
def test_checkout_creates_order_and_empties_cart(
    user_api: BookshopApi, make_book: MakeBook
) -> None:
    book = make_book(price_cents=2000, stock=5)
    user_api.set_quantity(book.id, 2)

    response = user_api.checkout()
    assert response.status_code == 201
    order = response.json()
    assert_matches_schema(order, "order")
    assert order["total_cents"] == 4000
    assert order["items"] == [
        {"book_id": book.id, "title": book.title, "quantity": 2, "unit_price_cents": 2000}
    ]
    assert user_api.cart().json()["items"] == []
    assert user_api.get_book(book.id).json()["stock"] == 3

    orders = user_api.orders()
    assert_matches_schema(orders.json(), "order_list")
    assert [o["id"] for o in orders.json()] == [order["id"]]
    assert user_api.order(order["id"]).json() == order


def test_users_cannot_read_each_others_orders(
    api: BookshopApi, user_api: BookshopApi, make_book: MakeBook
) -> None:
    user_api.set_quantity(make_book().id, 1)
    order_id = user_api.checkout().json()["id"]

    other = api.as_user(UserBuilder().create(api).token)
    try:
        assert other.order(order_id).status_code == 404
        assert other.orders().json() == []
    finally:
        other.close()


@pytest.mark.regression
def test_checkout_fails_cleanly_when_stock_ran_out(
    api: BookshopApi, user_api: BookshopApi, make_book: MakeBook
) -> None:
    last_copy = make_book(stock=1)
    user_api.set_quantity(last_copy.id, 1)

    rival = api.as_user(UserBuilder().create(api).token)
    try:
        rival.set_quantity(last_copy.id, 1)
        assert rival.checkout().status_code == 201
    finally:
        rival.close()

    response = user_api.checkout()
    assert response.status_code == 409
    assert "no longer has enough stock" in response.json()["detail"]
    assert user_api.cart().json()["items"][0]["book_id"] == last_copy.id  # cart is kept
