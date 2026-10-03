"""Shopping cart page."""

from __future__ import annotations

from playwright.sync_api import Locator

from qa_suite.pages.base_page import BasePage


class CartPage(BasePage):
    path = "/cart"

    @property
    def rows(self) -> Locator:
        return self.page.get_by_test_id("cart-row")

    def row_for(self, book_id: int) -> Locator:
        return self.page.locator(f'[data-testid="cart-row"][data-book-id="{book_id}"]')

    @property
    def added_notice(self) -> Locator:
        return self.page.get_by_test_id("added-notice")

    @property
    def empty_message(self) -> Locator:
        return self.page.get_by_test_id("empty-cart")

    @property
    def error(self) -> Locator:
        return self.page.get_by_test_id("error")

    @property
    def subtotal(self) -> Locator:
        return self.page.get_by_test_id("subtotal")

    @property
    def discount(self) -> Locator:
        return self.page.get_by_test_id("discount")

    @property
    def total(self) -> Locator:
        return self.page.get_by_test_id("total")

    def set_quantity(self, book_id: int, quantity: int) -> None:
        row = self.row_for(book_id)
        row.get_by_test_id("cart-quantity").fill(str(quantity))
        row.get_by_test_id("cart-update").click()

    def checkout(self) -> None:
        self.page.get_by_test_id("checkout").click()
