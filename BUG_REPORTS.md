# assay bug reports: defects found in the bookshop SUT

The twelve bookshop defects below are fixed and covered by the named regression tests. The reports record the failing behaviour, fix and test coverage. Environment for every report: local SUT started by the `sut` fixture (`uvicorn sut.app:create_app --factory`), Python 3.11, Chromium 141 (Playwright 1.56), Linux x86_64.

Severity scale: **Critical** (data loss, security), **High** (core flow broken), **Medium** (wrong results or a WCAG A/AA failure on a user-facing page), **Low** (edge-case input, small impact).

---

## BUG-001: Search treats `%` and `_` as wildcards and returns books that do not match

| Field | Value |
|---|---|
| Severity | Medium |
| Component | `sut/services.py` → `search_books` |
| Reproduction | Hypothesis property test `tests/api/test_api_properties.py::test_search_never_errors_and_only_returns_matches` |
| Status | Fixed |

**Steps to reproduce**
1. Start the SUT with the seed data.
2. Send `GET /api/books?q=%25` (the search text is `%`). Searching for `_` behaves the same way.

**Expected:** No results, because no title or author contains a literal `%` character.

**Actual:** `200` with `total: 20`, so every seeded book was returned. `q=a%e` returned 16 books.

**Root cause:** The user's text was placed directly into a SQL `LIKE '%…%'` pattern. The query was parameterised, so this was not SQL injection, but `%` and `_` kept their wildcard meaning.

**Fix:** `escape_like()` now escapes `\`, `%` and `_`, and the query uses `LIKE ? ESCAPE '\'`.

**Regression tests:** `@example(q="%")` and `@example(q="_")` on the property test, `tests/api/test_catalogue_api.py::test_like_wildcards_are_matched_literally`, `::test_titles_containing_wildcards_are_still_findable`, and `tests/unit/test_search_escaping.py`.

**Coverage limit:** A property-test run with 60 random examples can omit a bare `%`. The `@example` pins check this case on every run instead of depending on chance.

---

## BUG-002: A NUL character in the search text makes the search match every book

| Field | Value |
|---|---|
| Severity | Low |
| Component | `sut/services.py` → `search_books` |
| Reproduction | Hypothesis property test `tests/unit/test_search_escaping.py::test_escaped_like_agrees_with_python_substring` (falsifying example `needle='\x00', haystack=''`), then confirmed through the API |
| Status | Fixed |

**Steps to reproduce**
1. `GET /api/books?q=%00zzz` (the search text is NUL followed by `zzz`).

**Expected:** No results, or a validation error.

**Actual:** `200` with `total: 20`. SQLite reads a `LIKE` pattern only up to the first NUL, so the pattern shrank to `%` and matched everything.

**Fix:** `search_books` rejects text containing NUL with `InvalidInput`. The API returns `400 {"detail": "search text must not contain NUL characters"}`, and the HTML page shows the message as an alert.

**Regression tests:** `tests/unit/test_search_escaping.py::test_search_rejects_nul_characters` and `@example(q="\x00zzz")` on the API property test, which now expects a 400 for any input containing NUL.

---

## BUG-003: Unknown page URLs show raw JSON to browser users (WCAG failures)

| Field | Value |
|---|---|
| Severity | Medium |
| Component | `sut/app.py` (default 404 handling) |
| Reproduction | axe-core scan `tests/a11y/test_accessibility.py::test_public_pages_have_no_axe_violations[/nope]` |
| Status | Fixed |

**Steps to reproduce**
1. In a browser, open `http://<host>/nope`.

**Expected:** An HTML "Page not found" page that uses the site layout, with a `<title>`, `lang="en"` and a link back to the catalogue.

**Actual:** The browser showed FastAPI's raw JSON `{"detail":"Not Found"}`. axe reported two **serious** violations: `document-title` (the page has no `<title>`) and `html-has-lang` (the `<html>` element has no `lang`). A screen-reader user gets no page title and no language.

**Fix:** A `StarletteHTTPException` handler renders `not_found.html` for 404s when the client accepts `text/html` and the path is not under `/api/`. API clients still get the JSON error contract.

**Regression tests:** The `/nope` case of the axe scan, `tests/api/test_catalogue_api.py::test_browsers_get_html_errors_but_api_clients_get_json`, and `::test_unknown_api_route_is_json_even_for_browsers`.

