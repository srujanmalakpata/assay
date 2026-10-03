"""Keep pure unit tests independent of the live-server URL fixture.

pytest-base-url's autouse URL check requests base_url even when a test does not.
"""

import pytest


@pytest.fixture(scope="session")
def base_url() -> None:
    return None
