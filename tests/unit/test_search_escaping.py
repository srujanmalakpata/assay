"""Unit tests for LIKE-pattern escaping (regression tests for BUG-001)."""

from __future__ import annotations

import sqlite3

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sut.services import InvalidInput, escape_like, search_books

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [("abc", "abc"), ("%", "\\%"), ("_", "\\_"), ("\\", "\\\\"), ("50%_off\\", "50\\%\\_off\\\\")],
)
def test_escape_like(raw: str, escaped: str) -> None:
    assert escape_like(raw) == escaped


def ascii_lower(text: str) -> str:
    """LIKE folds ASCII case only, so compare with ASCII-only lowercasing."""
    return "".join(c.lower() if c.isascii() else c for c in text)


@pytest.mark.property
@given(
    # NUL is excluded: SQLite truncates patterns at NUL, so the service rejects it (BUG-002).
    # Lone surrogates (Cs) are excluded: they are not encodable as UTF-8, so sqlite3 raises
    # UnicodeEncodeError before LIKE runs (st.text() already excludes them for the haystack).
    needle=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
        max_size=8,
    ),
    haystack=st.text(max_size=20),
)
def test_escaped_like_agrees_with_python_substring(needle: str, haystack: str) -> None:
    """SQLite LIKE on an escaped needle behaves like `in` (for ASCII case-folding)."""
    conn = sqlite3.connect(":memory:")
    matched = conn.execute(
        "SELECT ? LIKE ? ESCAPE '\\'", (haystack, f"%{escape_like(needle)}%")
    ).fetchone()[0]
    conn.close()
    assert bool(matched) == (ascii_lower(needle) in ascii_lower(haystack))


def test_search_rejects_nul_characters() -> None:
    """BUG-002 regression: '\x00zzz' used to match every book."""
    conn = sqlite3.connect(":memory:")
    with pytest.raises(InvalidInput, match="NUL"):
        search_books(conn, "\x00zzz")
    conn.close()
