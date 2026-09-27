"""Acceptance driver for employee work attempts. Talks to the real API only.

usage:
  drive.py repo <port>                                   register calc-demo, print repo id
  drive.py task <port> <claude|agy> <spec.json> <title>  create a work task, print task id
  drive.py start <port> <task> [idem-key]                POST an attempt
  drive.py retry <port> <task> <attempt>
  drive.py watch <port> <task> [max-seconds]             poll attempts until the latest is terminal
  drive.py show <port> <task>                            print every attempt and its evidence
"""
import json, sys, time, uuid
from datetime import datetime, timezone
import httpx

C = "00000000-0000-4000-8000-0000000000e1"
AGENTS = {"claude": "00000000-0000-4000-8000-00000000c1a0", "agy": "00000000-0000-4000-8000-0000000000a9"}
TERMINAL = {"completed", "failed", "blocked", "cancelled", "expired"}

def now():
    return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]

def out(label, body):
    print(now(), label, json.dumps(body, sort_keys=True), flush=True)

def brief(a):
    r = a.get("report") or {}
    return {k: a.get(k) for k in ("id", "attempt_number", "status", "execution_id", "report_seq",
                                   "completion_reason", "error_code", "recoveries", "claimed_by",
                                   "session_id", "worktree_id", "cancelled_by")} | {
        "state": r.get("state"), "step": r.get("current_step"), "progress": r.get("progress_percent"),
        "backend": (a.get("usage") or {}).get("backend")}

def body(r):
    try:
        return r.json()
    except ValueError:
        return {"status": r.status_code, "text": r.text[:300]}

def main():
    cmd, port = sys.argv[1], sys.argv[2]
    c = httpx.Client(base_url=f"http://127.0.0.1:{port}", headers={"X-Company-Id": C}, timeout=60)
    if cmd == "repo":
        import os
        root = os.environ["REPOSITORY_ROOTS"].replace("{company_id}", C) + "/calc-demo"
        r = c.post(f"/api/v1/companies/{C}/repos", json={"name": "calc-demo", "url": "local://calc-demo",
                                                            "provider": "local", "local_path": root})
        print(r.status_code, r.json()["id"])
    elif cmd == "task":
        spec = json.load(open(sys.argv[4]))
        r = c.post(f"/api/v1/companies/{C}/tasks", json={
            "title": sys.argv[5], "assigned_agent_id": AGENTS[sys.argv[3]], "work_spec": spec})
        print(r.status_code, body(r).get("id") or body(r))
    elif cmd == "start":
        key = sys.argv[4] if len(sys.argv) > 4 else str(uuid.uuid4())
        r = c.post(f"/api/v1/tasks/{sys.argv[3]}/attempts", headers={"Idempotency-Key": key})
        out(f"start {r.status_code}", brief(r.json()) | {"created": r.json().get("created")}
            if r.status_code < 300 else body(r))
    elif cmd == "retry":
        r = c.post(f"/api/v1/tasks/{sys.argv[3]}/attempts/{sys.argv[4]}/retry")
        out(f"retry {r.status_code}", brief(r.json()) if r.status_code < 300 else body(r))
    elif cmd == "watch":
        limit = float(sys.argv[4]) if len(sys.argv) > 4 else 900
        last, t0 = None, time.time()
        while time.time() - t0 < limit:
            try:
                rows = c.get(f"/api/v1/tasks/{sys.argv[3]}/attempts").json()
            except httpx.HTTPError as exc:
                out("unreachable", {"error": type(exc).__name__}); time.sleep(1); continue
            view = brief(rows[0]) if rows else None
            if view != last:
                out("attempt", view); last = view
            if view and view["status"] in TERMINAL:
                break
            time.sleep(1)
    elif cmd == "show":
        task = c.get(f"/api/v1/tasks/{sys.argv[3]}").json()
        out("task", {k: task.get(k) for k in ("id", "title", "status", "completion_reason")})
        for a in c.get(f"/api/v1/tasks/{sys.argv[3]}/attempts").json()[::-1]:
            out("attempt", brief(a) | {"report": a.get("report")})
            ev = c.get(f"/api/v1/tasks/{sys.argv[3]}/attempts/{a['id']}/evidence").json()
            out("evidence", ev)

main()
