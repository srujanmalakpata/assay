"""Locust load scenario for the bookshop.

Two kinds of virtual user:
* Browser  (weight 3): anonymous catalogue searches and book pages, the hot read path.
* Shopper  (weight 1): logs in once, adds to cart, views the cart and checks out.

When the run ends, the results are checked against explicit thresholds
(qa_suite.load_gate) and Locust's exit code is set to 1 if any are breached, so a
CI job fails on a slow or erroring build. A JSON summary is written to
reports/load-summary.json.

    locust -f load/locustfile.py --headless -u 20 -r 5 -t 30s --host http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import random
import sys
import uuid
from pathlib import Path

from locust import HttpUser, between, events, task

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qa_suite.load_gate import LoadResult, Thresholds, evaluate, summary

SEARCH_TERMS = ["austen", "dickens", "the", "war", "bronte", "tolstoy", "island", "zzz"]
SEED_BOOK_IDS = list(range(1, 20))  # the seeded books with plenty of stock
SUMMARY_PATH = Path("reports/load-summary.json")


class LocalUser(HttpUser):
    abstract = True

    def on_start(self) -> None:
        # The SUT is local: never route its traffic through an HTTP(S)_PROXY from the env.
        self.client.trust_env = False


class Browser(LocalUser):
    weight = 3
    wait_time = between(0.2, 1.0)

    @task(3)
    def search_api(self) -> None:
        q = random.choice(SEARCH_TERMS)
        self.client.get("/api/books", params={"q": q}, name="/api/books?q=[term]")

    @task(2)
    def book_api(self) -> None:
        self.client.get(f"/api/books/{random.choice(SEED_BOOK_IDS)}", name="/api/books/[id]")

    @task(1)
    def search_page(self) -> None:
        q = random.choice(SEARCH_TERMS)
        self.client.get("/books", params={"q": q}, name="/books?q=[term] (HTML)")


class Shopper(LocalUser):
    weight = 1
    wait_time = between(0.5, 1.5)

    def on_start(self) -> None:
        super().on_start()
        creds = {"username": f"load_{uuid.uuid4().hex[:12]}", "password": "load-test-password"}
        self.client.post("/api/users", json=creds, name="/api/users")
        token = self.client.post("/api/auth/token", json=creds, name="/api/auth/token")
        self.client.headers["Authorization"] = f"Bearer {token.json()['access_token']}"

    @task(3)
    def add_to_cart(self) -> None:
        book_id = random.choice(SEED_BOOK_IDS)
        with self.client.put(
            f"/api/cart/items/{book_id}",
            json={"quantity": 1},
            name="/api/cart/items/[id]",
            catch_response=True,
        ) as response:
            # 409 = sold out under load: correct behaviour, not an error.
            if response.status_code in (200, 409):
                response.success()

    @task(2)
    def view_cart(self) -> None:
        self.client.get("/api/cart")

    @task(1)
    def checkout(self) -> None:
        with self.client.post("/api/orders", catch_response=True) as response:
            # 400 = empty cart, 409 = stock ran out: expected outcomes under load.
            if response.status_code in (201, 400, 409):
                response.success()


@events.quitting.add_listener
def apply_thresholds(environment, **_kwargs) -> None:
    total = environment.stats.total
    result = LoadResult(
        requests=total.num_requests,
        failures=total.num_failures,
        p50_ms=total.get_response_time_percentile(0.50) or 0.0,
        p95_ms=total.get_response_time_percentile(0.95) or 0.0,
        p99_ms=total.get_response_time_percentile(0.99) or 0.0,
        rps=round(total.total_rps, 1),
    )
    thresholds = Thresholds.from_env()
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary(result, thresholds), indent=2))
    breaches = evaluate(result, thresholds)
    print(f"[load-gate] {json.dumps(summary(result, thresholds)['result'])}")
    if breaches:
        print("[load-gate] FAIL: " + "; ".join(breaches))
        environment.process_exit_code = 1
    else:
        print("[load-gate] PASS")