---

## BUG-004: Malformed parameters on HTML pages show a raw JSON 422 error

| Field | Value |
|---|---|
| Severity | Low |
| Component | `sut/app.py` (default request-validation handling) |
| Reproduction | axe-core scan `test_public_pages_have_no_axe_violations[/books?page=abc]` and `[/books/abc]` |
| Status | Fixed |

**Steps to reproduce**
1. In a browser, open `/books?page=abc` or `/books/abc`.

**Expected:** An HTML error page saying the link is not valid.

**Actual:** A raw JSON `422` validation body, with the same axe `document-title` and `html-has-lang` violations as BUG-003.

**Fix:** A `RequestValidationError` handler renders `bad_request.html` with status 400 for browser requests outside `/api/`. API clients still get the standard 422 JSON.

**Regression tests:** The two axe scan cases above, plus the `/books/abc` and `/books?page=x` cases of `test_browsers_get_html_errors_but_api_clients_get_json`.

---

## BUG-005: Ids and page numbers beyond SQLite's 64-bit range crash the server with a 500

| Field | Value |
|---|---|
| Severity | Medium |
| Component | `sut/api.py`, `sut/web.py`, `sut/services.py` (every integer path or query parameter) |
| Reproduction | HTTP probe script |
| Status | Fixed |

**Steps to reproduce**
1. `GET /api/books/100000000000000000000` (10^20). The same happens with `GET /api/books?page=10^20`, `GET /books?page=10^20`, `GET /books/10^20`, `PUT /api/cart/items/10^20` and `GET /api/orders/10^20`.
2. `GET /api/books?page=1000000000000000000` (10^18). This page number fits in SQLite, but `OFFSET = (page - 1) * page_size` does not.

**Expected:** `422` (or `404`/`400` for HTML pages). A request parameter must never crash the server.

**Actual:** `500 Internal Server Error` on all 7 requests. The SUT log showed 7 tracebacks ending in `OverflowError: Python int too large to convert to SQLite INTEGER`. The connection was also reset.

**Root cause:** FastAPI parses any size of integer into a Python `int`, but SQLite's `INTEGER` is a signed 64-bit value. Only `page >= 1` was checked, with no upper bound.

**Coverage requirement:** The "never 500" property must generate ids and page numbers as well as search text, cart quantities and registration data.

**Fix:** The API declares ids as `Path(ge=1, le=2**63 - 1)` and `page` as `Query(ge=1, le=10_000)`. The service layer also checks ids (`_valid_id`) and pages (`MAX_PAGE`), so the HTML pages answer `404` for unknown ids and `400` for bad page numbers.

**Regression tests:** `tests/api/test_api_properties.py::test_ids_and_page_numbers_never_cause_a_500` (Hypothesis over unbounded integers on 7 endpoints, with `@example(10**20)` and `@example(10**18)`), `tests/unit/test_services.py::test_ids_outside_the_sqlite_range_are_not_found`, `tests/api/test_html_forms.py::test_html_search_rejects_out_of_range_pages` and `::test_cart_forms_report_unknown_books_as_404`.

---

## BUG-006: A non-ASCII admin token crashes the admin check with a 500

| Field | Value |
|---|---|
| Severity | Medium (any anonymous client could trigger a server error in the authorization code) |
| Component | `sut/api.py` → `require_admin` |
| Reproduction | HTTP probe script |
| Status | Fixed |

**Steps to reproduce**
1. `POST /api/books` with the header `X-Admin-Token: \xe9` (a single non-ASCII byte).

**Expected:** `403 {"detail": "admin token required"}`.

**Actual:** `500`. The log showed `TypeError: comparing strings with non-ASCII characters is not supported`. Starlette decodes header bytes as Latin-1, and `hmac.compare_digest(str, str)` only accepts ASCII strings.

**Fix:** The token and the expected value are compared as bytes: `hmac.compare_digest(x_admin_token.encode(), expected.encode())`.

**Regression test:** the `b"\xe9t\xe9"` case of `tests/api/test_auth_api.py::test_creating_books_requires_the_admin_token`.

---

## BUG-007: The "Add to cart" form accepts zero and negative quantities and removes copies

| Field | Value |
|---|---|
| Severity | Medium |
| Component | `sut/services.py` → `add_to_cart`, `sut/web.py` → `cart_add` |
| Reproduction | HTTP probe script |
| Status | Fixed |

