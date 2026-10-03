# assay test record

- **Date:** 2026-10-03
- **Environment:** shared 4-vCPU Linux container (x86_64, Ubuntu 24.04), Python 3.11.15, uv 0.8.17, Docker Engine 29.6.2 with Compose v5.3.1. Other jobs share the machine (load average 7-24 during the measurements), so timings are noisy.
- **Browsers:** pre-installed Playwright Chromium 141.0.7390.37 (revision chromium-1194, used through Playwright 1.56.0). Selenium uses chromedriver 141.0.7390.122 supplied by Selenium Manager; the version 147 driver on PATH does not match.
- **Key package versions:** fastapi 0.142.2, uvicorn 0.54.0, pytest 9.1.1, pytest-xdist 3.8.0, pytest-html 4.2.0, pytest-playwright 0.9.0, selenium 4.50.0, hypothesis 6.168.3, jsonschema 4.26.0, locust 2.46.6, axe-core 4.12.1 (bundled with axe-playwright-python 0.1.8), ruff 0.16.10.

Commands use the project root. The original table records the shared 4-vCPU Linux container described above, before the navigation regressions were added. The local recheck below records the current checkout separately. Docker and CI configurations are validated locally; the project has never been deployed.

| # | Command | Result | Key output |
|---|---|---|---|
| 1 | `uv sync` (clean environment, no existing dependencies, caches or generated outputs) | PASS | Project-local `.venv` populated from `uv.lock` |
| 2 | `uv run ruff check .` | PASS | `All checks passed!` |
| 3 | `uv run ruff format --check .` | PASS | `58 files already formatted` (53 `.py` files and 5 `.md` files) |
| 4 | `uv run pytest -n 2 --html=reports/report.html --self-contained-html --junitxml=reports/junit.xml` | PASS | `228 passed, 3 skipped in 75.12s`. Second run: `228 passed, 3 skipped in 74.16s`. The 3 skips are the opt-in Selenium tests. Artifacts: HTML report (223 KB) and JUnit XML. |
| 5 | `uv run pytest` (serial, no xdist) | PASS | `228 passed, 3 skipped in 84.62s` |
| 6 | `uv run pytest tests/<dir>` and `-m <marker>` with `--collect-only -q` | PASS | 231 tests in total. By directory: unit 92, api 97, db 9, ui 18, a11y 12, selenium 3. By marker: contract 5, property 11, smoke 23, regression 43. |
| 7 | `CHROME_BINARY=/opt/pw-browsers/chromium-1194/chrome-linux/chrome SE_SKIP_DRIVER_IN_PATH=true SELENIUM_REQUIRED=1 uv run pytest -m selenium` | PASS | `3 passed, 228 deselected in 11.93s` |
| 8 | `SELENIUM_REQUIRED=1 uv run pytest -m selenium` without `CHROME_BINARY` (negative check: the default driver does not match the browser) | PASS (failed as intended) | `228 deselected, 3 errors`, exit code 1, `SELENIUM_REQUIRED=1 but no usable chromedriver for this browser (session not created: This version of ChromeDriver only supports Chrome version 147 ...)`. Without the flag the same check reports `3 skipped` with a "NOT RUN" reason. |
| 9 | Deliberately failing Playwright test (temporary test, not included in the suite) | PASS (evidence kept) | `1 failed`; artifacts: `test-results/playwright/<test>/trace.zip` and `test-failed-1.png` |
| 10 | `uv run python load/run_load.py --users 20 --spawn-rate 5 --duration 30s` (run twice) | PASS | Run 1: `{"requests": 858, "failures": 0, "p50_ms": 5, "p95_ms": 26, "p99_ms": 95, "rps": 28.6}`. Run 2: `{"requests": 862, "failures": 0, "p50_ms": 6, "p95_ms": 37, "p99_ms": 110, "rps": 28.8}`. Both results include `[load-gate] PASS` (load average 13-16). Other runs on the same container measure p95 27 and 34 ms, and 51-80 ms under heavier load: the recorded range is 26-80 ms depending on machine load. The 300 ms gate is the stable claim. |
| 11 | `LOAD_P95_MS=1 uv run python load/run_load.py --users 5 --spawn-rate 5 --duration 5s` (negative check of the gate) | PASS (gate failed the run as intended) | `[load-gate] FAIL: only 43 requests (< 100); p95 86 ms > 1 ms`, exit code 1 |
| 12a | `uv run python -m qa_suite.flaky --runs 3 --out reports/flaky -- -m smoke` (load average about 22) | FAIL (real nondeterminism reported) | `stable-pass: 22, flaky: 1`, exit code 1: `test_search_by_author[chromium]` outcomes: `failed failed passed`. Run 1: `Locator.click: Target crashed` (the Chromium renderer died); run 2: `Locator.click: Timeout 30000ms exceeded` waiting for the search button to be stable. |
| 12b | `uv run python -m qa_suite.flaky --runs 5 -- tests/ui -m smoke` and `uv run python -m qa_suite.flaky --runs 3 -- tests/ui -m smoke --tracing=on` | FAIL (same symptom class) | Invocation 1: 2 UI failures in run 1 only (30 s timeouts waiting for the page), then 4 clean runs. Invocation 2: runs 1-2 clean; in run 3 the SUT exits with code 1 before becoming healthy, with no output, and all 4 tests error. A bind conflict produces code 3 and `address already in use`, unlike this failure. The cause of the silent exit and renderer crash is unknown. Contention from concurrent browsers and servers on the shared machine is a suspected cause, not proven. |
| 12c | `uv run python -m qa_suite.flaky --runs 3 --out reports/flaky -- -m smoke` (load average 13-16) | PASS | `stable-pass: 23, stable-fail: 0, flaky: 0, skipped: 0`, exit code 0 |
| 13 | `uv run python -m qa_suite.flaky --runs 4 --out reports/flaky-demo -- examples/flaky_demo` | PASS (detector behaved correctly) | `stable-pass 1, stable-fail 1, flaky 1` (`passed failed passed failed`), exit code 1 |
| 14 | `uv run python -m qa_suite.flaky --runs 2 --out reports/flaky-negative-usage -- --no-such-option` and `... --out reports/flaky-negative-empty -- tests/unit -k no_such_test_name` (negative checks with separate report directories) | PASS (failed as intended) | Both exit 2 with `No test results were recorded: nothing was verified.` and a broken-runs table (pytest exit codes 4 and 5) |
| 15 | `docker build -t assay-sut .` | PASS | Image build: 17 s; size: 225 MB. |
| 16 | `HOST_UID=$(id -u) HOST_GID=$(id -g) SUT_PORT=18080 docker compose up -d --wait` (fresh `compose-data/`) | PASS | `Container assay-sut-1 Healthy`; `/healthz` answered 200 |
| 17 | `SUT_BASE_URL=http://127.0.0.1:18080 SUT_DB_PATH=compose-data/bookshop.sqlite3 uv run pytest -n 2` | PASS | `228 passed, 3 skipped in 66.30s`. DB tests read the bind-mounted SQLite file. Container log: 0 tracebacks. Cleanup: `docker compose down -v`. |
| 18 | `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` | PASS | 8 jobs parsed: lint, api, ui, accessibility, selenium, load-smoke, flaky-check, docker-compose |
| 19 | `SUT_PORT=8000 docker compose config -q` | PASS | Compose file is valid |
| 20 | `uv export --no-dev --no-hashes --format requirements-txt --no-emit-project` diffed against `requirements.txt` | PASS | Identical, ignoring comment lines (the same check the CI lint job runs) |
| 21 | HTTP probe for BUG-010 to BUG-012 against the unfixed and fixed SUT | PASS | Before: 7 raw-JSON requests (lone `\ud800` surrogate in a password, username or title; `NaN`, `-Infinity` or `1e400` as a quantity) returned 500, with 14 tracebacks in the SUT log (`UnicodeEncodeError ... surrogates not allowed`, `ValueError: Out of range float values are not JSON compliant`); `{"quantity": true}` returned 200; `POST /api/users {"username": "DEMO"}` returned 201 next to `demo`. After: 422 for all 8 and 409 for `DEMO`, 0 tracebacks. See BUG-010 to BUG-012. |
| 22 | Sensitivity check: regression tests against a copy with the BUG-010 to BUG-012 fixes reverted | PASS (tests failed as intended) | `21 failed, 35 passed` in the four affected API test files: every raw-JSON case, the three properties, `true`/`false`/`2.0`/`"2"` quantities, the case-insensitive username test, and the 422 contract tests (the error schema forbids an echoed `input`). |
| 23 | Mutation check: `BEGIN IMMEDIATE` replaced with a deferred `BEGIN` in a copy of the project, `pytest tests/db -k concurrent` run 3 times | PASS (tests failed as intended) | Both race tests failed 3 of 3 times with HTTP 500 "database is locked" (13, 13 and 11 log lines), not with oversold stock. This confirms the concurrency contract in `sut/db.py` and [DESIGN.md](DESIGN.md): the conditional UPDATE prevents overselling, and the immediate lock prevents SQLITE_BUSY failures. |
| 24 | GitHub Actions workflow run | NOT_RUN | This verification did not execute or inspect GitHub Actions. See the README status badge for current workflow status. The workflow is validated as YAML and its job commands are exercised locally (rows 2-20). Runner-specific `playwright install --with-deps` and Selenium Manager driver downloads are NOT_RUN. |
| 25 | Firefox and WebKit browsers | NOT_RUN | Only Chromium is pre-installed in the measurement environment; other browsers are NOT_RUN |
| 26 | Search-escaping strategy regression check: `pytest tests/unit/test_search_escaping.py -k agrees --hypothesis-seed=N` for N = 1..30, before and after the fix, then `uv run pytest -n 2` | PASS (after the fix) | Before: 3 of 30 seeds failed with `UnicodeEncodeError` (falsifying example `needle='\ud800'`). The needle strategy `st.characters(blacklist_characters='\x00')` can draw lone surrogates, which sqlite3 cannot encode, causing failures in about 10% of runs. The fixed strategy also excludes category `Cs`, consistent with `tests/api/test_api_properties.py`. After: 0 of 30 seeds failed; full suite `228 passed, 3 skipped in 48.94s`. |

