"""Registration, login and authorization rules of the REST API."""

from __future__ import annotations

import pytest

from qa_suite.api_client import BookshopApi
from qa_suite.builders import CreatedUser, UserBuilder
from qa_suite.contracts import assert_matches_schema
from qa_suite.server import SutHandle, wait_until_healthy

pytestmark = pytest.mark.api


@pytest.mark.smoke
def test_health_endpoint(api: BookshopApi) -> None:
    response = api.http.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_check_rejects_a_server_with_another_instance_id(sut: SutHandle) -> None:
    """free_port() race: another worker's SUT on "our" port must not count as healthy."""
    with pytest.raises(RuntimeError, match="answered 200 from"):
        wait_until_healthy(sut.base_url, timeout=0.5, instance_id="some-other-server")


@pytest.mark.smoke
@pytest.mark.contract
def test_register_then_login_returns_bearer_token(api: BookshopApi) -> None:
    payload = UserBuilder().build()
    created = api.register(**payload)
    assert created.status_code == 201
    assert_matches_schema(created.json(), "user")
    assert created.json()["username"] == payload["username"]

    token = api.token(**payload)
    assert token.status_code == 200
    assert_matches_schema(token.json(), "token")


def test_duplicate_username_is_rejected_with_409(api: BookshopApi, user: CreatedUser) -> None:
    response = api.register(user.username, "another-password")
    assert response.status_code == 409
    assert_matches_schema(response.json(), "error")
    assert "already taken" in response.json()["detail"]


@pytest.mark.regression
def test_usernames_are_unique_regardless_of_case(api: BookshopApi, user: CreatedUser) -> None:
    """BUG-011: 'DEMO' could be registered next to 'demo', allowing look-alike accounts."""
    for variant in (user.username.upper(), user.username.title()):
        response = api.register(variant, "another-password")
        assert response.status_code == 409, f"{variant!r}: {response.text}"
    assert api.register("DEMO", "another-password").status_code == 409  # seeded 'demo'


@pytest.mark.parametrize(
    ("username", "password", "bad_field"),
    [
        ("ab", "long-enough-pw", "username"),  # too short
        ("x" * 33, "long-enough-pw", "username"),  # too long
        ("has space", "long-enough-pw", "username"),  # disallowed character
        ("valid_name", "short", "password"),  # password under 8 characters
    ],
)
def test_registration_validation(
    api: BookshopApi, username: str, password: str, bad_field: str
) -> None:
    response = api.register(username, password)
    assert response.status_code == 422
    assert_matches_schema(response.json(), "error")
    assert response.json()["detail"][0]["loc"][-1] == bad_field


@pytest.mark.parametrize("which", ["wrong-password", "unknown-user"])
def test_login_failures_do_not_reveal_which_part_was_wrong(
    api: BookshopApi, user: CreatedUser, which: str
) -> None:
    if which == "wrong-password":
        response = api.token(user.username, "not-the-password")
    else:
        response = api.token("no_such_user_xyz", user.password)
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid username or password"}


@pytest.mark.smoke
@pytest.mark.parametrize("path", ["/api/cart", "/api/orders"])
def test_protected_endpoints_require_a_token(api: BookshopApi, path: str) -> None:
    response = api.http.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "header", ["Bearer not-a-real-token", "Basic dXNlcjpwYXNz", "bearer", "Token abc"]
)
def test_invalid_authorization_headers_are_rejected(api: BookshopApi, header: str) -> None:
    response = api.http.get("/api/cart", headers={"Authorization": header})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "token",
    [
        None,
        "wrong-admin-token",
        b"\xe9t\xe9",  # non-ASCII header bytes used to crash the comparison (BUG-006)
    ],
)
def test_creating_books_requires_the_admin_token(
    api: BookshopApi, token: str | bytes | None
) -> None:
    headers = {"X-Admin-Token": token} if token else {}
    payload = {"isbn": "9791234567890", "title": "T", "author": "A", "price_cents": 1, "stock": 1}
    response = api.http.post("/api/books", json=payload, headers=headers)
    assert response.status_code == 403
