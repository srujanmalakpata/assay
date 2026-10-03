"""Order confirmation page."""

from __future__ import annotations

import re

from playwright.sync_api import Locator

from qa_suite.pages.base_page import BasePage


class OrderPage(BasePage):
    @property
    def confirmation(self) -> Locator:
        return self.page.get_by_test_id("order-heading")

    @property
    def total(self) -> Locator:
        return self.page.get_by_test_id("order-total")

    @property
    def rows(self) -> Locator:
        return self.page.get_by_test_id("order-row")

    def order_id(self) -> int:
        match = re.search(r"/orders/(\d+)$", self.page.url)
        assert match, f"not on an order page: {self.page.url}"
        return int(match.group(1))
