"""Test-data builders.

Each test creates the data it needs through the public API instead of relying on
shared seed rows it might mutate. Builders give every record a unique key (username,
ISBN) so tests stay independent under pytest-xdist and against a long-lived server.

    book = BookBuilder().titled("Dune").priced(1999).with_stock(1).create(admin_api)
    user = UserBuilder().create(api)
"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass, replace
from typing import Any

from qa_suite.api_client import BookshopApi

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Short unique string: process-unique counter plus random bits (unique across workers)."""
    return f"{next(_counter)}{uuid.uuid4().hex[:8]}"


def unique_isbn() -> str:
    """A 13-digit ISBN-like string in the 979 range, which the seed data never uses."""
    return "979" + str(uuid.uuid4().int % 10**10).zfill(10)


class BuilderError(RuntimeError):
    """Raised when the API refuses to create test data.

    It is deliberately not an AssertionError, so a report shows a setup problem apart
    from a failed product assertion. Raised inside a fixture (``user``, ``user_api``),
    pytest reports the test as ERROR; raised from a test body (``make_book(...)``), the
    test is FAILED with ``BuilderError`` and the API's response in the message.
    """


@dataclass(frozen=True)
class CreatedUser:
    id: int
    username: str
    password: str
    token: str


@dataclass(frozen=True)
class CreatedBook:
    id: int
    isbn: str
    title: str
    author: str
    price_cents: int
    stock: int


@dataclass(frozen=True)
class UserBuilder:
    username: str | None = None
    password: str = "correct-horse-battery"

    def named(self, username: str) -> UserBuilder:
        return replace(self, username=username)

    def with_password(self, password: str) -> UserBuilder:
        return replace(self, password=password)

    def build(self) -> dict[str, str]:
        return {"username": self.username or f"user_{unique_suffix()}", "password": self.password}

    def create(self, api: BookshopApi) -> CreatedUser:
        payload = self.build()
        created = api.register(**payload)
        if created.status_code != 201:
            raise BuilderError(f"could not create user: {created.status_code} {created.text}")
        token = api.token(**payload)
        if token.status_code != 200:
            raise BuilderError(f"could not log in new user: {token.status_code} {token.text}")
        return CreatedUser(
            id=created.json()["id"],
            username=payload["username"],
            password=payload["password"],
            token=token.json()["access_token"],
        )


@dataclass(frozen=True)
class BookBuilder:
    title: str | None = None
    author: str = "Test Author"
    price_cents: int = 1500
    stock: int = 10
    isbn: str | None = None

    def titled(self, title: str) -> BookBuilder:
        return replace(self, title=title)

    def by(self, author: str) -> BookBuilder:
        return replace(self, author=author)

    def priced(self, price_cents: int) -> BookBuilder:
        return replace(self, price_cents=price_cents)

    def with_stock(self, stock: int) -> BookBuilder:
        return replace(self, stock=stock)

    def out_of_stock(self) -> BookBuilder:
        return self.with_stock(0)

    def build(self) -> dict[str, Any]:
        return {
            "isbn": self.isbn or unique_isbn(),
            "title": self.title or f"Test Book {unique_suffix()}",
            "author": self.author,
            "price_cents": self.price_cents,
            "stock": self.stock,
        }

    def create(self, admin_api: BookshopApi) -> CreatedBook:
        response = admin_api.create_book(self.build())
        if response.status_code != 201:
            raise BuilderError(f"could not create book: {response.status_code} {response.text}")
        return CreatedBook(**response.json())
