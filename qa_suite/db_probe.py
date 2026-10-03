"""Read-only SQL access to the SUT's SQLite file for database-state assertions.

UI and API tests check what the user sees; these helpers check what was actually
persisted (stock levels, order rows, sessions). The connection is opened read-only
so a test can never "fix" the data it is asserting on.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class DbProbe:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def scalar(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        conn = self._connect()
        try:
            row = conn.execute(sql, params).fetchone()
            return None if row is None else row[0]
        finally:
            conn.close()

    # Convenience queries used across suites -------------------------------------
    def stock_of(self, book_id: int) -> int:
        return self.scalar("SELECT stock FROM books WHERE id = ?", (book_id,))

    def order_count(self, user_id: int) -> int:
        return self.scalar("SELECT COUNT(*) FROM orders WHERE user_id = ?", (user_id,))

    def cart_rows(self, user_id: int) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT book_id, quantity FROM cart_items WHERE user_id = ? ORDER BY book_id",
            (user_id,),
        )
