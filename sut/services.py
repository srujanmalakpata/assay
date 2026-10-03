"""Business operations shared by the JSON API and the HTML pages.

Every function takes an open connection, so the web layers stay thin and the
same rules (stock checks, pricing, ownership) apply to both interfaces.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from sut import pricing, security
from sut.db import transaction

MAX_PAGE_SIZE = 50
MAX_QUANTITY = 99
MAX_QUERY_LENGTH = 100
# SQLite INTEGER is a signed 64-bit value; larger Python ints raise OverflowError (BUG-005).
MAX_ID = 2**63 - 1
# Caps OFFSET = (page - 1) * MAX_PAGE_SIZE far below MAX_ID (BUG-005).
MAX_PAGE = 10_000
SESSION_HOURS = 12


class DomainError(Exception):
    """Base class for errors that map to a 4xx response."""


class NotFound(DomainError):
    pass


class Conflict(DomainError):
    pass


class InvalidInput(DomainError):
    pass


class AuthError(DomainError):
    pass


@dataclass(frozen=True)
class User:
    id: int
    username: str


@dataclass(frozen=True)
class Book:
    id: int
    isbn: str
    title: str
    author: str
    price_cents: int
    stock: int


@dataclass(frozen=True)
class CartLine:
    book: Book
    quantity: int

    @property
    def line_total_cents(self) -> int:
        return self.book.price_cents * self.quantity


@dataclass(frozen=True)
class Cart:
    lines: list[CartLine]
    quote: pricing.Quote


@dataclass(frozen=True)
class OrderLine:
    book_id: int
    title: str
    quantity: int
    unit_price_cents: int


@dataclass(frozen=True)
class Order:
    id: int
    user_id: int
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    created_at: str
    lines: list[OrderLine]


@dataclass(frozen=True)
class Page:
    items: list[Book]
    total: int
    page: int
    page_size: int


def _book(row: sqlite3.Row) -> Book:
    return Book(
        id=row["id"],
        isbn=row["isbn"],
        title=row["title"],
        author=row["author"],
        price_cents=row["price_cents"],
        stock=row["stock"],
    )


def _valid_id(value: int) -> bool:
    """Ids outside SQLite's INTEGER range cannot exist, so they are reported as not found."""
    return 1 <= value <= MAX_ID


# --- users and sessions -----------------------------------------------------------

# Verifying against this when the username is unknown makes both login failures cost
# one PBKDF2 run, so response time does not reveal which usernames exist.
_DUMMY_PASSWORD_HASH = security.hash_password("not-a-real-password", salt=b"dummy-salt-00000")


def create_user(conn: sqlite3.Connection, username: str, password: str) -> User:
    try:
        with transaction(conn):
            cur = conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, security.hash_password(password)),
            )
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"username '{username}' is already taken") from exc
    return User(id=cur.lastrowid, username=username)


def login(conn: sqlite3.Connection, username: str, password: str) -> str:
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    stored_hash = row["password_hash"] if row else _DUMMY_PASSWORD_HASH
    password_ok = security.verify_password(password, stored_hash)
    if row is None or not password_ok:
        raise AuthError("invalid username or password")
    token = security.new_token()
    with transaction(conn):
        # Expired sessions can never be used again, so each login prunes them.
        conn.execute("DELETE FROM sessions WHERE expires_at <= datetime('now')")
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) "
            "VALUES (?, ?, datetime('now', ?))",
            (security.token_digest(token), row["id"], f"+{SESSION_HOURS} hours"),
        )
    return token


def logout(conn: sqlite3.Connection, token: str) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (security.token_digest(token),))


def user_for_token(conn: sqlite3.Connection, token: str | None) -> User | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT u.id, u.username FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > datetime('now')",
        (security.token_digest(token),),
    ).fetchone()
    return User(id=row["id"], username=row["username"]) if row else None


# --- catalogue --------------------------------------------------------------------


