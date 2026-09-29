# ruff: noqa: E501  (the fake interpreters below are embedded scripts)
"""Ownership, isolation and redaction tests for scripts/start-local-voice.ps1 and stop-local-voice.ps1.

The real scripts run in Windows PowerShell 5.1 against a fake checkout in a directory with
spaces. Fakes stand in for everything heavy: the worker, backend, dashboard, ``docker`` and
the Python interpreter are small stubs; Redis and OmniRoute are servers in this process. No
test touches a real user process, container, database or secret.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell launcher")

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SECRET_KEY = "sentinel-secret-key-do-not-log-4f9a"
COMPANY = "11111111-1111-4111-8111-111111111111"
CEO_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
UNRELATED = {"id": "9" * 64, "name": "someone-elses-db", "label": "", "image": "postgres:16"}
POWERSHELL = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]

FAKE_PY = r"""
import json, os, runpy, socket, sqlite3, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

probe = os.environ["FAKE_PROBE_DIR"]
a = sys.argv[1:]

def write(name, data):
    with open(os.path.join(probe, name), "w") as f:
        json.dump(data, f)

def listen(port, http=False):
    if http:
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
            def log_message(self, *x): pass
        HTTPServer(("127.0.0.1", port), H).serve_forever()
    s = socket.socket(); s.bind(("127.0.0.1", port)); s.listen()
    while True:
        s.accept()[0].close()

if a[:1] == ["-c"]:
    print("secret_resolves=" + ("False" if os.environ.get("FAKE_SECRET") == "missing" else "True"))
elif a and a[0].endswith("clone_sqlite.py"):
    sys.argv = a
    runpy.run_path(a[0], run_name="__main__")
