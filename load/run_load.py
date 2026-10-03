"""Start a throwaway SUT on a free port and run the Locust scenario headless against it.

    python load/run_load.py --users 20 --spawn-rate 5 --duration 30s

Pass --host to target an already running server instead (e.g. docker compose).
Exits with Locust's exit code, which is 1 when a threshold is breached.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qa_suite.server import SutServer  # noqa: E402


def run_locust(host: str, users: int, spawn_rate: int, duration: str) -> int:
    cmd = [
        sys.executable, "-m", "locust",
        "-f", str(ROOT / "load" / "locustfile.py"),
        "--headless",
        "--users", str(users),
        "--spawn-rate", str(spawn_rate),
        "--run-time", duration,
        "--host", host,
        "--csv", str(ROOT / "reports" / "load"),
        "--only-summary",
    ]  # fmt: skip
    return subprocess.run(cmd, cwd=ROOT, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--spawn-rate", type=int, default=5)
    parser.add_argument("--duration", default="30s")
    parser.add_argument("--host", help="target an existing server instead of starting one")
    args = parser.parse_args()
    (ROOT / "reports").mkdir(exist_ok=True)

    if args.host:
        return run_locust(args.host, args.users, args.spawn_rate, args.duration)
    with tempfile.TemporaryDirectory() as tmp:
        server = SutServer(Path(tmp) / "load.sqlite3", ROOT / "test-results" / "sut-load.log")
        with server as sut:
            return run_locust(sut.base_url, args.users, args.spawn_rate, args.duration)


if __name__ == "__main__":
    raise SystemExit(main())
