"""Book search / results page."""

from __future__ import annotations

from playwright.sync_api import Locator

from qa_suite.pages.base_page import BasePage


class SearchPage(BasePage):
    path = "/books"

    def search(self, query: str) -> SearchPage:
        self.page.get_by_label("Search by title or author").fill(query)
        self.page.get_by_test_id("search-submit").click()
        return self

    @property
    def result_count(self) -> Locator:
        return self.page.get_by_test_id("result-count")

    @property
    def rows(self) -> Locator:
        return self.page.get_by_test_id("result-row")

    @property
    def no_results(self) -> Locator:
        return self.page.get_by_text("No books matched your search.")

    def page_indicator(self, page: int, pages: int) -> Locator:
        return self.page.get_by_text(f"Page {page} of {pages}")

    def titles(self) -> list[str]:
        return self.rows.locator("td:first-child").all_inner_texts()

    def next_page(self) -> SearchPage:
        self.page.get_by_test_id("next-page").click()
        return self

    def open_book(self, title: str) -> None:
        self.page.get_by_role("link", name=title, exact=True).click()
