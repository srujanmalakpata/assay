"""Navigation regressions with an old document and a partially parsed response.

Advance observable browser state on each unsuccessful poll instead of using time
or a real browser, so the pre-submit result count reliably exposes the old race.
"""

from unittest.mock import Mock

import pytest
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

from qa_suite import selenium_pages

pytestmark = pytest.mark.unit


@pytest.fixture
def navigating_driver(monkeypatch: pytest.MonkeyPatch) -> Mock:
    driver = Mock()
    driver.phase = 0  # 0: initial; 1: request pending; 2: parsing; 3: loaded
    driver.login_result = "nav-user"
    driver.search_titles = ["Anna Karenina", "War and Peace"]

    class PollingWait:
        def __init__(self, driver: Mock, timeout: float):
            self.driver = driver

        def until(self, condition):
            for _ in range(4):
                try:
                    if result := condition(self.driver):
                        return result
                except NoSuchElementException:
                    pass
                if self.driver.phase in (1, 2):
                    self.driver.phase += 1
            raise AssertionError("Condition never matched the response document")

    monkeypatch.setattr(selenium_pages, "WebDriverWait", PollingWait)

    def element(text: str = "") -> Mock:
        result = Mock()
        result.text = text
        result.is_displayed.return_value = True
        return result

    button = element()

    def click() -> None:
        driver.phase = 1

    def enabled() -> bool:
        if driver.phase >= 2:
            raise StaleElementReferenceException()
        return True

    button.click.side_effect = click
    button.is_enabled.side_effect = enabled

    def find_element(by: str, selector: str) -> Mock:
        if selector in (
            '[data-testid="login-submit"]',
            '[data-testid="search-submit"]',
            '[data-testid="add-to-cart"]',
        ):
            return button
        if selector == '[data-testid="result-count"]':
            count = len(driver.search_titles) if driver.phase == 3 else 20
            return element(f'{count} results for "tolstoy"' if driver.phase == 3 else "20 results")
        if selector in ('[data-testid="nav-user"]', '[data-testid="login-error"]'):
            if driver.phase == 3 and selector == f'[data-testid="{driver.login_result}"]':
                return element("Signed in as reader")
            raise NoSuchElementException()
        if selector == '[data-testid="added-notice"]':
            if driver.phase != 3:
                raise NoSuchElementException()
            return element('Added "Example" to your cart.')
        return element()

    def find_elements(by: str, selector: str) -> list[Mock]:
        if driver.phase != 3:
            return []
        rows = []
        for title in driver.search_titles:
            row = Mock()
            row.find_element.return_value = element(title)
            rows.append(row)
        return rows

    driver.find_element.side_effect = find_element
    driver.find_elements.side_effect = find_elements
    driver.execute_script.side_effect = lambda _: "complete" if driver.phase == 3 else "loading"
    return driver


@pytest.mark.parametrize("outcome", ["nav-user", "login-error"])
def test_login_waits_for_its_response_before_returning(
    navigating_driver: Mock, outcome: str
) -> None:
    navigating_driver.login_result = outcome
    selenium_pages.SeleniumLoginPage(navigating_driver, "http://localhost").login(
        "reader", "password"
    )
    assert navigating_driver.phase == 3


@pytest.mark.parametrize("titles", [["Anna Karenina", "War and Peace"], []])
def test_search_reads_only_the_completed_response(
    navigating_driver: Mock, titles: list[str]
) -> None:
    navigating_driver.search_titles = titles
    page = selenium_pages.SeleniumSearchPage(navigating_driver, "http://localhost")
    page.search("tolstoy")
    assert navigating_driver.phase == 3
    assert page.titles() == titles
    assert page.find("result-count").text == f'{len(titles)} results for "tolstoy"'


def test_add_to_cart_waits_for_confirmation(navigating_driver: Mock) -> None:
    page = selenium_pages.SeleniumBookPage(navigating_driver, "http://localhost")
    page.add_to_cart(1, quantity=3)
    assert navigating_driver.phase == 3
    assert page.added_notice() == 'Added "Example" to your cart.'
