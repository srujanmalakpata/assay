"""FastAPI dependencies shared by the API and HTML routers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Request

from sut import db


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """One SQLite connection per request, always closed afterwards."""
    conn = db.connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()
