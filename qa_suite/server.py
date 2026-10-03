"""Start and stop the system under test as a real uvicorn subprocess.

Running the SUT in its own process (instead of FastAPI's in-process TestClient)
means browser, Selenium and Locust tests talk to it over real HTTP exactly as a
user would, and every pytest-xdist worker can own an isolated server + database.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent


INSTANCE_HEADER = "X-Instance-Id"


def free_port() -> int:
    """Ask the OS for an unused TCP port on localhost.

    The port is released before uvicorn binds it, so another process can take it in
    between. ``SutServer`` therefore also checks the instance id echoed by /healthz.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until_healthy(
    base_url: str,
    timeout: float = 30.0,
    process: subprocess.Popen[bytes] | None = None,
    instance_id: str | None = None,
) -> None:
    """Poll /healthz until it answers 200. If ``process`` exits first, fail at once.

    With ``instance_id``, only a server that echoes that id counts as healthy: if another
    server (say, a different xdist worker's) took the port, this one cannot have bound
    it, so we keep polling until our process exits or the timeout passes.
    """
    deadline = time.monotonic() + timeout
    last_error: object = None
    # trust_env=False: SUT traffic is local and must never go through an HTTP(S)_PROXY.
    with httpx.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                raise RuntimeError(
                    f"SUT process exited with code {process.returncode} before healthy"
                )
            try:
                response = client.get(f"{base_url}/healthz")
                answered_by = response.headers.get(INSTANCE_HEADER)
                if response.status_code == 200 and instance_id in (None, answered_by):
                    return
                last_error = f"/healthz answered {response.status_code} from {answered_by!r}"
            except httpx.HTTPError as exc:
                last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"SUT at {base_url} did not become healthy: {last_error!r}")


@dataclass(frozen=True)
class SutHandle:
    """Where the system under test lives; db_path is None when the DB is not reachable."""

    base_url: str
    db_path: Path | None
    admin_token: str


class SutServer:
    """Context manager that runs `uvicorn sut.app:create_app` on a free port."""

    def __init__(self, db_path: Path, log_path: Path, admin_token: str = "dev-admin-token"):
        self.db_path = db_path
        self.log_path = log_path
        self.admin_token = admin_token
        self.port = free_port()
        self.instance_id = uuid.uuid4().hex
        self._proc: subprocess.Popen[bytes] | None = None
        self._log = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> SutHandle:
        env = {
            **os.environ,
            "BOOKSHOP_DB": str(self.db_path),
            "BOOKSHOP_ADMIN_TOKEN": self.admin_token,
            "BOOKSHOP_INSTANCE_ID": self.instance_id,
        }
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "sut.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--log-level",
            "warning",
        ]
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = self.log_path.open("wb")
        self._proc = subprocess.Popen(
            cmd, cwd=PROJECT_ROOT, env=env, stdout=self._log, stderr=subprocess.STDOUT
        )
        try:
            wait_until_healthy(self.base_url, process=self._proc, instance_id=self.instance_id)
        except RuntimeError as exc:
            self.stop()
            raise RuntimeError(
                f"SUT failed to start ({exc}); see {self.log_path}:\n"
                f"{self.log_path.read_text()[-2000:]}"
            ) from None
        return SutHandle(self.base_url, self.db_path, self.admin_token)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        if self._log:
            self._log.close()

    def __enter__(self) -> SutHandle:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
