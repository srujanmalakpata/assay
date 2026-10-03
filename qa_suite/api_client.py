"""Thin, typed wrapper around httpx for the bookshop REST API.

Methods return the raw ``httpx.Response`` so tests can assert on status codes and
headers; builders and fixtures use ``.json()`` once they know the call succeeded.
"""

from __future__ import annotations

import json
from typing import Any

import httpx


class BookshopApi:
    def __init__(self, base_url: str, token: str | None = None, admin_token: str | None = None):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if admin_token:
            headers["X-Admin-Token"] = admin_token
        self.base_url = base_url
        # trust_env=False: the SUT is local, so HTTP(S)_PROXY settings must not apply.
        self.http = httpx.Client(base_url=base_url, headers=headers, timeout=15, trust_env=False)

    def close(self) -> None:
        self.http.close()

    def send_raw_json(self, method: str, path: str, payload: object) -> httpx.Response:
        """Send ``payload`` the way a lenient client would: ``json.dumps`` defaults.

        httpx's own ``json=`` refuses NaN/Infinity and lone surrogates; Python's
        ``json.dumps`` writes them as ``NaN``, ``Infinity`` and ``"\\ud800"``, which is
        what a hostile or buggy client can put on the wire.
        """
        return self.http.request(
            method,
            path,
            content=json.dumps(payload).encode("ascii"),
            headers={"Content-Type": "application/json"},
        )

    def as_user(self, token: str) -> BookshopApi:
        """A new client that authenticates every request with ``token``."""
        return BookshopApi(self.base_url, token=token)

    # --- users -----------------------------------------------------------------
    def register(self, username: str, password: str) -> httpx.Response:
        return self.http.post("/api/users", json={"username": username, "password": password})

    def token(self, username: str, password: str) -> httpx.Response:
        return self.http.post("/api/auth/token", json={"username": username, "password": password})

    # --- catalogue -------------------------------------------------------------
    def search(self, q: str = "", page: int = 1, page_size: int = 10) -> httpx.Response:
        return self.http.get("/api/books", params={"q": q, "page": page, "page_size": page_size})

    def get_book(self, book_id: int) -> httpx.Response:
        return self.http.get(f"/api/books/{book_id}")

    def create_book(self, payload: dict[str, Any]) -> httpx.Response:
        return self.http.post("/api/books", json=payload)

    # --- cart and orders -------------------------------------------------------
    def cart(self) -> httpx.Response:
        return self.http.get("/api/cart")

    def set_quantity(self, book_id: int, quantity: int) -> httpx.Response:
        return self.http.put(f"/api/cart/items/{book_id}", json={"quantity": quantity})

    def remove_item(self, book_id: int) -> httpx.Response:
        return self.http.delete(f"/api/cart/items/{book_id}")

    def checkout(self) -> httpx.Response:
        return self.http.post("/api/orders")

    def orders(self) -> httpx.Response:
        return self.http.get("/api/orders")

    def order(self, order_id: int) -> httpx.Response:
        return self.http.get(f"/api/orders/{order_id}")
