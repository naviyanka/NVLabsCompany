"""Backend supervisor daemon — start/stop/restart the NEXUS API from the UI.

A tiny, always-on HTTP service (stdlib only, zero third-party deps) that owns
the backend uvicorn process. The dashboard talks to *this*, not the backend, so
lifecycle controls work even when the backend is down.

Run it once (it is the one always-on piece):

    python -m nexus.supervisor

Then the dashboard's Runtime Control panel can hit:

    GET  /status   -> { running, healthy, pid, port, uptime_seconds }
    POST /start     -> spawn the backend if not already running
    POST /stop      -> terminate the backend (graceful, then force)
    POST /restart   -> stop + start

Design notes:
- Binds to 127.0.0.1 only. It manages one local backend; it is never a remote
  control surface.
- No dependency on the backend's packages, so a broken backend import can never
  stop the supervisor from restarting it.
- Windows process trees are killed with ``taskkill /F /T`` because uvicorn's
  reloader spawns children that ``Popen.terminate`` alone would orphan.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# --- configuration (overridable via env) ---------------------------------

SUPERVISOR_PORT = int(os.environ.get("SUPERVISOR_PORT", "8001"))
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))
BACKEND_HOST = os.environ.get("BACKEND_HOST", "0.0.0.0")

# Repo layout: this file is src/nexus/supervisor.py, so the backend cwd is src/.
_SRC_DIR = Path(__file__).resolve().parent.parent

# The environment the backend runs with. Values already set in the supervisor's
# own environment win, so an operator can override any of these before launch.
_DEFAULT_BACKEND_ENV = {
    "AUTH_ENABLED": "true",
    "DATABASE_URL": "sqlite+aiosqlite:///./nexus_dev.db",
    "CEO_API_KEY": "nv_52e2c692e7f566675fcea7209c6e14cf570fa640c60eab1e",
    "SECRET_KEY": "nvlabs-dev-vault-key-9f3c2a7e1b6d4508",
}


class BackendController:
    """Owns the backend child process and its lifecycle transitions."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._started_at: float | None = None
        self._lock = threading.Lock()

    # --- queries ---------------------------------------------------------

    def _proc_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _health_ok(self, timeout: float = 1.5) -> bool:
        """Probe the backend's own health endpoint."""
        url = f"http://127.0.0.1:{BACKEND_PORT}/health"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    def status(self) -> dict:
        alive = self._proc_alive()
        healthy = self._health_ok()
        # "running" means the backend answers health, whether we own it or not —
        # an operator may have started it in a terminal.
        running = alive or healthy
        return {
            "running": running,
            "healthy": healthy,
            "owned": alive,
            "pid": self._proc.pid if self._proc else None,
            "port": BACKEND_PORT,
            "uptime_seconds": int(time.time() - self._started_at) if self._started_at and alive else None,
        }

    # --- transitions -----------------------------------------------------

    def start(self) -> dict:
        with self._lock:
            if self._proc_alive() or self._health_ok():
                return {"ok": True, "message": "Backend already running.", **self.status()}

            env = os.environ.copy()
            for key, val in _DEFAULT_BACKEND_ENV.items():
                env.setdefault(key, val)

            cmd = [
                sys.executable, "-m", "uvicorn", "nexus.main:app",
                "--host", BACKEND_HOST, "--port", str(BACKEND_PORT),
            ]
            creationflags = 0
            if os.name == "nt":
                # New process group so we can signal the tree on Windows.
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            self._proc = subprocess.Popen(
                cmd, cwd=str(_SRC_DIR), env=env, creationflags=creationflags,
            )
            self._started_at = time.time()

        # Wait briefly for health so the caller gets an accurate verdict.
        for _ in range(40):  # up to ~20s
            if self._health_ok():
                break
            if not self._proc_alive():
                return {"ok": False, "message": "Backend exited during startup.", **self.status()}
            time.sleep(0.5)

        healthy = self._health_ok()
        return {
            "ok": healthy,
            "message": "Backend started." if healthy else "Backend spawned but not yet healthy.",
            **self.status(),
        }

    def stop(self) -> dict:
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                # We do not own a live process. Best-effort free the port in case
                # a detached backend is holding it.
                self._kill_port(BACKEND_PORT)
                self._proc = None
                self._started_at = None
                return {"ok": True, "message": "Backend was not running (owned by supervisor).", **self.status()}

            self._terminate_tree(proc)
            self._proc = None
            self._started_at = None
            return {"ok": True, "message": "Backend stopped.", **self.status()}

    def restart(self) -> dict:
        self.stop()
        time.sleep(1.0)
        return self.start()

    # --- process/port helpers -------------------------------------------

    @staticmethod
    def _terminate_tree(proc: subprocess.Popen) -> None:
        """Kill the process and its children, cross-platform."""
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, check=False,
                )
            else:
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    @staticmethod
    def _kill_port(port: int) -> None:
        """Best-effort: kill whatever listens on `port` (Windows netstat path)."""
        if os.name != "nt":
            return
        try:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, check=False
            ).stdout
            pids: set[str] = set()
            needle = f":{port}"
            for line in out.splitlines():
                if needle in line and "LISTENING" in line:
                    pids.add(line.split()[-1])
            for pid in pids:
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, check=False)
        except Exception:
            pass


_controller = BackendController()


class Handler(BaseHTTPRequestHandler):
    """Minimal JSON HTTP handler for the supervisor endpoints."""

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # The dashboard proxies same-origin, but allow direct localhost calls too.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("/status", "/api/supervisor/status"):
            self._send(200, _controller.status())
        elif self.path.rstrip("/") in ("", "/health", "/api/supervisor/health"):
            self._send(200, {"supervisor": "alive"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        route = self.path.rstrip("/").replace("/api/supervisor", "")
        if route == "/start":
            self._send(200, _controller.start())
        elif route == "/stop":
            self._send(200, _controller.stop())
        elif route == "/restart":
            self._send(200, _controller.restart())
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *_args) -> None:  # silence default stderr logging
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", SUPERVISOR_PORT), Handler)
    print(f"[supervisor] listening on http://127.0.0.1:{SUPERVISOR_PORT}")
    print(f"[supervisor] manages backend on port {BACKEND_PORT} (cwd={_SRC_DIR})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[supervisor] shutting down; leaving backend running.")
        server.shutdown()


if __name__ == "__main__":
    main()
