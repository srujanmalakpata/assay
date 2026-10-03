"""Searching and browsing the catalogue in the browser."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from qa_suite.api_client import BookshopApi
from qa_suite.builders import BookBuilder, unique_suffix
from qa_suite.pages import BookPage, SearchPage

pytestmark = pytest.mark.ui


@pytest.mark.smoke
def test_search_by_author(page: Page, base_url: str) -> None:
    search = SearchPage(page, base_url).open().search("dickens")
    expect(search.result_count).to_have_text('2 results for "dickens"')
    assert search.titles() == ["A Tale of Two Cities", "Great Expectations"]


def test_search_without_matches(page: Page, base_url: str) -> None:
    search = SearchPage(page, base_url).open().search("zzzz-no-such-book")
    expect(search.result_count).to_have_text('0 results for "zzzz-no-such-book"')
    expect(search.no_results).to_be_visible()


@pytest.mark.regression
def test_pagination_walks_through_every_result(
    page: Page, base_url: str, admin_api: BookshopApi
) -> None:
    tag = f"uipage{unique_suffix()}"
    expected = [f"{tag} part {i:02d}" for i in range(12)]  # 12 results = 2 pages of 10
    for title in expected:
        BookBuilder().titled(title).create(admin_api)

    search = SearchPage(page, base_url).open().search(tag)
    expect(search.result_count).to_have_text(f'12 results for "{tag}"')
    titles = search.titles()
    search.next_page()
    expect(search.page_indicator(2, 2)).to_be_visible()
    titles += search.titles()
    assert titles == expected


def test_open_book_from_results(page: Page, base_url: str) -> None:
    SearchPage(page, base_url).open().search("moby").open_book("Moby-Dick")
    book = BookPage(page, base_url)
    expect(book.title).to_have_text("Moby-Dick")
    expect(book.price).to_have_text("$15.99")


def test_unknown_book_shows_404_page(page: Page, base_url: str) -> None:
    response = page.goto(base_url + "/books/999999")
    assert response is not None
    assert response.status == 404
    expect(BookPage(page, base_url).heading).to_have_text("Page not found")
