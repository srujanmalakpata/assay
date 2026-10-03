"""Database-state assertions: verify what was persisted, not just what the API said."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable

import httpx
import pytest

from qa_suite.api_client import BookshopApi
from qa_suite.builders import CreatedBook, CreatedUser, UserBuilder
from qa_suite.db_probe import DbProbe
from qa_suite.server import SutHandle

pytestmark = pytest.mark.db

MakeBook = Callable[..., CreatedBook]


@pytest.mark.smoke
def test_seed_data_is_deterministic(db: DbProbe) -> None:
    assert db.scalar("SELECT COUNT(*) FROM books WHERE isbn LIKE '978%'") == 20
    assert db.scalar("SELECT SUM(price_cents) FROM books WHERE isbn LIKE '978%'") == 32_480
    assert db.scalar("SELECT username FROM users WHERE id = 1") == "demo"


def test_passwords_are_stored_hashed(db: DbProbe, user: CreatedUser) -> None:
    stored = db.scalar("SELECT password_hash FROM users WHERE id = ?", (user.id,))
    assert stored.startswith("pbkdf2_sha256$")
    assert user.password not in stored


def test_cart_writes_one_row_per_book(
    db: DbProbe, user: CreatedUser, user_api: BookshopApi, make_book: MakeBook
) -> None:
    a, b = make_book(), make_book()
    user_api.set_quantity(a.id, 2)
    user_api.set_quantity(b.id, 1)
    user_api.set_quantity(a.id, 3)
    assert db.cart_rows(user.id) == [
        {"book_id": a.id, "quantity": 3},
        {"book_id": b.id, "quantity": 1},
    ]


@pytest.mark.smoke
def test_checkout_persists_order_lines_and_decrements_stock(
    db: DbProbe, user: CreatedUser, user_api: BookshopApi, make_book: MakeBook
) -> None:
    book = make_book(price_cents=6000, stock=4)
    user_api.set_quantity(book.id, 2)
    order = user_api.checkout().json()

    assert db.stock_of(book.id) == 2
    assert db.cart_rows(user.id) == []
    assert db.rows(
        "SELECT user_id, subtotal_cents, discount_cents, total_cents FROM orders WHERE id = ?",
        (order["id"],),
    ) == [
        {"user_id": user.id, "subtotal_cents": 12000, "discount_cents": 1200, "total_cents": 10800}
    ]
    assert db.rows(
        "SELECT book_id, quantity, unit_price_cents FROM order_items WHERE order_id = ?",
        (order["id"],),
    ) == [{"book_id": book.id, "quantity": 2, "unit_price_cents": 6000}]


@pytest.mark.regression
def test_failed_checkout_rolls_back_every_line(
    db: DbProbe,
    api: BookshopApi,
    user: CreatedUser,
    user_api: BookshopApi,
    make_book: MakeBook,
) -> None:
    """If one line is out of stock, no stock is taken from the *other* lines either."""
    plenty, scarce = make_book(stock=10), make_book(stock=1)
    user_api.set_quantity(plenty.id, 3)
    user_api.set_quantity(scarce.id, 1)

    rival = api.as_user(UserBuilder().create(api).token)
    try:
        rival.set_quantity(scarce.id, 1)
        assert rival.checkout().status_code == 201
    finally:
        rival.close()

    assert user_api.checkout().status_code == 409
    assert db.stock_of(plenty.id) == 10, "stock leaked from a rolled-back checkout"
    assert db.order_count(user.id) == 0
    assert len(db.cart_rows(user.id)) == 2


@pytest.mark.regression
def test_concurrent_checkouts_never_oversell(
    db: DbProbe, api: BookshopApi, make_book: MakeBook
) -> None:
    """Eight buyers race for the last two copies: exactly two orders, stock ends at 0."""
    book = make_book(stock=2)
    buyers = [api.as_user(UserBuilder().create(api).token) for _ in range(8)]
    for buyer in buyers:
        assert buyer.set_quantity(book.id, 1).status_code == 200

    statuses: list[int] = []
    start = threading.Barrier(len(buyers))

    def buy(client: BookshopApi) -> None:
        start.wait()
        statuses.append(client.checkout().status_code)

    threads = [threading.Thread(target=buy, args=(b,)) for b in buyers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for b in buyers:
        b.close()

    assert sorted(statuses) == [201, 201] + [409] * 6
    assert db.stock_of(book.id) == 0
    assert db.scalar("SELECT SUM(quantity) FROM order_items WHERE book_id = ?", (book.id,)) == 2


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def test_sessions_store_only_a_token_digest_with_an_expiry(db: DbProbe, user: CreatedUser) -> None:
    assert db.scalar("SELECT COUNT(*) FROM sessions WHERE token_hash = ?", (user.token,)) == 0
    row = db.rows(
        "SELECT user_id, expires_at > datetime('now') AS live, "
        "round((julianday(expires_at) - julianday(created_at)) * 24) AS hours "
        "FROM sessions WHERE token_hash = ?",
        (_digest(user.token),),
    )
    assert row == [{"user_id": user.id, "live": 1, "hours": 12.0}]


def test_logout_deletes_the_session_row(
    db: DbProbe, sut: SutHandle, api: BookshopApi, user: CreatedUser
) -> None:
    count_sql = "SELECT COUNT(*) FROM sessions WHERE token_hash = ?"
    assert db.scalar(count_sql, (_digest(user.token),)) == 1
    with httpx.Client(
        base_url=sut.base_url, cookies={"session": user.token}, trust_env=False
    ) as browser:
        assert browser.post("/logout").status_code == 303
    assert db.scalar(count_sql, (_digest(user.token),)) == 0

    old_token = api.as_user(user.token)
    try:
        assert old_token.cart().status_code == 401, "token still accepted after logout"
    finally:
        old_token.close()


@pytest.mark.regression
def test_concurrent_adds_to_the_same_cart_are_not_lost(
    db: DbProbe, sut: SutHandle, user: CreatedUser, make_book: MakeBook
) -> None:
    """BUG-008: eight simultaneous "add 1" requests used to leave a quantity of 1 or 2."""
    book = make_book(stock=50)
    start = threading.Barrier(8)
    statuses: list[int] = []

    def add_one() -> None:
        with httpx.Client(
            base_url=sut.base_url, cookies={"session": user.token}, trust_env=False
        ) as browser:
            start.wait()
            response = browser.post("/cart/add", data={"book_id": book.id, "quantity": 1})
            statuses.append(response.status_code)

    threads = [threading.Thread(target=add_one) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert statuses == [303] * 8
    assert db.cart_rows(user.id) == [{"book_id": book.id, "quantity": 8}]
