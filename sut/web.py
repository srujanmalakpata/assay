"""Server-rendered HTML pages (Jinja2) for the browser-based UI tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from sut import services
from sut.deps import get_conn
from sut.pricing import format_cents

SESSION_COOKIE = "session"

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters["money"] = format_cents

router = APIRouter(include_in_schema=False)

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def page_user(request: Request, conn: Conn) -> services.User | None:
    return services.user_for_token(conn, request.cookies.get(SESSION_COOKIE))


PageUser = Annotated[services.User | None, Depends(page_user)]


def _render(
    request: Request,
    name: str,
    user: services.User | None,
    status_code: int = 200,
    **context: object,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, name, {"user": user, **context}, status_code=status_code
    )


def _safe_next(target: str | None) -> str:
    """Only allow same-site absolute paths as a post-login redirect (prevents open redirects).

    Browsers treat a backslash like a slash and drop tabs/newlines, so "/\\evil.example"
    would become "//evil.example": anything with a backslash or control character is refused,
    as is anything that parses with a scheme or host.
    """
    if not target or not target.startswith("/") or target.startswith("//"):
        return "/"
    if "\\" in target or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in target):
        return "/"
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return "/"
    return target


def _login_redirect(next_path: str) -> RedirectResponse:
    return RedirectResponse(f"/login?next={next_path}", status_code=status.HTTP_303_SEE_OTHER)


def _see_other(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


def _status_for(exc: services.DomainError) -> int:
    """Same mapping as the JSON API: bad input is 400, a stock/state clash is 409."""
    return status.HTTP_400_BAD_REQUEST if isinstance(exc, services.InvalidInput) else 409


def _cart_error(
    request: Request, conn: sqlite3.Connection, user: services.User, exc: services.DomainError
) -> HTMLResponse:
    cart = services.get_cart(conn, user.id)
    return _render(
        request, "cart.html", user, _status_for(exc), cart=cart, added_title=None, error=str(exc)
    )


INSTANCE_HEADER = "X-Instance-Id"


@router.get("/healthz")
def healthz(request: Request, response: Response) -> dict[str, str]:
    response.headers[INSTANCE_HEADER] = request.app.state.settings.instance_id
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
def home(request: Request, conn: Conn, user: PageUser) -> HTMLResponse:
    featured = services.search_books(conn, "", 1, 6).items
    return _render(request, "index.html", user, featured=featured)


@router.get("/books", response_class=HTMLResponse)
def search(
    request: Request, conn: Conn, user: PageUser, q: str = "", page: int = 1
) -> HTMLResponse:
    try:
        result = services.search_books(conn, q, page, 10)
    except services.InvalidInput as exc:
        return _render(request, "books.html", user, 400, q=q, result=None, error=str(exc))
    return _render(request, "books.html", user, q=q, result=result, error=None)


@router.get("/books/{book_id}", response_class=HTMLResponse)
def book_detail(request: Request, book_id: int, conn: Conn, user: PageUser) -> HTMLResponse:
    try:
        book = services.get_book(conn, book_id)
    except services.NotFound:
        return _render(request, "not_found.html", user, 404)
    return _render(request, "book.html", user, book=book, error=None)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, user: PageUser, next: str = "/") -> HTMLResponse:
    return _render(request, "login.html", user, next=_safe_next(next), error=None)


@router.post("/login", response_model=None)
def login_submit(
    request: Request,
    conn: Conn,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "/",
) -> Response:
    try:
        token = services.login(conn, username, password)
    except services.AuthError:
        return _render(
            request,
            "login.html",
            None,
            status.HTTP_401_UNAUTHORIZED,
            next=_safe_next(next),
            error="Invalid username or password.",
            username=username,
        )
    response = _see_other(_safe_next(next))
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
    return response


@router.post("/logout")
def logout(request: Request, conn: Conn) -> RedirectResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        services.logout(conn, token)
    response = _see_other("/")
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/cart", response_class=HTMLResponse, response_model=None)
def cart_page(request: Request, conn: Conn, user: PageUser, added: int | None = None) -> Response:
    if user is None:
        return _login_redirect("/cart")
    cart = services.get_cart(conn, user.id)
    added_title = None
    if added is not None:
        added_title = next((ln.book.title for ln in cart.lines if ln.book.id == added), None)
    return _render(request, "cart.html", user, cart=cart, added_title=added_title, error=None)


@router.post("/cart/add", response_model=None)
def cart_add(
    request: Request,
    conn: Conn,
    user: PageUser,
    book_id: Annotated[int, Form()],
    quantity: Annotated[int, Form()] = 1,
) -> Response:
    if user is None:
        return _login_redirect(f"/books/{book_id}")
    try:
        services.add_to_cart(conn, user.id, book_id, quantity)
    except services.NotFound:
        return _render(request, "not_found.html", user, 404)
    except (services.Conflict, services.InvalidInput) as exc:
        book = services.get_book(conn, book_id)
        return _render(request, "book.html", user, _status_for(exc), book=book, error=str(exc))
    return _see_other(f"/cart?added={book_id}")


@router.post("/cart/update", response_model=None)
def cart_update(
    request: Request,
    conn: Conn,
    user: PageUser,
    book_id: Annotated[int, Form()],
    quantity: Annotated[int, Form()],
) -> Response:
    if user is None:
        return _login_redirect("/cart")
    try:
        services.set_cart_quantity(conn, user.id, book_id, quantity)
    except services.NotFound:
        return _render(request, "not_found.html", user, 404)
    except (services.Conflict, services.InvalidInput) as exc:
        return _cart_error(request, conn, user, exc)
    return _see_other("/cart")


@router.post("/checkout", response_model=None)
def checkout(request: Request, conn: Conn, user: PageUser) -> Response:
    if user is None:
        return _login_redirect("/cart")
    try:
        order = services.checkout(conn, user.id)
    except (services.Conflict, services.InvalidInput) as exc:
        return _cart_error(request, conn, user, exc)
    return _see_other(f"/orders/{order.id}")


@router.get("/orders/{order_id}", response_class=HTMLResponse, response_model=None)
def order_page(request: Request, order_id: int, conn: Conn, user: PageUser) -> Response:
    if user is None:
        return _login_redirect(f"/orders/{order_id}")
    try:
        order = services.get_order(conn, user.id, order_id)
    except services.NotFound:
        return _render(request, "not_found.html", user, 404)
    return _render(request, "order.html", user, order=order)
