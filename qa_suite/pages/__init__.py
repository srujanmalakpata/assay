"""Playwright page objects. Tests talk to pages through these classes, never raw selectors."""

from qa_suite.pages.base_page import BasePage
from qa_suite.pages.book_page import BookPage
from qa_suite.pages.cart_page import CartPage
from qa_suite.pages.login_page import LoginPage
from qa_suite.pages.order_page import OrderPage
from qa_suite.pages.search_page import SearchPage

__all__ = ["BasePage", "BookPage", "CartPage", "LoginPage", "OrderPage", "SearchPage"]
