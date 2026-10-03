"""SQLite schema, connections and deterministic seeding."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sut import security
from sut.seed_data import DEMO_PASSWORD, DEMO_USERNAME, SEED_BOOKS

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,  -- 'Demo' and 'demo' clash (BUG-011)
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT    PRIMARY KEY,  -- SHA-256 of the bearer token, never the token itself
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS books (
    id          INTEGER PRIMARY KEY,
    isbn        TEXT    NOT NULL UNIQUE,
    title       TEXT    NOT NULL,
    author      TEXT    NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    stock       INTEGER NOT NULL CHECK (stock >= 0)
);
CREATE TABLE IF NOT EXISTS cart_items (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id  INTEGER NOT NULL REFERENCES books(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (user_id, book_id)
);
CREATE TABLE IF NOT EXISTS orders (
    id             INTEGER PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    subtotal_cents INTEGER NOT NULL,
    discount_cents INTEGER NOT NULL,
    total_cents    INTEGER NOT NULL,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS order_items (
    order_id         INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    book_id          INTEGER NOT NULL REFERENCES books(id),
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL,
    PRIMARY KEY (order_id, book_id)
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection in autocommit mode; callers open transactions explicitly."""
    conn = sqlite3.connect(db_path, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a write transaction that takes the write lock up front (BEGIN IMMEDIATE).

    Overselling is prevented by checkout's conditional ``UPDATE ... WHERE stock >= ?``
    and its rowcount check, not by the lock mode. What BEGIN IMMEDIATE adds:

    * A transaction that reads and then writes waits (up to ``busy_timeout``) for the
      write lock before its first read. With a deferred ``BEGIN`` in WAL mode, such a
      transaction cannot upgrade its read snapshot once another writer has committed,
      and SQLite fails it at once with SQLITE_BUSY ("database is locked", a 500); the
      busy timeout does not help in that case.
    * For ``add_to_cart`` it makes the read-modify-write atomic, so concurrent adds
      are not lost (BUG-008).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def initialise(db_path: Path, *, seed: bool = True) -> None:
    """Create the schema and, on an empty database, insert the deterministic seed data."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        if seed:
            _seed(conn)
    finally:
        conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        if conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]:
            return
        conn.executemany(
            "INSERT INTO books (isbn, title, author, price_cents, stock) VALUES (?, ?, ?, ?, ?)",
            SEED_BOOKS,
        )
        # A fixed salt keeps the seeded database byte-for-byte reproducible.
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (DEMO_USERNAME, security.hash_password(DEMO_PASSWORD, salt=b"seed-salt-000000")),
        )