elif a and a[0].endswith("prepare_acceptance.py"):
    # Stands in for the real script (covered by tests/test_prepare_acceptance.py): records what it saw.
    calls = os.path.join(probe, "prepare_calls.json")
    seen = json.load(open(calls)) if os.path.exists(calls) else []
    seen.append({"args": a[1:], "database_url": os.environ.get("DATABASE_URL"), "cwd": os.getcwd()})
    json.dump(seen, open(calls, "w"))
    if a[1] == "migrate":
        if os.environ.get("FAKE_MIGRATE") == "fail":
            print(json.dumps({"status": "FAIL", "error": "migration failed: OperationalError: boom"})); sys.exit(2)
        db = sqlite3.connect(os.environ["DATABASE_URL"].split(":///", 1)[1])
        db.execute("create table if not exists alembic_version(version_num)"); db.execute("delete from alembic_version")
        db.execute("insert into alembic_version values ('e7a1c2d3f406')"); db.commit(); db.close()
        print(json.dumps({"status": "PASS", "head": "e7a1c2d3f406"}))
    elif "--agent" in a:
        agent = a[a.index("--agent") + 1]
        print(json.dumps({"status": "PASS", "ceo_source": "appointed", "ceo": {"id": agent, "name": "Chosen", "role": "executive"},
                          "snapshot": {"version": 1, "freshness": "fresh", "payload_hash": "h"}}))
    else:
        print(json.dumps({"status": "LIVE_CHECK_REQUIRED", "candidates": [
            {"id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "name": "Ann", "role": "executive"},
            {"id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "name": "Zed", "role": "engineer"}]}))
        sys.exit(3)
elif a[:2] == ["-m", "uvicorn"]:
    url = os.environ["DATABASE_URL"]
    write("backend.json", {k: os.environ.get(k) for k in ("DATABASE_URL", "SECRET_KEY", "NEXUS_VOICE_WORKER_SECRET", "HERMES_NATIVE_SECRET_REF", "HERMES_NATIVE_MODEL")} | {"pid": os.getpid()})
    db = sqlite3.connect(url.split(":///", 1)[1])
    db.execute("create table if not exists acceptance_marks(x)"); db.execute("insert into acceptance_marks values (1)"); db.commit(); db.close()
    listen(int(a[a.index("--port") + 1]), http=True)
elif a[:2] == ["-m", "nexus.cli"]:
    secret = os.environ["NEXUS_VOICE_WORKER_SECRET"]
    hindi = os.environ.get("FAKE_HINDI", "LIVE_CHECK_REQUIRED")
    checks = [
        {"id": "browser_microphone", "status": "LIVE_CHECK_REQUIRED", "detail": "browser only"},
        {"id": "tts_en", "status": "PASS", "detail": "en voice"},
        {"id": "tts_hi", "status": hindi, "detail": "no hi voice" + (" " + secret if os.environ.get("FAKE_DOCTOR_LEAK") else "")},
        {"id": "shared_state", "status": "PASS", "detail": "Redis"},
    ]
    write("doctor_args.json", a)
    print(json.dumps({"status": "LIVE_CHECK_REQUIRED" if hindi != "PASS" else "PASS", "checks": checks}))
elif a == ["serve"]:
    write("worker.json", {"secret": os.environ["NEXUS_VOICE_WORKER_SECRET"], "pid": os.getpid()})
    listen(int(os.environ["NEXUS_VOICE_PORT"]))
elif a == ["run", "dev"]:
    listen(int(os.environ["PORT"]))
elif a == ["sleep"]:
    time.sleep(120)
"""

FAKE_DOCKER = r"""
import hashlib, json, os, sys
state_file, log = os.environ["FAKE_DOCKER_STATE"], os.environ["FAKE_DOCKER_LOG"]
a = sys.argv[1:]
with open(log, "a") as f:
    f.write(" ".join(a) + "\n")
if os.environ.get("FAKE_DOCKER_DOWN"):
    sys.stderr.write("Cannot connect to the Docker daemon\n")
    sys.exit(1)
state = json.load(open(state_file))
cs = state["containers"]


def flag_values(flag):
    return [a[i + 1] for i, x in enumerate(a) if x == flag and i + 1 < len(a)]


if a[0] == "run":
    cid = hashlib.sha256(f"fake{len(cs) + 1}".encode()).hexdigest()
    label = a[a.index("--label") + 1].split("=", 1)[1]
    cs.append({"id": cid, "name": a[a.index("--name") + 1], "label": label, "image": a[-1]})
    print(cid)
elif a[0] == "ps":
    # Like Docker: repeated --filter flags are ANDed, id= matches by PREFIX, label=k=v matches exactly.
    hits = cs
    for flt in flag_values("--filter"):
        key, _, value = flt.partition("=")
        if key == "id":
            hits = [c for c in hits if c["id"].startswith(value)]
        elif key == "label":
            hits = [c for c in hits if c["label"] == value.partition("=")[2]]
        else:
            sys.exit(1)
    if os.environ.get("FAKE_DOCKER_PS") == "other":  # a result that is not the container asked about
        hits = [{"id": "0" * 64, "name": "x", "image": "x"}]
    if os.environ.get("FAKE_DOCKER_PS") == "two":
        hits = hits + [{"id": "0" * 64, "name": "x", "image": "x"}]
    for c in hits:
        if "--format" in a:
            print(flag_values("--format")[0].replace("{{.Names}}", c["name"]).replace("{{.Image}}", c.get("image", "")))
        else:
            print(c["id"])
elif a[0] == "inspect":
    # What real Docker does with the template PowerShell hands it once the inner quotes are stripped.
    template = flag_values("-f")[0]
    if 'Labels "' not in template:
        sys.stderr.write('template parsing error: function "nexus" not defined\n')
        sys.exit(1)
    sys.exit(1)
elif a[0] == "rm":
    if not any(c["id"] == a[-1] for c in cs):
        sys.stderr.write("Error: No such container\n")
        sys.exit(1)
    state["containers"] = [c for c in cs if c["id"] != a[-1]]
json.dump(state, open(state_file + ".tmp", "w"))
os.replace(state_file + ".tmp", state_file)  # atomic: the test's Redis thread reads it concurrently
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class OmniRoute:
    """Fake gateway: answers 401 like OmniRoute without a key, and records what it was sent."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append(
                    {"path": self.path, "auth": self.headers.get("Authorization")}
                )
                self.send_response(401)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def alive(self) -> bool:
        try:
            socket.create_connection(("127.0.0.1", self.port), timeout=2).close()
            return True
        except OSError:
            return False


class Redis:
    """Answers PING with +PONG only while ``up()`` is true; otherwise nothing listens (as a free port)."""

    def __init__(self, up) -> None:
        self.up = up
        self.port = free_port()
        self.sock: socket.socket | None = None
        self.stopped = False
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while not self.stopped:
            if self.up() and self.sock is None:
                self.sock = socket.socket()
                self.sock.settimeout(0.1)
                self.sock.bind(("127.0.0.1", self.port))
                self.sock.listen()
            elif not self.up() and self.sock is not None:
                self.sock.close()
                self.sock = None
            if self.sock is not None:
                try:
                    c, _ = self.sock.accept()
                except OSError:
                    continue
                try:
                    if c.recv(64):
                        c.sendall(b"+PONG\r\n")
                except OSError:
                    pass
                finally:
                    c.close()
            else:
                time.sleep(0.05)

    def close(self) -> None:
        self.stopped = True
        if self.sock is not None:
            self.sock.close()


def run_ps(cmd, env, cwd, timeout, stdin="") -> subprocess.CompletedProcess:
    """Run a script with output going to files: the services it leaves running inherit pipes and would block EOF."""
    with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
        r = subprocess.run(
            cmd, env=env, input=stdin, stdout=out, stderr=err, text=True, timeout=timeout, cwd=cwd
        )
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(cmd, r.returncode, out.read(), err.read())


class Sandbox:
    def __init__(self, base: Path, existing_redis: bool = False) -> None:
        self.base = base
        self.root = base / "my repo (spaces)"
        self.tmp = base / "tmp dir"
        self.probe = base / "probe"
        self.envdir = base / "env dir"
        self.bin = base / "bin"
        for d in (
            self.root / "scripts",
            self.root / "voice",
            self.root / "dashboard",
            self.root / "src",
            self.tmp,
            self.probe,
            self.envdir,
            self.bin,
        ):
            d.mkdir(parents=True)
        for f in ("start-local-voice.ps1", "stop-local-voice.ps1", "clone_sqlite.py"):
            shutil.copy(SCRIPTS / f, self.root / "scripts" / f)
        (self.bin / "fake_py.py").write_text(FAKE_PY)
        (self.bin / "fake_docker.py").write_text(FAKE_DOCKER)
        py = sys.executable
        for name in ("python", "worker", "npm"):  # all pass their arguments to the fake interpreter
            (self.bin / f"{name}.cmd").write_text(f'@"{py}" "%~dp0fake_py.py" %*\r\n')
        (self.bin / "docker.cmd").write_text(f'@"{py}" "%~dp0fake_docker.py" %*\r\n')
        self.docker_state = base / "docker_state.json"
        self.docker_log = base / "docker.log"
        self.docker_state.write_text(json.dumps({"containers": [UNRELATED]}))
        self.docker_log.write_text("")
        self.omniroute = OmniRoute()
        self.existing_redis = existing_redis
        self.redis = Redis(
            lambda: (
                self.existing_redis
                or any(
                    c["name"].startswith("nexus-local-voice-redis-")
                    for c in self.docker()["containers"]
                )
            )
        )
        self.ports = {
            "BackendPort": free_port(),
            "DashboardPort": free_port(),
            "WorkerPort": free_port(),
        }
        # The primary database sits next to .env and is referenced by a relative URL.
        self.source_db = self.envdir / "dev.db"
        db = sqlite3.connect(self.source_db)
        db.execute("create table secrets(name, ciphertext)")
        db.execute(
            "insert into secrets values ('hermes_native_omniroute_api_key', 'gAAAA-not-a-real-token')"
        )
        db.execute("create table alembic_version(version_num)")
        db.execute(
            "insert into alembic_version values ('a7c4e9b2d610')"
        )  # behind head: only the copy may move
        db.commit()
        db.close()
        self.env_file = self.envdir / ".env"
        self.env_file.write_text(
            f"DATABASE_URL=sqlite+aiosqlite:///./dev.db\nSECRET_KEY={SECRET_KEY}\n"
        )
        self.state_dir = self.tmp / "nexus-local-voice"

    def docker(self) -> dict:
        return json.loads(self.docker_state.read_text())

    def docker_calls(self) -> list[str]:
        return self.docker_log.read_text().splitlines()

    def env(self, **extra: str) -> dict[str, str]:
        e = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SECRET_KEY")}
        e.update(
            TEMP=str(self.tmp),
            TMP=str(self.tmp),
            PATH=f"{self.bin};{e['PATH']}",
            FAKE_PROBE_DIR=str(self.probe),
            FAKE_DOCKER_STATE=str(self.docker_state),
            FAKE_DOCKER_LOG=str(self.docker_log),
        )
        e.update(extra)
        return e

    def start(
        self, *args: str, ceo: bool = True, stdin: str = "", **env: str
    ) -> subprocess.CompletedProcess:
        if ceo and "-UseDevDatabase" not in args and "-CeoAgentId" not in args:
            args = (*args, "-CeoAgentId", CEO_ID)
        cmd = [
            *POWERSHELL,
            str(self.root / "scripts" / "start-local-voice.ps1"),
            "-EnvFile",
            str(self.env_file),
            "-Python",
            str(self.bin / "python.cmd"),
            "-Worker",
            str(self.bin / "worker.cmd"),
            "-HermesBaseUrl",
            f"http://127.0.0.1:{self.omniroute.port}/v1",
            "-HermesModel",
            "agy/gemini-3.7-flash-high",
            "-SecretRef",
            "hermes_native_omniroute_api_key",
            "-CompanyId",
            COMPANY,
            "-RedisPort",
            str(self.redis.port),
            *[x for k, v in self.ports.items() for x in (f"-{k}", str(v))],
            "-NoPause",
            *args,
        ]
        return run_ps(cmd, self.env(**env), self.root, 240, stdin)

    def stop(self, **env: str) -> subprocess.CompletedProcess:
        cmd = [*POWERSHELL, str(self.root / "scripts" / "stop-local-voice.ps1")]
        return run_ps(cmd, self.env(**env), self.root, 120)

    def prepare_calls(self) -> list[dict]:
        path = self.probe / "prepare_calls.json"
        return json.loads(path.read_text()) if path.exists() else []

    def state(self) -> dict:
        return json.loads((self.state_dir / "state.json").read_text(encoding="utf-8-sig"))

    def probe_json(self, name: str) -> dict:
        return json.loads((self.probe / name).read_text())

    def state_dir_text(self) -> str:
        return "".join(
            p.read_text(errors="replace")
            for p in self.state_dir.iterdir()
            if p.is_file() and p.suffix != ".db"
        )

    def close(self) -> None:
        try:
            self.stop()
        finally:
            self.omniroute.server.shutdown()
            self.redis.close()


def alive(pid: int) -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
    ).stdout
    return str(pid) in out


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def start_time(pid: int) -> int:
    out = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"(Get-Process -Id {pid}).StartTime.ToFileTimeUtc()",
        ],
        capture_output=True,
        text=True,
    ).stdout
    return int(out.strip())


@pytest.fixture
def sandbox(tmp_path):
    sb = Sandbox(tmp_path)
    yield sb
    sb.close()


@pytest.fixture(scope="module")
def happy(tmp_path_factory):
    """One full isolated-mode launch, inspected while running, then stopped twice."""
    sb = Sandbox(tmp_path_factory.mktemp("happy"))
    dev_hash, env_hash = sha(sb.source_db), sha(sb.env_file)
    r1 = sb.start()
    running = {}
    if r1.returncode == 0:
        st = sb.state()
        running = {
            "state": st,
            "alive": {p["name"]: alive(p["pid"]) for p in st["processes"]},
            "state_text": sb.state_dir_text(),
            "copy_exists": (sb.state_dir / "acceptance.db").exists(),
            "copy_has_mark": _has_mark(sb.state_dir / "acceptance.db"),
            "backend": sb.probe_json("backend.json"),
            "worker": sb.probe_json("worker.json"),
            "doctor_args": sb.probe_json("doctor_args.json"),
            "docker": sb.docker(),
            "prepare_calls": sb.prepare_calls(),
            "copy_revision": _revision(sb.state_dir / "acceptance.db"),
        }
        r2 = sb.start()
        running["second_alive"] = {p["name"]: alive(p["pid"]) for p in st["processes"]}
        running["second_state"] = sb.state()
    else:
        r2 = None
    stop1 = sb.stop()
    stop2 = sb.stop()
    out = dict(
        sb=sb,
        r1=r1,
        r2=r2,
        stop1=stop1,
        stop2=stop2,
        running=running,
        dev_hash=dev_hash,
        env_hash=env_hash,
    )
    out["after_omni_alive"] = sb.omniroute.alive()
    yield out
    sb.close()


def _revision(db: Path) -> str | None:
    c = sqlite3.connect(db)
    try:
        return c.execute("select version_num from alembic_version").fetchone()[0]
    except sqlite3.Error:
        return None
    finally:
        c.close()


def _has_mark(db: Path) -> bool:
    try:
        c = sqlite3.connect(db)
        try:
            return c.execute("select count(*) from acceptance_marks").fetchone()[0] == 1
        finally:
            c.close()
    except sqlite3.Error:
        return False


# --- isolated database -----------------------------------------------------------------


def test_launch_succeeds_in_a_path_with_spaces(happy):
    assert " " in str(happy["sb"].root)
    r = happy["r1"]
    assert r.returncode == 0, r.stdout + r.stderr
    for line in (
        "worker     PASS",
        "backend    PASS",
        "dashboard  PASS",
        "secret     PASS",
        "omniroute  PASS",
    ):
        assert line in r.stdout


def test_isolated_mode_is_the_default(happy):
    run = happy["running"]
    assert "isolated backup" in happy["r1"].stdout
    assert "DEV DATABASE" not in happy["r1"].stdout
    backend = run["backend"]
    copy = (happy["sb"].state_dir / "acceptance.db").as_posix()
    assert backend["DATABASE_URL"] == f"sqlite+aiosqlite:///{copy}"
    assert str(happy["sb"].source_db).replace("\\", "/") not in backend["DATABASE_URL"]
    assert run["copy_exists"]
    assert run["state"]["db"]["owner"] == run["state"]["run"]


def test_backup_receives_writes_while_the_source_does_not(happy):
    assert happy["running"]["copy_has_mark"]
    db = sqlite3.connect(happy["sb"].source_db)
    try:
        assert (
            db.execute(
                "select count(*) from sqlite_master where name='acceptance_marks'"
            ).fetchone()[0]
            == 0
        )
    finally:
        db.close()
    assert sha(happy["sb"].source_db) == happy["dev_hash"]
    assert "source_db  PASS (byte-for-byte unchanged)" in happy["r1"].stdout
    assert sha(happy["sb"].env_file) == happy["env_hash"]  # .env only read


def test_doctor_gets_the_company_and_secret_ref_reaches_the_backend(happy):
    args = happy["running"]["doctor_args"]
    assert args[-2:] == ["--company", COMPANY]
    assert (
        happy["running"]["backend"]["HERMES_NATIVE_SECRET_REF"] == "hermes_native_omniroute_api_key"
    )
    assert happy["running"]["backend"]["HERMES_NATIVE_MODEL"] == "agy/gemini-3.7-flash-high"


# --- redaction --------------------------------------------------------------------------


def test_no_database_url_secret_key_or_worker_secret_is_logged_or_persisted(happy):
    sb, run = happy["sb"], happy["running"]
    worker_secret = run["worker"]["secret"]
    assert len(worker_secret) >= 32
    assert run["backend"]["NEXUS_VOICE_WORKER_SECRET"] == worker_secret  # shared through env only
    every = (
        happy["r1"].stdout
        + happy["r1"].stderr
        + run["state_text"]
        + happy["stop1"].stdout
        + happy["stop1"].stderr
    )
    for forbidden in (
        worker_secret,
        SECRET_KEY,
        "sqlite+aiosqlite",
        str(sb.source_db),
        sb.source_db.as_posix(),
        "gAAAA",
    ):
        assert forbidden not in every, forbidden
    assert worker_secret not in sb.env_file.read_text()
    assert run["backend"]["SECRET_KEY"] == SECRET_KEY  # the backend still gets the key to decrypt


def test_doctor_output_containing_the_worker_secret_is_refused(sandbox, tmp_path):
    evidence = tmp_path / "evidence.json"
    r = sandbox.start("-EvidenceFile", str(evidence), FAKE_DOCTOR_LEAK="1")
    assert r.returncode == 1
    assert "contained the worker secret" in r.stdout
    assert not evidence.exists()
    assert not sandbox.state_dir.exists()  # failure cleaned everything up


def test_unresolvable_secret_ref_fails_and_cleans_up(sandbox):
    r = sandbox.start(FAKE_SECRET="missing")
    assert r.returncode == 1
    assert "does not resolve" in r.stdout
    assert not sandbox.state_dir.exists()


# --- ownership and cleanup --------------------------------------------------------------


def test_stop_removes_only_the_launchers_own_things(happy):
    sb, run = happy["sb"], happy["running"]
    assert all(run["alive"].values()) and set(run["alive"]) == {"worker", "backend", "dashboard"}
    assert happy["stop1"].returncode == 0, happy["stop1"].stdout
    assert not any(alive(p["pid"]) for p in run["state"]["processes"])
    assert not sb.state_dir.exists()  # copy, logs and state are gone
    assert sb.source_db.exists() and sha(sb.source_db) == happy["dev_hash"]


def test_owned_redis_container_is_removed_and_unrelated_ones_are_untouched(happy):
    sb, run = happy["sb"], happy["running"]
    assert "PASS (container owned by this script)" in happy["r1"].stdout
    ours = run["docker"]["containers"][1]
    assert run["state"]["container"]["id"] == ours["id"] and ours["image"] == "redis:7-alpine"
    assert sb.docker()["containers"] == [UNRELATED]
    calls = sb.docker_calls()
    assert [c.split()[0] for c in calls] == ["run", "ps", "ps", "rm"]
    assert (
        calls[1]
        == f"ps -aq --no-trunc --filter id={ours['id']} --filter label=nexus.local-voice={run['state']['run']}"
    )
    assert calls[3] == f"rm -f {ours['id']}"  # by the exact full ID, never by name
    assert all(UNRELATED["id"] not in c and "inspect" not in c for c in calls)


def test_omniroute_is_probed_never_authenticated_and_keeps_running(happy):
    assert happy["after_omni_alive"]
    reqs = happy["sb"].omniroute.requests
    assert reqs and all(r["auth"] is None for r in reqs)


def test_repeated_start_refuses_and_leaves_the_first_run_alone(happy):
    r2, run = happy["r2"], happy["running"]
    assert r2.returncode == 1 and "already started" in r2.stdout
    assert run["second_state"] == run["state"]
    assert all(run["second_alive"].values())


def test_stop_is_idempotent(happy):
    assert happy["stop2"].returncode == 0
    assert "nothing to stop" in happy["stop2"].stdout


def test_hindi_gap_is_explained_and_english_acceptance_continues(happy):
    out = happy["r1"].stdout
    assert "LIVE_CHECK_REQUIRED tts_hi" in out.replace("  ", " ") or "tts_hi" in out
    assert "MISSING" in out and "Hindi" in out
    assert "PASS" in out and "tts_en" in out


def test_existing_redis_is_reused_and_never_stopped(tmp_path):
    sb = Sandbox(tmp_path, existing_redis=True)
    try:
        r = sb.start()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "PASS (existing, not owned)" in r.stdout
        assert sb.state()["container"] is None
        assert sb.stop().returncode == 0
        assert sb.docker_calls() == []  # no docker command at all
        assert sb.redis.up()
    finally:
        sb.close()


def test_interrupt_and_failure_run_cleanup(sandbox):
    # The stage hook raises the exception Ctrl+C raises, after the worker is up.
    r = sandbox.start(NEXUS_LOCAL_VOICE_TEST_INTERRUPT="worker")
    assert r.returncode != 0
    worker = sandbox.probe_json("worker.json")
    assert not alive(worker["pid"])
    assert not sandbox.state_dir.exists()  # copy, logs and state removed
    assert sandbox.docker()["containers"] == [UNRELATED]
    assert sandbox.source_db.exists()


def test_interrupt_during_the_backup_still_removes_the_copy(sandbox):
    r = sandbox.start(NEXUS_LOCAL_VOICE_TEST_INTERRUPT="database")
    assert r.returncode != 0
    assert not sandbox.state_dir.exists()


# --- migration of the copy and the CEO choice --------------------------------------------


def test_only_the_copy_is_migrated_and_it_reaches_head(happy):
    run, sb = happy["running"], happy["sb"]
    copy_url_tail = str(sb.state_dir / "acceptance.db").replace("\\", "/")
    migrate, prepare = run["prepare_calls"]
    assert migrate["args"] == ["migrate", str(sb.source_db)]
    assert prepare["args"] == ["prepare", COMPANY, "--agent", CEO_ID]
    for call in run["prepare_calls"]:
        assert call["database_url"].endswith(copy_url_tail), (
            "prepare/migrate only ever see the copy"
        )
        assert str(sb.source_db).replace("\\", "/") not in call["database_url"]
    assert run["copy_revision"] == "e7a1c2d3f406"
    assert _revision(sb.source_db) == "a7c4e9b2d610" and sha(sb.source_db) == happy["dev_hash"]


def test_without_a_ceo_choice_the_launcher_lists_candidates_and_stops(sandbox):
    before = sha(sandbox.source_db)
    r = sandbox.start(ceo=False)
    assert r.returncode == 3, r.stdout
    assert "LIVE_CHECK_REQUIRED" in r.stdout
    assert "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" in r.stdout and "Ann" in r.stdout
    assert "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" in r.stdout and "Zed" in r.stdout
    assert "-CeoAgentId <id>" in r.stdout
    assert [c["args"][0] for c in sandbox.prepare_calls()] == ["migrate", "prepare"]
    assert sandbox.docker_calls() == [], "no container before a CEO exists"
    assert (
        not (sandbox.probe / "worker.json").exists()
        and not (sandbox.probe / "backend.json").exists()
    )
    assert (
        not sandbox.state_dir.exists()
        and sha(sandbox.source_db) == before
        and _revision(sandbox.source_db) == "a7c4e9b2d610"
    )


@pytest.mark.parametrize(
    "args",
    [
        ("-UseDevDatabase", "-CeoAgentId", CEO_ID),
        ("-ReplaceCeo",),
        ("-CeoAgentId", "not-a-guid"),
        ("-CeoAgentId", "1; whoami"),
    ],
)
def test_ceo_flags_are_validated_before_anything_starts(sandbox, args):
    r = sandbox.start(*args, ceo=False, stdin="USE DEV DATABASE\n")
    assert r.returncode == 1, r.stdout
    assert sandbox.prepare_calls() == [] and sandbox.docker_calls() == []
    assert not sandbox.state_dir.exists()


def test_replace_ceo_is_passed_through_only_when_asked(sandbox):
    assert sandbox.start("-ReplaceCeo").returncode == 0
    assert sandbox.prepare_calls()[-1]["args"] == [
        "prepare",
        COMPANY,
        "--agent",
        CEO_ID,
        "--replace-ceo",
    ]


def test_a_failed_migration_stops_startup_and_cleans_up(sandbox):
    before = sha(sandbox.source_db)
    r = sandbox.start(FAKE_MIGRATE="fail")
    assert r.returncode == 1 and "migration of the copy failed" in r.stdout
    assert [c["args"][0] for c in sandbox.prepare_calls()] == ["migrate"]
    assert sandbox.docker_calls() == [] and not (sandbox.probe / "worker.json").exists()
    assert not sandbox.state_dir.exists()
    assert sha(sandbox.source_db) == before


@pytest.mark.parametrize("spelling", ["same", "forward-slashes", "upper-case"])
def test_a_source_that_is_the_copy_path_is_refused(sandbox, spelling):
    target = str(sandbox.state_dir / "acceptance.db")
    target = {
        "same": target,
        "forward-slashes": target.replace("\\", "/"),
        "upper-case": target.upper(),
    }[spelling]
    sandbox.env_file.write_text(
        f"DATABASE_URL=sqlite+aiosqlite:///{target}\nSECRET_KEY={SECRET_KEY}\n"
    )
    r = sandbox.start()
    assert r.returncode == 1, r.stdout
    assert sandbox.prepare_calls() == []


# --- -UseDevDatabase --------------------------------------------------------------------


def test_dev_database_requires_explicit_confirmation(sandbox):
    before = sha(sandbox.source_db)
    r = sandbox.start("-UseDevDatabase", stdin="yes\n")
    assert r.returncode == 1
    assert "WARNING" in r.stdout and "not confirmed" in r.stdout
    assert not sandbox.state_dir.exists()  # nothing was started
    assert sandbox.docker_calls() == []
    assert sha(sandbox.source_db) == before
    assert SECRET_KEY not in r.stdout + r.stderr and "sqlite" not in (r.stdout + r.stderr).lower()


def test_dev_database_runs_on_the_primary_only_after_confirmation(sandbox):
    r = sandbox.start(
        "-UseDevDatabase", stdin="USE DEV DATABASE\n", NEXUS_LOCAL_VOICE_TEST_INTERRUPT="redis"
    )
    assert "not confirmed" not in r.stdout
    assert "WARNING" in r.stdout
    assert not sandbox.state_dir.exists() and sandbox.source_db.exists()


# --- stop-local-voice.ps1 against hand-made state ----------------------------------------


def _sleeper(sb: Sandbox) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])


def _write_state(sb: Sandbox, **state) -> None:
    sb.state_dir.mkdir(parents=True, exist_ok=True)
    (sb.state_dir / "state.json").write_text(
        json.dumps(
            {"run": str(uuid.uuid4()), "processes": [], "container": None, "db": None, **state}
        )
    )


def test_pid_and_start_time_ownership(sandbox):
    victim = _sleeper(sandbox)
    ours = _sleeper(sandbox)
    try:
        _write_state(
            sandbox,
            processes=[
                {
                    "name": "reused-pid",
                    "pid": victim.pid,
                    "started": start_time(victim.pid) + 10 * 3600 * 10_000_000,
                },
                {"name": "ours", "pid": ours.pid, "started": start_time(ours.pid)},
            ],
        )
        r = sandbox.stop()
        assert r.returncode == 1  # a PID that was not ours was reported
        time.sleep(1)
        assert victim.poll() is None, "a reused PID must not be killed"
        assert ours.poll() is not None, "the recorded process must be stopped"
        assert not sandbox.state_dir.exists()
    finally:
        victim.kill()
        ours.kill()


def _ours(run: str, cid: str = "1" * 64, **over) -> dict:
    return {
        "id": cid,
        "name": f"nexus-local-voice-redis-{run[:8]}",
        "label": run,
        "image": "redis:7-alpine",
        **over,
    }


def _with_containers(sb: Sandbox, *containers: dict) -> None:
    sb.docker_state.write_text(json.dumps({"containers": [UNRELATED, *containers]}))


def test_container_is_removed_by_exact_id_after_label_name_and_image_check(sandbox):
    run = str(uuid.uuid4())
    _with_containers(sandbox, _ours(run))
    _write_state(sandbox, run=run, container={"id": "1" * 64, "name": "recorded"})
    r = sandbox.stop()
    assert r.returncode == 0 and "removed Redis container" in r.stdout
    assert sandbox.docker()["containers"] == [UNRELATED]
    assert sandbox.docker_calls() == [
        f"ps -aq --no-trunc --filter id={'1' * 64} --filter label=nexus.local-voice={run}",
        f"ps -a --no-trunc --filter id={'1' * 64} --format {{{{.Names}}}} {{{{.Image}}}}",
        f"rm -f {'1' * 64}",
    ]
    assert sandbox.stop().stdout.strip() == "PASS  nothing to stop"  # idempotent


@pytest.mark.parametrize(
    "case",
    [
        "label-of-another-run",  # a look-alike carrying someone else's run label
        "wrong-name",
        "wrong-image",
        "ps-returns-another-id",  # the exact ID must come back, not merely some ID
        "ps-returns-two-lines",
    ],
)
def test_container_that_is_not_provably_ours_is_left_alone(sandbox, case):
    run = str(uuid.uuid4())
    over = {
        "label-of-another-run": {"label": "another-run"},
        "wrong-name": {"name": "nexus-local-voice-redis-deadbeef"},
        "wrong-image": {"image": "postgres:16"},
    }.get(case, {})
    _with_containers(sandbox, _ours(run, **over))
    _write_state(sandbox, run=run, container={"id": "1" * 64, "name": "recorded"})
    env = (
        {"FAKE_DOCKER_PS": {"ps-returns-another-id": "other", "ps-returns-two-lines": "two"}[case]}
        if case.startswith("ps-")
        else {}
    )
    r = sandbox.stop(**env)
    assert r.returncode == 0 and "left alone" in r.stdout
    assert len(sandbox.docker()["containers"]) == 2, "nothing may be removed"
    assert not any(c.startswith(("rm", "inspect")) for c in sandbox.docker_calls())


def test_container_already_removed_is_not_an_error(sandbox):
    run = str(uuid.uuid4())
    _with_containers(sandbox)  # only the unrelated one
    _write_state(sandbox, run=run, container={"id": "1" * 64, "name": "gone"})
    r = sandbox.stop()
    assert r.returncode == 0 and "already gone" in r.stdout
    assert sandbox.docker()["containers"] == [UNRELATED]
    assert not any(c.startswith("rm") for c in sandbox.docker_calls())
    assert not sandbox.state_dir.exists()


@pytest.mark.parametrize(
    "bad_id",
    [
        "--all",
        "abc; docker rm -f " + "9" * 64,
        "$(calc)",
        "a b",
        "1" * 63,
        "G" * 64,
        "unrelated1",
        "9" * 64 + " --force",
        "",
    ],
)
def test_malicious_or_stale_state_never_reaches_docker(sandbox, bad_id):
    run = str(uuid.uuid4())
    _with_containers(sandbox, _ours(run))
    _write_state(sandbox, run=run, container={"id": bad_id, "name": "x"})
    r = sandbox.stop()
    assert r.returncode == 0
    assert sandbox.docker_calls() == []
    assert len(sandbox.docker()["containers"]) == 2


def test_malicious_run_id_never_reaches_docker(sandbox):
    _with_containers(sandbox, _ours("x"))
    _write_state(sandbox, run="x --filter id=" + "9" * 64, container={"id": "1" * 64, "name": "x"})
    sandbox.stop()
    assert sandbox.docker_calls() == []
    assert len(sandbox.docker()["containers"]) == 2


def test_state_is_kept_when_docker_cannot_be_asked(sandbox):
    run = str(uuid.uuid4())
    _with_containers(sandbox, _ours(run))
    _write_state(sandbox, run=run, container={"id": "1" * 64, "name": "x"})
    r = sandbox.stop(FAKE_DOCKER_DOWN="1")
    assert r.returncode == 1 and "Docker unavailable" in r.stdout
    assert (sandbox.state_dir / "state.json").exists(), "the record needed to remove it later stays"
    assert sandbox.stop().returncode == 0  # Docker is back: now it is removed
    assert sandbox.docker()["containers"] == [UNRELATED]
    assert not sandbox.state_dir.exists()


def test_docker_inspect_label_template_reproduces_the_powershell_quoting_failure(sandbox, tmp_path):
    """The original stop script's ownership check. PowerShell 5.1 drops the inner quotes, so Docker
    parses ``index .Config.Labels nexus.local-voice`` and fails: the container was never removed."""
    script = tmp_path / "old-check.ps1"
    script.write_text(
        "docker inspect -f '{{index .Config.Labels \"nexus.local-voice\"}}' " + "1" * 64 + "\n"
    )
    r = run_ps([*POWERSHELL, str(script)], sandbox.env(), sandbox.root, 60)
    assert 'function "nexus" not defined' in r.stdout + r.stderr
    (call,) = sandbox.docker_calls()
    assert call.startswith("inspect -f ") and '"' not in call, (
        "the quotes are gone before Docker sees the template"
    )
    code = [
        ln
        for ln in (SCRIPTS / "stop-local-voice.ps1").read_text().splitlines()
        if not ln.lstrip().startswith("#")
    ]
    assert not any("docker inspect" in ln for ln in code), (
        "the stop script must not depend on that template"
    )


def test_cloned_database_is_deleted_only_when_the_launcher_owns_it(sandbox, tmp_path):
    victim = tmp_path / "victim.db"
    victim.write_text("not ours")
    foreign = sandbox.state_dir / "keep-me.txt"
    run = str(uuid.uuid4())
    # A tampered state file points at a file outside the launcher's directory.
    _write_state(sandbox, run=run, db={"path": str(victim), "owner": run})
    foreign.write_text("foreign")
    (sandbox.state_dir / "acceptance.db").write_text("copy")
    r = sandbox.stop()
    assert victim.read_text() == "not ours"
    assert foreign.exists(), "files the launcher did not create stay"
    assert "left alone" in r.stdout
    # Wrong owner: the copy is left alone too.
    _write_state(
        sandbox,
        run=run,
        db={"path": str(sandbox.state_dir / "acceptance.db"), "owner": "someone-else"},
    )
    sandbox.stop()
    assert (sandbox.state_dir / "acceptance.db").exists()
    # Right owner and path: only the copy (and the launcher's own files) go.
    _write_state(
        sandbox, run=run, db={"path": str(sandbox.state_dir / "acceptance.db"), "owner": run}
    )
    sandbox.stop()
    assert not (sandbox.state_dir / "acceptance.db").exists()
    assert foreign.exists() and victim.exists()


# --- clone_sqlite.py --------------------------------------------------------------------


def _clone(src: Path, dst: Path, url: str | None = None):
    env = {**os.environ, "DATABASE_URL": url or f"sqlite+aiosqlite:///{src.as_posix()}"}
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "clone_sqlite.py"), str(dst)],
        env=env,
        capture_output=True,
        text=True,
    )


def test_clone_is_consistent_for_a_live_wal_database_and_never_writes_the_source(tmp_path):
    src = tmp_path / "live dir" / "dev.db"
    src.parent.mkdir()
    live = sqlite3.connect(src)
    live.execute("pragma journal_mode=wal")
    live.execute("create table t(x)")
    live.executemany("insert into t values (?)", [(i,) for i in range(500)])
    live.commit()  # committed rows may still sit in the -wal file: a raw copy of dev.db would miss them
    main_before = sha(src)
    dst = tmp_path / "copy.db"
    r = _clone(src, dst)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert sha(src) == main_before, "source main file changed"
    copy = sqlite3.connect(dst)
    assert copy.execute("select count(*) from t").fetchone()[0] == 500
    copy.execute("insert into t values (999)")
    copy.commit()
    copy.close()
    assert live.execute("select count(*) from t").fetchone()[0] == 500  # source untouched
    live.close()


def test_encrypted_secret_rows_stay_resolvable_in_the_backup(tmp_path, monkeypatch):
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import nexus.models  # noqa: F401  registers every table so the FK target exists
    from nexus.governance.secret_backend import FernetSecretBackend
    from nexus.models.secret import Secret

    src = tmp_path / "dev.db"
    key, value = "a-secret-key-for-this-test", "value-that-must-not-be-logged"

    def factory(path: Path):
        return async_sessionmaker(
            create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}"),
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def create():
        f = factory(src)
        async with f.kw["bind"].begin() as conn:
            await conn.run_sync(lambda c: Secret.metadata.create_all(c, tables=[Secret.__table__]))
        await f.kw["bind"].dispose()

    asyncio.run(create())
    assert FernetSecretBackend(key, session_factory=factory(src)).encrypt(
        "hermes_native_omniroute_api_key", value
    )
    dst = tmp_path / "copy.db"
    r = _clone(src, dst)
    assert r.returncode == 0
    assert value not in dst.read_bytes().decode("latin-1")  # rows stay encrypted
    assert (
        FernetSecretBackend(key, session_factory=factory(dst)).decrypt(
            "hermes_native_omniroute_api_key"
        )
        == value
    )
    assert (
        FernetSecretBackend("wrong-key", session_factory=factory(dst)).decrypt(
            "hermes_native_omniroute_api_key"
        )
        is None
    )


@pytest.mark.parametrize(
    "url", ["", "postgresql+asyncpg://u:p@h/db", "sqlite+aiosqlite:///:memory:"]
)
def test_clone_refuses_non_file_databases_without_echoing_the_url(tmp_path, url):
    r = _clone(tmp_path / "x.db", tmp_path / "c.db", url=url or " ")
    assert r.returncode == 2
    assert "u:p@h" not in r.stdout + r.stderr
    assert not (tmp_path / "c.db").exists()


def test_clone_will_not_overwrite_an_existing_file(tmp_path):
    src = tmp_path / "a.db"
    sqlite3.connect(src).close()
    dst = tmp_path / "b.db"
    dst.write_text("existing")
    assert _clone(src, dst).returncode == 2
    assert dst.read_text() == "existing"
