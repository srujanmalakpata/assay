"""Book detail page with the add-to-cart form."""

from __future__ import annotations

from playwright.sync_api import Locator

from qa_suite.pages.base_page import BasePage


class BookPage(BasePage):
    def open_book(self, book_id: int) -> BookPage:
        return self.open(f"/books/{book_id}")

    @property
    def title(self) -> Locator:
        return self.page.get_by_test_id("book-title")

    @property
    def price(self) -> Locator:
        return self.page.get_by_test_id("book-price")

    @property
    def stock(self) -> Locator:
        return self.page.get_by_test_id("book-stock")

    @property
    def sold_out(self) -> Locator:
        return self.page.get_by_test_id("sold-out")

    @property
    def add_button(self) -> Locator:
        return self.page.get_by_test_id("add-to-cart")

    def add_to_cart(self, quantity: int = 1) -> None:
        self.page.get_by_label("Quantity").fill(str(quantity))
        self.add_button.click()
