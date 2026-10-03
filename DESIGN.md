# assay design notes

## Goals

- Cover API and contract testing, property-based testing, DB checks, a UI Page Object Model, accessibility, Selenium, load testing, CI and Docker.
- Keep framework components small and readable.
- Make results trustworthy: passing runs check product behaviour, and failing runs retain evidence.

## Key decisions and trade-offs

### Ship the system under test in the repository
**Decision:** The suite tests `sut/`, a bookshop with about 1,200 lines of Python (FastAPI and SQLite). It does not test a public demo site.
**Why:** Tests need a deterministic, local target that can be reset. Public demo sites change and rate-limit. Including the SUT allows fixes and regression tests to use the same repository.
**Trade-off:** The product and tests share an author, so their assumptions may share blind spots. Independent checks reduce that risk: hand-written schemas, Hypothesis-generated inputs, axe-core rules and SQL checks of persisted state, rather than only re-reading the SUT's own logic.

### Run the SUT as a real subprocess, not FastAPI's TestClient
**Decision:** `qa_suite/server.py` starts `uvicorn` on a free port and polls `/healthz` until it responds.
**Why:** Playwright, Selenium and Locust need a real socket, so a real server is required for those layers anyway, and one code path for every test type is simpler. It also tests the app the way it runs in production: the real uvicorn server, HTTP parsing, the process boundary, and a separate process writing to the SQLite file that `DbProbe` reads. (TestClient does not serialise requests: sync endpoints still run in AnyIO's threadpool, so it could drive the concurrency tests too. The reason is realism, not concurrency.)
**Trade-off:** Startup costs about 1 s per session (per worker). The alternative, `TestClient`, would be faster for pure API tests but is not used here. `free_port()` releases the port before uvicorn binds it, so another worker's server can take it in between. Each `SutServer` therefore passes a random instance id (`BOOKSHOP_INSTANCE_ID`) that `/healthz` echoes in an `X-Instance-Id` header, and `wait_until_healthy` only accepts its own id. If uvicorn exits during startup (an import error, or a lost port race), the poll sees the exited process and fails at once with the log tail, instead of polling for 30 s or, worse, testing against another worker's server. Passing a pre-bound socket to uvicorn (`--fd`) would remove the race entirely; the id check was simpler and also catches a stale server left on a port.

### One server and database per xdist worker, plus builders instead of shared fixtures
**Decision:** The session fixture creates a temporary SQLite file per worker. Tests create their own users and books through `UserBuilder` and `BookBuilder`, which generate unique usernames and ISBNs.
**Why:** It keeps tests independent of each other and of test order, so they can run in parallel. The same tests also pass against a shared, long-lived server such as the docker compose run, because no test assumes it owns the catalogue. Pagination tests query uniquely tagged books to avoid concurrent catalogue changes; see [BUG_REPORTS.md](BUG_REPORTS.md).
**Alternatives:** Resetting the database between tests through a test-only endpoint is simpler but forces serial execution. Transaction rollback per test does not work across a process boundary.

### Hand-written JSON Schemas, not the app's own OpenAPI document
**Decision:** The schemas in `qa_suite/schemas/` are written by hand from the intended contract and use `additionalProperties: false`.
**Why:** Validating against the server's own generated OpenAPI would be circular: any change to the response would update both sides and still pass. Separate contracts catch accidental field additions, renames and type changes.
**Trade-off:** The schemas must be maintained by hand. A consumer-driven tool such as Pact or Schemathesis would scale better across many services.

### Property-based tests against the live server, with a capped example budget
**Decision:** `max_examples=60` and `deadline=None`. Bugs that were found get pinned with `@example`.
**Why:** HTTP round trips are slow, so 60 examples keeps each property test to a few seconds and the full suite at roughly a minute with 2 workers. Pinning matters because Hypothesis is random: BUG-001 was missed on one run and found on the next.
**Strategies must reach every path.** Arbitrary text rarely matches the username pattern, and Hypothesis's default alphabet never draws lone surrogates. The properties mix pattern-valid usernames (`st.from_regex`) with hostile text and non-string JSON values, send raw JSON the way `json.dumps` writes it (NaN, Infinity, `\ud800` escapes), and one property has an exact oracle (valid username plus valid password must give 201 and a working login).

### Read-only `DbProbe` for state assertions
**Decision:** DB tests open the SQLite file with `mode=ro` and only run `SELECT`.
**Why:** If a test could write to the database it was checking, it could hide a bug. Reading only also keeps the DB checks valid against the containerised SUT, where the file is a bind mount.

### Selenium is opt-in
**Decision:** The Selenium tests are skipped unless you run `-m selenium`. They duplicate three Playwright flows. If no matching chromedriver can be obtained they skip with a "NOT RUN" reason locally, but the CI job sets `SELENIUM_REQUIRED=1`, which turns that skip into a failure so the job cannot go green without running anything.
**Why:** Selenium Manager may download a driver, and default runs should make no network calls. Playwright is the primary UI tool because it waits automatically, records traces and isolates browser contexts. The Selenium variants use explicit waits, as many existing suites do.

### The load test has a gate that can fail
**Decision:** Locust only measures. `qa_suite/load_gate.py`, a pure and unit-tested function, decides pass or fail. A minimum number of requests prevents a "pass" when almost nothing ran.
**Why:** A load test that only prints numbers never fails CI. Keeping the thresholds in one small function makes them easy to review.
**Trade-off:** A 30 s run of 20 users on a CI runner is a smoke test for regressions, not a capacity test.

### Detect flaky tests instead of retrying them
**Decision:** `qa_suite/flaky.py` reruns the whole selection N times and classifies each test from its JUnit output. There is no `pytest-rerunfailures`.
**Why:** Automatic retries make flaky and broken tests look green. The detector reports a non-deterministic test as **flaky**, separately from a reproducible **stable-fail**, and both exit 1. A test that passes in one run and is skipped in another is also flaky, because a nondeterministic skip hides whether it works. A test absent from a run (for example after a worker crash or a collection error) is recorded as **missing** in that run, never as passed. The detector also checks pytest's own exit code: a run that ended with code 2-5 (interrupted, internal error, usage error, nothing collected) or wrote no JUnit file (or an unreadable one) is listed as a **broken run**, and broken runs or an empty report exit 2. Usage errors such as `--no-such-option` must produce a broken-run result, not an empty passing report.

### Error pages: HTML for browsers, JSON for the API
The handler checks `Accept: text/html` and that the path is not under `/api/`. That keeps the API error contract stable while browsers get an accessible page.

### SQLite concurrency
Overselling is prevented by checkout's conditional `UPDATE books SET stock = stock - ? WHERE id = ? AND stock >= ?` and its row-count check: checkout never decrements from a value it read earlier, so the database decides atomically whether enough stock is left, and a `Conflict` rolls the whole order back. The 8-thread race test checks it: exactly 2 orders for 2 copies, and stock ends at 0.

`BEGIN IMMEDIATE` does a different job. It takes the write lock before the transaction's first read, so a transaction that reads and then writes waits (up to the 10 s `busy_timeout`) for other writers. With a plain deferred `BEGIN` in WAL mode, such a transaction starts as a reader. If another writer commits first, its snapshot is stale, SQLite cannot upgrade it to a writer, and it fails at once with `SQLITE_BUSY` ("database is locked"), which the busy timeout does not retry. In a mutation check with `BEGIN` instead of `BEGIN IMMEDIATE`, both race tests failed in 3 of 3 runs, with 500 "database is locked" responses (11-13 log lines per run) rather than oversold stock. For "add to cart", which is a read-modify-write, the immediate lock also makes the read and the write atomic. Before that fix, 8 simultaneous adds left 1 or 2 copies (BUG-008). WAL mode lets reads continue during writes.

### Validate every input on the server, at the boundary
Ids are bounded to SQLite's 64-bit range and page numbers to 10,000 in the API signatures (so clients get a 422), and the service layer checks them again (so the HTML pages answer 404/400). Quantities are checked in the service, not only by the HTML `min` attribute, and the JSON quantity is a strict integer, so `true` or `2.0` is a 422 (BUG-012). Usernames are unique case-insensitively (`COLLATE NOCASE`, BUG-011). The 422 body lists only each error's `type`, `loc` and `msg`: echoing the rejected input back made a lone surrogate or a NaN crash the error response itself (BUG-010). Regression cases for BUG-005, BUG-007 and BUG-010 to BUG-012 cover ids, page numbers, crafted form posts, surrogates and non-integer JSON. A "never 500" property cannot cover these inputs unless its strategies generate them. Property tests cover only the inputs their strategies generate; review those strategies alongside the code.

### Sessions and redirects
Session tokens are random 256-bit values. The database stores only their SHA-256 digest with a 12-hour `expires_at`, so a copy of the database contains no usable tokens. Each login also deletes expired session rows, so the table does not grow without bound. Login runs PBKDF2 even for unknown usernames, against a dummy hash, so timing does not reveal which usernames exist (BUG-009). The post-login `next` parameter must be a same-site path: `_safe_next` refuses `//host`, anything with a scheme or host, and any backslash or control character, because browsers read `/\host` as `//host`. Starlette's `RedirectResponse` happened to percent-encode the backslash, but the check does not depend on that.

## Alternatives considered

| Option | Why not (here) |
|---|---|
| Robot Framework or Behave (BDD) | They add a DSL layer. Plain pytest is easier to maintain and is what most Python teams use. |
| `pytest-rerunfailures` | It hides flakiness; see the detector decision above. |
| k6 for load | It would need a separate JS toolchain. Locust keeps everything in Python and reuses the framework's server fixture. |
| Testcontainers | It would be elegant, but docker compose is already needed for CI. The env-var switch (`SUT_BASE_URL`) lets the same suite target either a subprocess or a container. |
| Schemathesis (OpenAPI fuzzing) | It generates from the server's own spec. Hand-written schemas provide independent contracts, and targeted Hypothesis strategies control input coverage. Schemathesis remains planned as an additional fuzzing pass. |

## Planned work

1. Run the Playwright suite on Firefox and WebKit through a CI matrix (`--browser firefox --browser webkit`).
2. Add Schemathesis against `/openapi.json` as a second, broader fuzzing pass. It generates every parameter of every route, so it would likely have found BUG-005 (huge ids) without a hand-written strategy.
3. Add visual regression with Playwright `to_have_screenshot` for the cart and order pages.
4. Add CSRF tokens to the HTML forms, then test that requests without a token are rejected.
5. Run the flaky detector nightly over the whole suite (not just smoke) and track flaky tests over time.
6. Collect coverage of the SUT during the API run (`coverage run -m uvicorn …`) to find untested branches.
