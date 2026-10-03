"""Framework self-tests: builders produce valid, unique data; schemas are well-formed."""

from __future__ import annotations

import pytest

from qa_suite.builders import BookBuilder, UserBuilder, unique_isbn
from qa_suite.contracts import SCHEMA_DIR, schema_errors, validator

pytestmark = pytest.mark.unit


def test_book_builder_defaults_are_valid_and_unique() -> None:
    a, b = BookBuilder().build(), BookBuilder().build()
    assert a["isbn"] != b["isbn"]
    assert a["title"] != b["title"]
    assert len(a["isbn"]) == 13
    assert a["isbn"].isdigit()


def test_builder_is_immutable_and_chainable() -> None:
    base = BookBuilder()
    custom = base.titled("Dune").by("Frank Herbert").priced(999).out_of_stock()
    assert base.title is None
    assert base.stock == 10
    payload = custom.build()
    assert payload | {"isbn": "x"} == {
        "isbn": "x",
        "title": "Dune",
        "author": "Frank Herbert",
        "price_cents": 999,
        "stock": 0,
    }


def test_user_builder_generates_unique_valid_usernames() -> None:
    names = {UserBuilder().build()["username"] for _ in range(200)}
    assert len(names) == 200
    assert all(3 <= len(n) <= 32 for n in names)


def test_unique_isbns_never_collide_with_seed_range() -> None:
    assert all(unique_isbn().startswith("979") for _ in range(50))


@pytest.mark.parametrize("path", sorted(SCHEMA_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_every_schema_is_valid_json_schema(path) -> None:
    validator(path.stem)  # raises SchemaError if the schema itself is malformed


def test_schema_errors_explain_what_is_wrong() -> None:
    errors = schema_errors({"id": "7", "isbn": "123"}, "book")
    assert any(e.startswith("id:") for e in errors)
    assert any(e.startswith("isbn:") for e in errors)
    assert any("'title' is a required property" in e for e in errors)


def test_selenium_opt_in_reads_whole_marker_tokens() -> None:
    from tests.conftest import _selects_selenium

    assert _selects_selenium("selenium")
    assert _selects_selenium("smoke or selenium")
    assert not _selects_selenium("")
    assert not _selects_selenium("not selenium")
    assert not _selects_selenium("selenium_grid")
