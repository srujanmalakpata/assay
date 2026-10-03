"""Request bodies that are valid JSON for Python's parser but not valid input (BUG-010).

Python's ``json`` module accepts ``NaN``, ``Infinity``, ``1e400`` (parsed as infinity) and
lone surrogate escapes such as ``"\\ud800"``. Pydantic rejects every one of them, but the
default 422 handler echoed the rejected value back and could not encode it, so the
error response itself became a 500.
"""

from __future__ import annotations

import pytest

from qa_suite.api_client import BookshopApi
from qa_suite.contracts import assert_matches_schema

pytestmark = [pytest.mark.api, pytest.mark.regression]

SURROGATE = "\\ud800"  # the six characters a client puts on the wire


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/api/users", '{"username": "surrogate_pw", "password": "abcdefgh%s"}'),
        ("POST", "/api/users", '{"username": "%s_user", "password": "abcdefgh1"}'),
        ("POST", "/api/auth/token", '{"username": "%s", "password": "x"}'),
        ("POST", "/api/auth/token", '{"username": "demo", "password": "%s"}'),
        (
            "POST",
            "/api/books",
            '{"isbn": "9790000000001", "title": "%s", "author": "a", "price_cents": 1, "stock": 1}',
        ),
        ("PUT", "/api/cart/items/1", '{"quantity": NaN}'),
        ("PUT", "/api/cart/items/1", '{"quantity": -Infinity}'),
        ("PUT", "/api/cart/items/1", '{"quantity": 1e400}'),
        ("POST", "/api/books", "{not json"),
    ],
)
def test_unencodable_or_invalid_bodies_get_a_422_not_a_500(
    admin_api: BookshopApi, user_api: BookshopApi, method: str, path: str, body: str
) -> None:
    client = admin_api if path == "/api/books" else user_api
    response = client.http.request(
        method,
        path,
        content=body.replace("%s", SURROGATE).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert_matches_schema(response.json(), "error")  # no "input" echoed back
