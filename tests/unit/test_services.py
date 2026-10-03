"""Service-layer rules checked directly against a throwaway SQLite file (no HTTP)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from sut import db, security, services
from sut.seed_data import DEMO_PASSWORD, DEMO_USERNAME
from sut.web import _safe_next

pytestmark = pytest.mark.unit


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "unit.sqlite3"
    db.initialise(path)
    connection = db.connect(path)
    yield connection
    connection.close()


def test_unknown_usernames_cost_a_password_hash_too(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-009: skipping PBKDF2 for unknown users made them measurably faster to reject."""
    calls: list[str] = []
    real_verify = security.verify_password

    def counting_verify(password: str, stored: str) -> bool:
        calls.append(stored)
        return real_verify(password, stored)

    monkeypatch.setattr(security, "verify_password", counting_verify)
    for username in ("no_such_user", DEMO_USERNAME):
        with pytest.raises(services.AuthError):
            services.login(conn, username, "wrong-password")
    assert len(calls) == 2, "both failures must run exactly one password hash"
    assert all(stored.startswith("pbkdf2_sha256$100000$") for stored in calls)


def test_login_stores_only_the_token_digest(conn: sqlite3.Connection) -> None:
    token = services.login(conn, DEMO_USERNAME, DEMO_PASSWORD)
    stored = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
    assert stored == [security.token_digest(token)]
    assert services.user_for_token(conn, token) == services.User(1, DEMO_USERNAME)


def test_expired_sessions_are_not_accepted(conn: sqlite3.Connection) -> None:
    token = services.login(conn, DEMO_USERNAME, DEMO_PASSWORD)
    conn.execute("UPDATE sessions SET expires_at = datetime('now', '-1 second')")
    assert services.user_for_token(conn, token) is None


def test_login_prunes_expired_sessions(conn: sqlite3.Connection) -> None:
    old = services.login(conn, DEMO_USERNAME, DEMO_PASSWORD)
    conn.execute("UPDATE sessions SET expires_at = datetime('now', '-1 second')")
    new = services.login(conn, DEMO_USERNAME, DEMO_PASSWORD)
    stored = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
    assert stored == [security.token_digest(new)]
    assert security.token_digest(old) not in stored


def test_usernames_differing_only_in_case_conflict(conn: sqlite3.Connection) -> None:
    """BUG-011: the UNIQUE constraint was case-sensitive, so 'DEMO' could join 'demo'."""
    with pytest.raises(services.Conflict):
        services.create_user(conn, DEMO_USERNAME.upper(), "another-password")


@pytest.mark.parametrize("bad_id", [0, -1, services.MAX_ID + 1, 10**20])
def test_ids_outside_the_sqlite_range_are_not_found(conn: sqlite3.Connection, bad_id: int) -> None:
    """BUG-005: these used to raise OverflowError from the sqlite3 driver."""
    with pytest.raises(services.NotFound):
        services.get_book(conn, bad_id)
    with pytest.raises(services.NotFound):
        services.get_order(conn, 1, bad_id)
    with pytest.raises(services.NotFound):
        services.add_to_cart(conn, 1, bad_id, 1)


@pytest.mark.parametrize("quantity", [0, -2, services.MAX_QUANTITY + 1])
def test_add_to_cart_rejects_non_positive_or_huge_quantities(
    conn: sqlite3.Connection, quantity: int
) -> None:
    services.add_to_cart(conn, 1, 1, 3)
    with pytest.raises(services.InvalidInput):
        services.add_to_cart(conn, 1, 1, quantity)
    assert [ln.quantity for ln in services.get_cart(conn, 1).lines] == [3]


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/cart", "/cart"),
        ("/books?q=a&page=2", "/books?q=a&page=2"),
        (None, "/"),
        ("", "/"),
        ("cart", "/"),
        ("//evil.example", "/"),
        ("https://evil.example", "/"),
        ("/\\evil.example", "/"),
        ("/\t/evil.example", "/"),
        ("/\n/evil.example", "/"),
    ],
)
def test_safe_next_only_allows_same_site_paths(target: str | None, expected: str) -> None:
    assert _safe_next(target) == expected
