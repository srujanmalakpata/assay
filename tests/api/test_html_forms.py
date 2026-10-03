"""Server-side validation of the HTML endpoints, posted directly (no browser).

A browser's ``min``/``max`` attributes are only a convenience: anyone can POST the form
with other values, so these tests bypass the UI and send crafted requests over HTTP.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import httpx
import pytest

from qa_suite.api_client import BookshopApi
from qa_suite.builders import CreatedBook, CreatedUser
from qa_suite.server import SutHandle

pytestmark = [pytest.mark.api, pytest.mark.regression]

MakeBook = Callable[..., CreatedBook]


@pytest.fixture
def browser_session(sut: SutHandle, user: CreatedUser) -> Iterator[httpx.Client]:
    """An HTTP client that sends the session cookie and HTML Accept header like a browser."""
    with httpx.Client(
        base_url=sut.base_url,
        cookies={"session": user.token},
        headers={"Accept": "text/html"},
        timeout=15,
        trust_env=False,
    ) as client:
        yield client


@pytest.mark.parametrize("quantity", [-2, 0, 100])
def test_cart_add_rejects_out_of_range_quantities(
    browser_session: httpx.Client, user_api: BookshopApi, make_book: MakeBook, quantity: int
) -> None:
    """BUG-007: a negative 'add' used to remove copies from the cart."""
    book = make_book(stock=50)
    assert (
        browser_session.post("/cart/add", data={"book_id": book.id, "quantity": 3}).status_code
        == 303
    )

    response = browser_session.post("/cart/add", data={"book_id": book.id, "quantity": quantity})

    assert response.status_code == 400
    assert "quantity must be between 1 and 99" in response.text
    assert [(i["book_id"], i["quantity"]) for i in user_api.cart().json()["items"]] == [
        (book.id, 3)
    ], "an invalid add changed the cart"


def test_cart_add_beyond_stock_is_a_409_conflict(
    browser_session: httpx.Client, make_book: MakeBook
) -> None:
    book = make_book(stock=2)
    response = browser_session.post("/cart/add", data={"book_id": book.id, "quantity": 3})
    assert response.status_code == 409
    assert "only 2 copies in stock" in response.text


@pytest.mark.parametrize("book_id", [999_999_999, 10**20])
def test_cart_forms_report_unknown_books_as_404(
    browser_session: httpx.Client, book_id: int
) -> None:
    for path in ("/cart/add", "/cart/update"):
        response = browser_session.post(path, data={"book_id": book_id, "quantity": 1})
        assert response.status_code == 404, path
        assert "Page not found" in response.text


def test_cart_update_with_an_invalid_quantity_is_a_400(
    browser_session: httpx.Client, make_book: MakeBook
) -> None:
    book = make_book()
    response = browser_session.post("/cart/update", data={"book_id": book.id, "quantity": -1})
    assert response.status_code == 400


def test_html_search_rejects_overlong_text_like_the_api(
    browser_session: httpx.Client, api: BookshopApi
) -> None:
    """The page used to cut the text to 100 characters silently; the API returned 422."""
    too_long = "x" * 101
    page = browser_session.get("/books", params={"q": too_long})
    assert page.status_code == 400
    assert "at most 100 characters" in page.text
    assert api.search(too_long).status_code == 422
    assert browser_session.get("/books", params={"q": "x" * 100}).status_code == 200


@pytest.mark.parametrize("page_number", [0, -3, 10_001, 10**20])
def test_html_search_rejects_out_of_range_pages(
    browser_session: httpx.Client, page_number: int
) -> None:
    response = browser_session.get("/books", params={"page": page_number})
    assert response.status_code == 400
    assert "page must be between 1 and 10000" in response.text
