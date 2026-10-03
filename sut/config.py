"""Runtime settings for the bookshop, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = Path("data") / "bookshop.sqlite3"
# A development-only token so the test framework can create isolated catalogue data.
# It is not a secret: override BOOKSHOP_ADMIN_TOKEN for anything that is not a test run.
DEFAULT_ADMIN_TOKEN = "dev-admin-token"


@dataclass(frozen=True)
class Settings:
    db_path: Path
    admin_token: str
    seed: bool = True
    # Echoed by /healthz so a test harness can tell its own server from another one.
    instance_id: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            db_path=Path(os.environ.get("BOOKSHOP_DB", str(DEFAULT_DB_PATH))),
            admin_token=os.environ.get("BOOKSHOP_ADMIN_TOKEN", DEFAULT_ADMIN_TOKEN),
            seed=os.environ.get("BOOKSHOP_SEED", "1") != "0",
            instance_id=os.environ.get("BOOKSHOP_INSTANCE_ID", ""),
        )