Parallelism measurements on the same shared container: about 75 s with 2 xdist workers against 85 s serially; other runs record 60 s against 84 s, and 44.9 s against 46.8 s. These measurements do not establish a stable parallel speed-up.

## Bugs found by testing and fixed

[BUG_REPORTS.md](BUG_REPORTS.md) records twelve fixed SUT defects and three corrected test defects, with failing behaviour, fixes and regression coverage. The table includes fixed-SUT results as well as explicit before/after and mutation checks; failures and NOT_RUN results remain part of the record.


## Local recheck: 2026-10-03

Environment: macOS 27.0.1, arm64, Python 3.11.15, uv 0.11.21, locked project-local dependencies. Commands ran from the project root with `UV_CACHE_DIR=/private/tmp/assay-uv-cache` because the default cache is outside the writable sandbox. Dependency downloads failed DNS resolution; copying already cached packages to the writable temporary cache allowed offline installation without changing dependencies or `uv.lock`.

Changes verified: Selenium form submission waits for the submitted element to become stale and the response document to finish loading. Login then waits for the signed-in navigation or login error; cart submission waits for its added notice. Search can no longer accept the previous page's result count or read a partially parsed results table. Five deterministic navigation regressions model pending requests and partial HTML parsing, including empty results and rejected credentials. Unit-only URL fixtures prevent pytest-base-url's autouse check from starting the SUT for isolated unit runs.

