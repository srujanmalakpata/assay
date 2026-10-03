"""Catalogue search, pagination and book lookup."""

from __future__ import annotations

import pytest

from qa_suite.api_client import BookshopApi
from qa_suite.builders import BookBuilder, unique_suffix
from qa_suite.contracts import assert_matches_schema

pytestmark = pytest.mark.api


@pytest.mark.smoke
@pytest.mark.contract
def test_search_seeded_author_returns_both_books(api: BookshopApi) -> None:
    response = api.search("austen")
    assert response.status_code == 200
    body = response.json()
    assert_matches_schema(body, "book_page")
    assert body["total"] == 2
    assert [b["title"] for b in body["items"]] == ["Emma", "Pride and Prejudice"]


@pytest.mark.parametrize("query", ["DICKENS", "dickens", "  Dickens  "])
def test_search_is_case_insensitive_and_trims_whitespace(api: BookshopApi, query: str) -> None:
    titles = [b["title"] for b in api.search(query).json()["items"]]
    assert titles == ["A Tale of Two Cities", "Great Expectations"]


def test_search_matches_title_as_well_as_author(api: BookshopApi) -> None:
    titles = [b["title"] for b in api.search("odyssey").json()["items"]]
    assert titles == ["The Odyssey"]


def test_search_with_no_match_returns_empty_page(api: BookshopApi) -> None:
    body = api.search(f"no-such-book-{unique_suffix()}").json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.regression
@pytest.mark.parametrize("wildcard", ["%", "_", "%%", "\\"])
def test_like_wildcards_are_matched_literally(api: BookshopApi, wildcard: str) -> None:
    """BUG-001: '%' used to match every book because it reached SQL LIKE unescaped."""
    body = api.search(wildcard).json()
    for book in body["items"]:
        assert wildcard in book["title"] or wildcard in book["author"]


@pytest.mark.regression
def test_titles_containing_wildcards_are_still_findable(
    api: BookshopApi, admin_api: BookshopApi
) -> None:
    title = f"100% Cotton_{unique_suffix()}"
    created = BookBuilder().titled(title).create(admin_api)
    assert [b["id"] for b in api.search(title).json()["items"]] == [created.id]


@pytest.mark.regression
def test_new_book_is_searchable(api: BookshopApi, admin_api: BookshopApi) -> None:
    title = f"Zebra Patterns {unique_suffix()}"
    created = BookBuilder().titled(title).create(admin_api)
    body = api.search(title).json()
    assert [b["id"] for b in body["items"]] == [created.id]


@pytest.mark.contract
def test_get_book_by_id(api: BookshopApi) -> None:
    response = api.get_book(1)
    assert response.status_code == 200
    assert_matches_schema(response.json(), "book")
    assert response.json()["title"] == "Pride and Prejudice"


def test_unknown_book_is_404(api: BookshopApi) -> None:
    response = api.get_book(999_999)
    assert response.status_code == 404
    assert_matches_schema(response.json(), "error")


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"page_size": 0}, {"page_size": 51}, {"page": "abc"}, {"q": "x" * 101}],
)
def test_invalid_search_parameters_are_422(api: BookshopApi, params: dict[str, object]) -> None:
    response = api.http.get("/api/books", params=params)
    assert response.status_code == 422
    assert_matches_schema(response.json(), "error")


def test_create_book_rejects_duplicate_isbn(admin_api: BookshopApi) -> None:
    payload = BookBuilder().build()
    assert admin_api.create_book(payload).status_code == 201
    response = admin_api.create_book({**payload, "title": "Another title"})
    assert response.status_code == 409


@pytest.mark.parametrize(
    "override",
    [{"isbn": "123"}, {"price_cents": -1}, {"stock": -5}, {"title": ""}],
)
def test_create_book_validation(admin_api: BookshopApi, override: dict[str, object]) -> None:
    response = admin_api.create_book({**BookBuilder().build(), **override})
    assert response.status_code == 422


@pytest.mark.regression
@pytest.mark.parametrize(
    ("path", "html_status"), [("/no-such-page", 404), ("/books/abc", 400), ("/books?page=x", 400)]
)
def test_browsers_get_html_errors_but_api_clients_get_json(
    api: BookshopApi, path: str, html_status: int
) -> None:
    """BUG-003 / BUG-004: framework errors used to reach browsers as raw JSON."""
    as_browser = api.http.get(path, headers={"Accept": "text/html,application/xhtml+xml"})
    assert as_browser.status_code == html_status
    assert as_browser.headers["content-type"].startswith("text/html")
    assert '<html lang="en">' in as_browser.text

    as_api = api.http.get(path, headers={"Accept": "application/json"})
    assert as_api.headers["content-type"] == "application/json"
    assert_matches_schema(as_api.json(), "error")


def test_unknown_api_route_is_json_even_for_browsers(api: BookshopApi) -> None:
    response = api.http.get("/api/nope", headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