def escape_like(text: str) -> str:
    """Escape LIKE wildcards so user input is matched literally (BUG-001)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_books(
    conn: sqlite3.Connection, query: str = "", page: int = 1, page_size: int = 10
) -> Page:
    if not 1 <= page <= MAX_PAGE:
        raise InvalidInput(f"page must be between 1 and {MAX_PAGE}")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise InvalidInput(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    if "\x00" in query:
        # SQLite stops reading a LIKE pattern at NUL, so "\x00x" would match everything (BUG-002).
        raise InvalidInput("search text must not contain NUL characters")
    if len(query) > MAX_QUERY_LENGTH:
        raise InvalidInput(f"search text must be at most {MAX_QUERY_LENGTH} characters")
    pattern = f"%{escape_like(query.strip())}%"
    where = "WHERE title LIKE ? ESCAPE '\\' OR author LIKE ? ESCAPE '\\'"
    total = conn.execute(f"SELECT COUNT(*) FROM books {where}", (pattern, pattern)).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM books {where} ORDER BY title, id LIMIT ? OFFSET ?",
        (pattern, pattern, page_size, (page - 1) * page_size),
    ).fetchall()
    return Page(items=[_book(r) for r in rows], total=total, page=page, page_size=page_size)


def get_book(conn: sqlite3.Connection, book_id: int) -> Book:
    if not _valid_id(book_id):
        raise NotFound(f"book {book_id} not found")
    row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise NotFound(f"book {book_id} not found")
    return _book(row)


def create_book(
    conn: sqlite3.Connection, isbn: str, title: str, author: str, price_cents: int, stock: int
) -> Book:
    try:
        with transaction(conn):
            cur = conn.execute(
                "INSERT INTO books (isbn, title, author, price_cents, stock) "
                "VALUES (?, ?, ?, ?, ?)",
                (isbn, title, author, price_cents, stock),
            )
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"a book with ISBN {isbn} already exists") from exc
    return get_book(conn, cur.lastrowid)


# --- cart -------------------------------------------------------------------------


def get_cart(conn: sqlite3.Connection, user_id: int) -> Cart:
    rows = conn.execute(
        "SELECT b.*, c.quantity FROM cart_items c JOIN books b ON b.id = c.book_id "
        "WHERE c.user_id = ? ORDER BY b.title, b.id",
        (user_id,),
    ).fetchall()
    lines = [CartLine(book=_book(r), quantity=r["quantity"]) for r in rows]
    quote = pricing.quote([pricing.LineItem(ln.book.price_cents, ln.quantity) for ln in lines])
    return Cart(lines=lines, quote=quote)


def _write_cart_quantity(
    conn: sqlite3.Connection, user_id: int, book_id: int, quantity: int
) -> None:
    """Validate and store a cart quantity. The caller must hold a write transaction."""
    if not 0 <= quantity <= MAX_QUANTITY:
        raise InvalidInput(f"quantity must be between 0 and {MAX_QUANTITY}")
    book = get_book(conn, book_id)
    if quantity > book.stock:
        raise Conflict(f"only {book.stock} cop{'y' if book.stock == 1 else 'ies'} in stock")
    if quantity == 0:
        conn.execute("DELETE FROM cart_items WHERE user_id = ? AND book_id = ?", (user_id, book_id))
    else:
        conn.execute(
            "INSERT INTO cart_items (user_id, book_id, quantity) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id, book_id) DO UPDATE SET quantity = excluded.quantity",
            (user_id, book_id, quantity),
        )


def set_cart_quantity(conn: sqlite3.Connection, user_id: int, book_id: int, quantity: int) -> Cart:
    """Set the quantity of a book in the cart; a quantity of 0 removes the line."""
    with transaction(conn):
        _write_cart_quantity(conn, user_id, book_id, quantity)
    return get_cart(conn, user_id)


def add_to_cart(conn: sqlite3.Connection, user_id: int, book_id: int, quantity: int = 1) -> Cart:
    """Add copies to the cart. Read and write share one transaction (BUG-008: lost updates)."""
    get_book(conn, book_id)  # an unknown book is a 404 whatever the quantity
    if not 1 <= quantity <= MAX_QUANTITY:
        raise InvalidInput(f"quantity must be between 1 and {MAX_QUANTITY}")  # BUG-007
    with transaction(conn):
        row = conn.execute(
            "SELECT quantity FROM cart_items WHERE user_id = ? AND book_id = ?",
            (user_id, book_id),
        ).fetchone()
        current = row["quantity"] if row else 0
        _write_cart_quantity(conn, user_id, book_id, current + quantity)
    return get_cart(conn, user_id)


# --- orders -----------------------------------------------------------------------


def checkout(conn: sqlite3.Connection, user_id: int) -> Order:
    """Turn the cart into an order atomically, decrementing stock."""
    with transaction(conn):
        cart = get_cart(conn, user_id)
        if not cart.lines:
            raise InvalidInput("cart is empty")
        for line in cart.lines:
            updated = conn.execute(
                "UPDATE books SET stock = stock - ? WHERE id = ? AND stock >= ?",
                (line.quantity, line.book.id, line.quantity),
            ).rowcount
            if updated != 1:
                raise Conflict(f"'{line.book.title}' no longer has enough stock")
        cur = conn.execute(
            "INSERT INTO orders (user_id, subtotal_cents, discount_cents, total_cents) "
            "VALUES (?, ?, ?, ?)",
            (
                user_id,
                cart.quote.subtotal_cents,
                cart.quote.discount_cents,
                cart.quote.total_cents,
            ),
        )
        order_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO order_items (order_id, book_id, quantity, unit_price_cents) "
            "VALUES (?, ?, ?, ?)",
            [(order_id, ln.book.id, ln.quantity, ln.book.price_cents) for ln in cart.lines],
        )
        conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
    return get_order(conn, user_id, order_id)


def get_order(conn: sqlite3.Connection, user_id: int, order_id: int) -> Order:
    if not _valid_id(order_id):
        raise NotFound(f"order {order_id} not found")
    row = conn.execute(
        "SELECT * FROM orders WHERE id = ? AND user_id = ?", (order_id, user_id)
    ).fetchone()
    if row is None:
        # Another user's order is reported as missing so ids cannot be probed.
        raise NotFound(f"order {order_id} not found")
    lines = conn.execute(
        "SELECT oi.book_id, b.title, oi.quantity, oi.unit_price_cents FROM order_items oi "
        "JOIN books b ON b.id = oi.book_id WHERE oi.order_id = ? ORDER BY b.title",
        (order_id,),
    ).fetchall()
    return Order(
        id=row["id"],
        user_id=row["user_id"],
        subtotal_cents=row["subtotal_cents"],
        discount_cents=row["discount_cents"],
        total_cents=row["total_cents"],
        created_at=row["created_at"],
        lines=[OrderLine(**dict(r)) for r in lines],
    )


def list_orders(conn: sqlite3.Connection, user_id: int) -> list[Order]:
    ids = conn.execute(
        "SELECT id FROM orders WHERE user_id = ? ORDER BY id DESC", (user_id,)
    ).fetchall()
    return [get_order(conn, user_id, r["id"]) for r in ids]
