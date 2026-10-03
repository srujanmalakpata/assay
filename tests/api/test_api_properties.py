"""Property-based API tests: Hypothesis generates inputs, we assert invariants.

These run against the live server over HTTP, so examples are capped to keep the
suite fast; Hypothesis still shrinks any failure to a minimal reproducing input.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from qa_suite.api_client import BookshopApi
from qa_suite.builders import BookBuilder, CreatedBook, unique_suffix
from qa_suite.contracts import assert_matches_schema

pytestmark = [pytest.mark.api, pytest.mark.property]

LIVE = settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

search_text = st.one_of(
    # Arbitrary Unicode (no lone surrogates: they are not valid UTF-8 in a URL)...
    st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=100),
    # ...plus short strings biased towards characters with meaning in SQL and URLs.
    st.text(alphabet="%_\\'\";&=+#?aeo ", max_size=6),
)


@LIVE
@given(q=search_text)
@example(q="%")  # BUG-001 regressions, pinned so they run every time
@example(q="_")
@example(q="\x00zzz")
def test_search_never_errors_and_only_returns_matches(api: BookshopApi, q: str) -> None:
    response = api.search(q)
    if "\x00" in q:  # BUG-002: NUL is rejected rather than truncating the SQL pattern
        assert response.status_code == 400, response.text
        return
    assert response.status_code == 200, response.text
    body = response.json()
    assert_matches_schema(body, "book_page")
    assert len(body["items"]) <= body["total"]
    needle = q.strip().lower()
    for book in body["items"]:
        assert needle in book["title"].lower() or needle in book["author"].lower(), (
            f"search {q!r} returned non-matching book {book['title']!r} by {book['author']!r}"
        )


# Characters a title may hold: no surrogates (invalid UTF-8) and no control characters.
title_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=1, max_size=20
)


@settings(LIVE, max_examples=30)
@given(data=st.data(), title_tail=title_text)
@example(data=None, title_tail="100% _real_ \\ data")  # wildcards must match literally too
def test_search_finds_a_book_by_any_substring_of_its_title(
    api: BookshopApi, admin_api: BookshopApi, data: st.DataObject | None, title_tail: str
) -> None:
    """Completeness: the soundness test above would pass for a search that returned []."""
    book = BookBuilder().titled(f"zq{unique_suffix()}{title_tail}").create(admin_api)
    if data is None:  # the pinned example searches for the wildcard-laden tail itself
        needle = title_tail
    else:
        start = data.draw(st.integers(0, len(book.title) - 1), label="start")
        end = data.draw(st.integers(start + 1, len(book.title)), label="end")
        needle = book.title[start:end]
    found: set[int] = set()
    page = 1
    while True:
        response = api.search(needle, page=page, page_size=50)
        assert response.status_code == 200, response.text
        body = response.json()
        found.update(item["id"] for item in body["items"])
        if book.id in found or page * 50 >= body["total"]:
            break
        page += 1
    assert book.id in found, f"searching {needle!r} did not find {book.title!r}"


# Integers far outside SQLite's signed 64-bit range included on purpose (BUG-005).
any_int = st.one_of(
    st.integers(),
    st.sampled_from([0, -1, 2**63 - 1, 2**63, 10**18, 10**20, -(2**63) - 1]),
)


@LIVE
@given(number=any_int)
@example(number=10**20)
@example(number=10**18)  # small enough for SQLite, but (page - 1) * page_size overflows
def test_ids_and_page_numbers_never_cause_a_500(
    api: BookshopApi, user_api: BookshopApi, number: int
) -> None:
    responses = {
        "GET /api/books?page": api.http.get("/api/books", params={"page": number}),
        "GET /api/books/{id}": api.get_book(number),
        "GET /books?page": api.http.get("/books", params={"page": number}),
        "GET /books/{id}": api.http.get(f"/books/{number}"),
        "PUT /api/cart/items/{id}": user_api.set_quantity(number, 1),
        "DELETE /api/cart/items/{id}": user_api.remove_item(number),
        "GET /api/orders/{id}": user_api.order(number),
    }
    server_errors = {name: r.status_code for name, r in responses.items() if r.status_code >= 500}
    assert not server_errors, f"{number}: {server_errors}"


@pytest.fixture(scope="module")
def tagged_books(admin_api: BookshopApi) -> tuple[str, list[int]]:
    """23 books sharing a unique tag, so paging is stable even on a shared server."""
    tag = f"pagetag{unique_suffix()}"
    ids = [BookBuilder().titled(f"{tag} volume {i:02d}").create(admin_api).id for i in range(23)]
    return tag, ids


@LIVE
@given(page_size=st.integers(1, 50))
def test_pages_partition_the_result_set(
    api: BookshopApi, tagged_books: tuple[str, list[int]], page_size: int
) -> None:
    tag, ids = tagged_books
    pages = -(-len(ids) // page_size)
    seen: list[int] = []
    for page in range(1, pages + 1):
        body = api.search(tag, page=page, page_size=page_size).json()
        assert body["total"] == len(ids)
        assert len(body["items"]) == min(page_size, len(ids) - (page - 1) * page_size)
        seen += [b["id"] for b in body["items"]]
    assert seen == ids, "pages dropped, repeated or reordered books"
    assert api.search(tag, page=pages + 1, page_size=page_size).json()["items"] == []


@pytest.fixture(scope="module")
def stocked_book(admin_api: BookshopApi) -> CreatedBook:
    return BookBuilder().with_stock(7).create(admin_api)


# Any JSON value a client could send, including what Python's json module emits for
# NaN/Infinity and lone surrogates (BUG-010) and booleans (lax int coercion).
any_json_scalar = st.one_of(
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.booleans(),
    st.none(),
    st.text(alphabet=st.one_of(st.characters(), st.characters(categories=["Cs"])), max_size=10),
)


@LIVE
@given(quantity=st.integers(-1_000, 1_000))
def test_cart_quantity_is_validated_never_500(
    user_api: BookshopApi, stocked_book: CreatedBook, quantity: int
) -> None:
    response = user_api.set_quantity(stocked_book.id, quantity)
    if quantity < 0 or quantity > 99:
        assert response.status_code == 422
    elif quantity > stocked_book.stock:
        assert response.status_code == 409
    else:
        assert response.status_code == 200
        lines = response.json()["items"]
        assert sum(line["quantity"] for line in lines) == quantity


@LIVE
@given(quantity=any_json_scalar)
@example(quantity=float("nan"))
@example(quantity=float("-inf"))
@example(quantity=True)
def test_cart_quantity_of_any_json_type_never_500s(
    user_api: BookshopApi, stocked_book: CreatedBook, quantity: object
) -> None:
    """Only a JSON integer is a quantity; every other value is a 422, never a 500."""
    response = user_api.send_raw_json(
        "PUT", f"/api/cart/items/{stocked_book.id}", {"quantity": quantity}
    )
    is_int = isinstance(quantity, int) and not isinstance(quantity, bool)
    if not is_int or not 0 <= quantity <= 99:
        assert response.status_code == 422, response.text
        assert_matches_schema(response.json(), "error")
    else:
        assert response.status_code == (409 if quantity > stocked_book.stock else 200)


# Strings that include lone surrogates, which Hypothesis's default alphabet never draws.
hostile_text = st.text(
    alphabet=st.one_of(st.characters(), st.characters(categories=["Cs"])), max_size=140
)
valid_username = st.from_regex(r"[A-Za-z0-9_.-]{3,32}", fullmatch=True)


@LIVE
@given(
    username=st.one_of(valid_username, hostile_text, any_json_scalar),
    password=st.one_of(st.text(min_size=8, max_size=128), hostile_text, any_json_scalar),
)
@example(username="valid_name", password="abcdefgh\ud800")  # BUG-010
@example(username="demo", password="long-enough-pw")  # always a 409: seeded user
def test_registration_never_500s(api: BookshopApi, username: object, password: object) -> None:
    response = api.send_raw_json("POST", "/api/users", {"username": username, "password": password})
    assert response.status_code in {201, 409, 422}, response.text


@LIVE
@given(
    prefix=st.from_regex(r"[A-Za-z0-9_.-]{0,20}", fullmatch=True),
    password=st.one_of(st.text(max_size=140), hostile_text),
)
@example(prefix="", password="abcdefgh\ud800")
def test_valid_usernames_register_exactly_when_the_password_is_valid(
    api: BookshopApi, prefix: str, password: str
) -> None:
    """Reaches the success path (PBKDF2 + INSERT) that random usernames almost never hit.

    The unique suffix keeps every username valid (3-32 characters) and unused, so the
    only thing that decides 201 versus 422 is the password: 8-128 characters, and no
    lone surrogates, because those cannot be encoded as UTF-8.
    """
    username = f"{prefix}_{unique_suffix()}"
    response = api.send_raw_json("POST", "/api/users", {"username": username, "password": password})
    has_surrogate = any(0xD800 <= ord(ch) <= 0xDFFF for ch in password)
    if 8 <= len(password) <= 128 and not has_surrogate:
        assert response.status_code == 201, response.text
        login = api.send_raw_json(
            "POST", "/api/auth/token", {"username": username, "password": password}
        )
        assert login.status_code == 200, login.text
    else:
        assert response.status_code == 422, response.text
