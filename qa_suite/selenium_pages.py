"""Selenium WebDriver page objects for the small cross-tool UI suite.

They mirror the Playwright page objects so the same scenarios can be expressed with
either driver. Selenium has no auto-waiting, so every interaction waits explicitly.
"""

from __future__ import annotations

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait


def _testid(value: str) -> tuple[str, str]:
    return By.CSS_SELECTOR, f'[data-testid="{value}"]'


class SeleniumPage:
    def __init__(self, driver: WebDriver, base_url: str, timeout: float = 10):
        self.driver = driver
        self.base_url = base_url.rstrip("/")
        self.wait = WebDriverWait(driver, timeout)

    def open(self, path: str) -> None:
        self.driver.get(self.base_url + path)

    def find(self, testid: str) -> WebElement:
        return self.wait.until(ec.visibility_of_element_located(_testid(testid)))

    def find_all(self, testid: str) -> list[WebElement]:
        return self.driver.find_elements(*_testid(testid))

    def submit(self, testid: str) -> None:
        """Wait for this form's response, not elements in the pre-submit document."""
        button = self.wait.until(ec.element_to_be_clickable(_testid(testid)))
        button.click()
        self.wait.until(ec.staleness_of(button))
        # A status element can appear before the rest of the HTML has been parsed.
        # Wait for the response document to finish loading before reading its rows.
        self.wait.until(
            lambda driver: driver.execute_script("return document.readyState") == "complete"
        )


class SeleniumLoginPage(SeleniumPage):
    def login(self, username: str, password: str) -> None:
        self.open("/login")
        self.find("username").send_keys(username)
        self.find("password").send_keys(password)
        self.submit("login-submit")
        # The caller may immediately navigate again; the session cookie and redirect
        # must have completed first. Failed credentials render a new login document.
        self.wait.until(
            ec.any_of(
                ec.visibility_of_element_located(_testid("nav-user")),
                ec.visibility_of_element_located(_testid("login-error")),
            )
        )

    def signed_in_text(self) -> str:
        return self.find("nav-user").text

    def error_text(self) -> str:
        return self.find("login-error").text


class SeleniumSearchPage(SeleniumPage):
    def search(self, query: str) -> None:
        self.open("/books")
        box = self.find("search-input")
        box.clear()
        box.send_keys(query)
        self.submit("search-submit")
        self.find("result-count")

    def titles(self) -> list[str]:
        return [
            row.find_element(By.CSS_SELECTOR, "td:first-child").text
            for row in self.find_all("result-row")
        ]


class SeleniumBookPage(SeleniumPage):
    def add_to_cart(self, book_id: int, quantity: int) -> None:
        self.open(f"/books/{book_id}")
        qty = self.find("quantity")
        qty.clear()
        qty.send_keys(str(quantity))
        self.submit("add-to-cart")
        self.find("added-notice")

    def added_notice(self) -> str:
        return self.find("added-notice").text

    def cart_total(self) -> str:
        return self.find("total").text