**Steps to reproduce**
1. Sign in and add 3 copies of a book (`POST /cart/add`, `quantity=3`).
2. Post the same form directly with `quantity=-2`, bypassing the input's `min="1"`.

**Expected:** `400` with a validation message, and the cart still holds 3 copies.

**Actual:** `303` redirect to the cart, which now held 1 copy. Only the browser's `min` attribute limited the field. The server computed `current + quantity` without checking the sign. An invalid quantity was also rendered with status 409 instead of 400.

**Fix:** `add_to_cart` rejects quantities outside 1-99 with `InvalidInput`. The HTML routes map `InvalidInput` to 400 and `Conflict` to 409, the same as the JSON API.

**Regression tests:** `tests/api/test_html_forms.py::test_cart_add_rejects_out_of_range_quantities[-2/0/100]` (checks that the cart is unchanged) and `tests/unit/test_services.py::test_add_to_cart_rejects_non_positive_or_huge_quantities`.

---

## BUG-008: Concurrent "Add to cart" requests lose updates

| Field | Value |
|---|---|
| Severity | Medium |
| Component | `sut/services.py` → `add_to_cart` |
| Reproduction | Concurrent-request probe script |
| Status | Fixed |

**Steps to reproduce**
1. Sign in, with the book not in the cart.
2. Send 8 `POST /cart/add` requests with `quantity=1` for the same book at the same moment (8 threads released by a barrier).

**Expected:** The cart holds 8 copies.

**Actual:** In 5 trials the cart held 1, 1, 1, 1 and 2 copies. `add_to_cart` read the current quantity outside any transaction and then wrote `current + 1`, so concurrent requests overwrote each other. Checkout re-checks stock, so this could not oversell, but the cart was wrong.

**Fix:** The read and the write now run inside one `BEGIN IMMEDIATE` transaction (`_write_cart_quantity` is shared with `set_cart_quantity`). After the fix, the same 5 trials each gave 8.

**Regression test:** `tests/db/test_persistence.py::test_concurrent_adds_to_the_same_cart_are_not_lost`.

---

## BUG-009: Login answers faster for unknown usernames, which reveals which usernames exist

| Field | Value |
|---|---|
| Severity | Low |
| Component | `sut/services.py` → `login` |
| Reproduction | Login timing probe script |
| Status | Fixed |

**Steps to reproduce**
1. Time 5 `POST /api/auth/token` calls with a wrong password for `demo` (an existing user) and 5 for `no_such_user_zz`.

**Expected:** The response time does not depend on whether the username exists. The message is already the same for both cases.

**Actual:** On average, 128 ms for the existing user and 72 ms for the unknown one, measured in a shared, loaded 4-vCPU Linux container. For an unknown username, `login` returned before running the 100,000-iteration PBKDF2 check.

**Fix:** When no user matches, `login` verifies the password against a fixed dummy hash, so both failures cost one PBKDF2 run. After the fix the probe measured 275 ms and 226 ms. That is a noisy single measurement on a machine with a load average of about 20, so the regression test checks the cause (the number of hash checks) instead of timing.

**Regression test:** `tests/unit/test_services.py::test_unknown_usernames_cost_a_password_hash_too`.

---

## BUG-010: Request bodies with lone surrogates or non-finite numbers crash the 422 error response with a 500