| Command / check | Result | Evidence |
|---|---|---|
| `uv sync --locked --python 3.11` | BLOCKED | PyPI download failed DNS resolution. |
| `uv sync --locked --offline --python 3.11` after populating the temporary cache | PASS | Installed 77 locked packages into `.venv`; no lockfile or dependency changes. |
| `uv run ruff check . && uv run ruff format --check .` | PASS | `All checks passed!`; `59 files already formatted`. |
| `uv run pytest tests/unit -q` | PASS | `97 passed in 5.99s`, including all five navigation regressions. |
| Navigation sensitivity check: execute the original page-object source in memory, then run `tests/unit/test_selenium_pages.py` | PASS | All five new regression cases fail against the original implementation; the wrapper confirms pytest exit 1 as expected. Tracked source remains unchanged by this check. |
| `uv run pytest --collect-only -q` | PASS | 236 tests collected: 97 unit, 97 API, 9 DB, 18 UI, 12 accessibility, 3 Selenium. |
| `uv run pytest -q` | BLOCKED | Final run: `97 passed, 3 skipped, 136 errors in 6.29s`, exit 1. Live-server fixture cannot bind localhost: `PermissionError: [Errno 1] Operation not permitted`. The three existing Selenium skips remain opt-in; no tests were skipped or weakened to hide these errors. |
| `for i in 1 2 3 4 5; do uv run pytest -m selenium -q -p no:randomly || exit 1; done` | BLOCKED | Run 1: `233 deselected, 3 errors in 0.82s`, exit 1, from the same localhost bind denial before browser assertions. Loop stops at run 1; runs 2–5 did not execute. Used `SELENIUM_REQUIRED=1`, `CHROME_BINARY` pointing to cached Chromium 141, and `SE_CHROMEDRIVER` pointing to cached matching driver 141.0.7390.122. No skips counted as successful Selenium runs. |
| `uv run python load/run_load.py --users 20 --spawn-rate 5 --duration 30s` | BLOCKED | Localhost bind denied before Locust starts; no current latency or throughput measurements. |
| `uv run python -m qa_suite.flaky --runs 3 --out reports/flaky -- -m smoke` | BLOCKED | Three runs completed, exit 1; 1 stable-pass and 22 stable-fail due to localhost setup denial. This does not establish browser stability or app nondeterminism. |
| `uv export --no-dev --no-hashes --format requirements-txt --no-emit-project`, compare dependency lines with `requirements.txt` | PASS | Exact match ignoring comment lines, as in the lint CI job. |
| Parse `.github/workflows/ci.yml` with `yaml.safe_load` | PASS | Eight jobs parsed. Syntax validation does not establish runner success. |
| `SUT_PORT=8000 docker compose config -q` | PASS | Exit 0; Compose configuration valid. |
| `docker info --format '{{.ServerVersion}}'`; Docker build/start/container suite | BLOCKED | Permission denied accessing the existing Docker socket. Runtime Docker commands cannot proceed; no containers were created. |
| Tracked-file hygiene and `git diff --check` | PASS | No tracked build outputs, caches, reports, or runtime databases; existing `.gitignore` covers those outputs. Added `.editorconfig`; license unchanged. |
| Fresh-clone Quickstart end to end; browser downloads | BLOCKED | Network DNS resolution is unavailable, and local server execution is blocked as above. Existing cached dependencies enabled only the offline checks. |
| Remote GitHub workflow execution | NOT_RUN | No remote workflow was started or queried. |

**Outstanding validation:** run the full suite and five consecutive Selenium selections on a host that permits localhost and browser execution, then confirm all eight CI jobs. The earlier renderer crashes and silent server exit under contention cannot be investigated here. Historical Linux success is preserved above; it is not a passing result for this changed checkout. No deployment was performed.
