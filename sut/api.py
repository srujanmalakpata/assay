"""JSON REST API under /api."""

from __future__ import annotations

import hmac
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, Field

from sut import services
from sut.deps import get_conn

router = APIRouter(prefix="/api", tags=["api"])

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
# Ids are bounded to SQLite's INTEGER range so huge values get a 422, not a 500 (BUG-005).
ResourceId = Annotated[int, Path(ge=1, le=services.MAX_ID)]


# --- request / response models ----------------------------------------------------


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(max_length=32)
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    id: int
    username: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class BookIn(BaseModel):
    isbn: str = Field(pattern=r"^\d{13}$")
    title: str = Field(min_length=1, max_length=200)
    author: str = Field(min_length=1, max_length=120)
    price_cents: int = Field(ge=0, le=1_000_000)
    stock: int = Field(ge=0, le=100_000)


class BookOut(BaseModel):
    id: int
    isbn: str
    title: str
    author: str
    price_cents: int
    stock: int


class BookPage(BaseModel):
    items: list[BookOut]
    total: int
    page: int
    page_size: int


class QuantityIn(BaseModel):
    # Strict: JSON true, 2.0 or "2" is a 422 instead of being coerced to an int.
    quantity: int = Field(ge=0, le=services.MAX_QUANTITY, strict=True)


class CartLineOut(BaseModel):
    book_id: int
    title: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int


class CartOut(BaseModel):
    items: list[CartLineOut]
    subtotal_cents: int
    discount_cents: int
    total_cents: int


class OrderLineOut(BaseModel):
    book_id: int
    title: str
    quantity: int
    unit_price_cents: int


class OrderOut(BaseModel):
    id: int
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    created_at: str
    items: list[OrderLineOut]


# --- helpers ----------------------------------------------------------------------


def _book_out(book: services.Book) -> BookOut:
    return BookOut(**book.__dict__)


def _cart_out(cart: services.Cart) -> CartOut:
    return CartOut(
        items=[
            CartLineOut(
                book_id=ln.book.id,
                title=ln.book.title,
                quantity=ln.quantity,
                unit_price_cents=ln.book.price_cents,
                line_total_cents=ln.line_total_cents,
            )
            for ln in cart.lines
        ],
        subtotal_cents=cart.quote.subtotal_cents,
        discount_cents=cart.quote.discount_cents,
        total_cents=cart.quote.total_cents,
    )


def _order_out(order: services.Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        subtotal_cents=order.subtotal_cents,
        discount_cents=order.discount_cents,
        total_cents=order.total_cents,
        created_at=order.created_at,
        items=[OrderLineOut(**ln.__dict__) for ln in order.lines],
    )


def current_user(
    conn: Conn, authorization: Annotated[str | None, Header()] = None
) -> services.User:
    scheme, _, token = (authorization or "").partition(" ")
    user = services.user_for_token(conn, token) if scheme.lower() == "bearer" else None
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[services.User, Depends(current_user)]


def require_admin(request: Request, x_admin_token: Annotated[str | None, Header()] = None) -> None:
    expected = request.app.state.settings.admin_token
    # Compare bytes: compare_digest(str, str) raises TypeError on non-ASCII input (BUG-006).
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin token required")


# --- routes -----------------------------------------------------------------------


@router.post("/users", status_code=status.HTTP_201_CREATED, response_model=UserOut)
def register(body: Credentials, conn: Conn) -> UserOut:
    user = services.create_user(conn, body.username, body.password)
    return UserOut(id=user.id, username=user.username)


@router.post("/auth/token", response_model=TokenOut)
def issue_token(body: LoginRequest, conn: Conn) -> TokenOut:
    return TokenOut(access_token=services.login(conn, body.username, body.password))


@router.get("/books", response_model=BookPage)
def search_books(
    conn: Conn,
    q: Annotated[str, Query(max_length=services.MAX_QUERY_LENGTH)] = "",
    page: Annotated[int, Query(ge=1, le=services.MAX_PAGE)] = 1,
    page_size: Annotated[int, Query(ge=1, le=services.MAX_PAGE_SIZE)] = 10,
) -> BookPage:
    result = services.search_books(conn, q, page, page_size)
    return BookPage(
        items=[_book_out(b) for b in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/books/{book_id}", response_model=BookOut)
def get_book(book_id: ResourceId, conn: Conn) -> BookOut:
    return _book_out(services.get_book(conn, book_id))


@router.post(
    "/books",
    status_code=status.HTTP_201_CREATED,
    response_model=BookOut,
    dependencies=[Depends(require_admin)],
)
def create_book(body: BookIn, conn: Conn) -> BookOut:
    return _book_out(services.create_book(conn, **body.model_dump()))


@router.get("/cart", response_model=CartOut)
def get_cart(user: CurrentUser, conn: Conn) -> CartOut:
    return _cart_out(services.get_cart(conn, user.id))


@router.put("/cart/items/{book_id}", response_model=CartOut)
def set_cart_item(book_id: ResourceId, body: QuantityIn, user: CurrentUser, conn: Conn) -> CartOut:
    return _cart_out(services.set_cart_quantity(conn, user.id, book_id, body.quantity))


@router.delete("/cart/items/{book_id}", response_model=CartOut)
def delete_cart_item(book_id: ResourceId, user: CurrentUser, conn: Conn) -> CartOut:
    return _cart_out(services.set_cart_quantity(conn, user.id, book_id, 0))


@router.post("/orders", status_code=status.HTTP_201_CREATED, response_model=OrderOut)
def checkout(user: CurrentUser, conn: Conn) -> OrderOut:
    return _order_out(services.checkout(conn, user.id))


@router.get("/orders", response_model=list[OrderOut])
def list_orders(user: CurrentUser, conn: Conn) -> list[OrderOut]:
    return [_order_out(o) for o in services.list_orders(conn, user.id)]


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: ResourceId, user: CurrentUser, conn: Conn) -> OrderOut:
    return _order_out(services.get_order(conn, user.id, order_id))