| Field | Value |
|---|---|
| Severity | Medium (any anonymous client could trigger a server error, the same "never 500" class as BUG-005 and BUG-006) |
| Component | `sut/app.py` → `validation_error` (FastAPI's default request-validation handler) |
| Reproduction | HTTP probe script |
| Status | Fixed |

**Steps to reproduce**
1. `POST /api/users` with the raw body `{"username": "probe_x", "password": "abcdefgh\ud800"}` (a lone UTF-16 surrogate escape).
2. The same happens for a surrogate username or password on `POST /api/auth/token`, a surrogate title on `POST /api/books`, and `PUT /api/cart/items/1` with `{"quantity": NaN}`, `-Infinity` or `1e400`.

**Expected:** `422` with a validation error.

**Actual:** `500 Internal Server Error` on all 7 requests, and the connection was reset. The SUT log had 14 traceback blocks: `UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800' ... surrogates not allowed` and `ValueError: Out of range float values are not JSON compliant`.

**Root cause:** Python's JSON parser accepts these values, and pydantic correctly rejects them. But FastAPI's default 422 handler copies each rejected `input` into the response, and Starlette's `JSONResponse` encodes with `ensure_ascii=False` and `allow_nan=False`. The error response itself could not be encoded.

**Coverage requirement:** httpx's `json=` refuses NaN and surrogates, and Hypothesis's default text alphabet never draws surrogates. Tests must send raw bytes for those inputs and explicitly generate valid usernames. Sampling arbitrary text produced only 14 pattern-valid usernames in 500 examples; a 60-example budget can therefore mostly exercise the 422 path.

**Fix:** For API requests the handler now returns only `type`, `loc` and `msg` of each error, never the rejected `input` (or `ctx`). The `error.json` contract forbids any other key, so an echo of the input fails the contract tests.

**Regression tests:** `tests/api/test_raw_json_bodies.py` (the 7 bodies above plus malformed JSON, sent as raw bytes), and three properties in `tests/api/test_api_properties.py` that send raw JSON with `json.dumps` semantics: `test_registration_never_500s` (usernames from the valid pattern mixed with surrogate-laden text and non-string JSON values), `test_valid_usernames_register_exactly_when_the_password_is_valid` (reaches the 201 path and logs in), and `test_cart_quantity_of_any_json_type_never_500s` (integers, floats including NaN and infinities, booleans, null and strings). Against the unfixed SUT all of them failed.

---

## BUG-011: Usernames are unique only case-sensitively, so look-alike accounts can be registered

| Field | Value |
|---|---|
| Severity | Low (impersonation risk: `DEMO` next to `demo`) |
| Component | `sut/db.py` → `users.username` |
| Reproduction | HTTP probe script |
| Status | Fixed |

**Steps to reproduce**
1. `POST /api/users` with `{"username": "DEMO", "password": "abcdefgh1"}` while the seeded `demo` user exists.

**Expected:** `409`, because `DEMO` and `demo` name the same account to a person.

**Actual:** `201 {"id": 3, "username": "DEMO"}`.

**Fix:** The column is now `username TEXT NOT NULL UNIQUE COLLATE NOCASE`. Usernames are restricted to ASCII letters, digits and `_.-`, so SQLite's ASCII-only `NOCASE` covers every allowed name. Login lookups use the same collation, so `DEMO` signs in as `demo`. An existing database keeps the old column definition (there are no migrations; see the README limitations).

**Regression tests:** `tests/api/test_auth_api.py::test_usernames_are_unique_regardless_of_case` and `tests/unit/test_services.py::test_usernames_differing_only_in_case_conflict`.

---

## BUG-012: The cart API accepts `true`, `2.0` and `"2"` as quantities

| Field | Value |
|---|---|
| Severity | Low |
| Component | `sut/api.py` → `QuantityIn` |
| Reproduction | HTTP probe script |
| Status | Fixed |

**Steps to reproduce**
1. Sign in and send `PUT /api/cart/items/1` with `{"quantity": true}`.

**Expected:** `422`: the contract says the quantity is a JSON integer.

**Actual:** `200`, and the cart held 1 copy. Pydantic's default lax mode converted `true` to 1 (and `2.0` or `"2"` to 2).

**Fix:** `quantity` is declared with `Field(strict=True)`, so only a JSON integer is accepted.

**Regression tests:** `tests/api/test_cart_orders_api.py::test_quantity_must_be_a_json_integer` (`true`, `false`, `2.0`, `"2"`, `null`, `[2]`) and the `quantity=True` example of `test_cart_quantity_of_any_json_type_never_500s`.

---

## Test defects (not product bugs)

These corrected test defects concern expectations, fixture scope and isolation. The product behaviour was correct in each case.

- **Seed price total:** An incorrect expectation of 30,224 cents caused a test failure. The correct total is 32,480 cents, matching `sut/seed_data.py`; `tests/db/test_persistence.py::test_seed_data_is_deterministic` asserts that value.
- **Fixture visibility:** A UI-only `signed_in_page` fixture caused accessibility tests to error. The fixture lives in `tests/conftest.py`, where both UI and accessibility tests can use it.
- **Pagination isolation:** Paging through the whole catalogue allowed concurrent book creation to change totals mid-test on a shared server. The API and UI pagination tests query their own uniquely tagged books, including when targeting docker compose.
