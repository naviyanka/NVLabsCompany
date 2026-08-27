# Backend Supervisor & Runtime Control

The dashboard can **start, stop, and restart the backend** from
Settings → System Hyperparameters → *Backend Runtime Control*. This works even
when the backend is down, because the controls talk to a small always-on
**supervisor daemon**, not to the backend itself.

## Why a supervisor

A browser cannot spawn OS processes, and a dead backend cannot restart itself
(nothing is listening). So a separate, dependency-free process owns the
backend's lifecycle. The dashboard calls the supervisor; the supervisor
starts/kills the backend.

```
Browser (dashboard :3000)
   │  /api/supervisor/*   (proxied by dashboard/server.ts)
   ▼
Supervisor daemon (:8001)  ── spawns / kills ──▶  Backend uvicorn (:8000)
```

## Running it

Start the supervisor once (it is the one always-on piece):

```powershell
./scripts/start_supervisor.ps1
# or, from the src/ directory:
python -m nexus.supervisor
```

Then use the dashboard's Runtime Control panel, or call it directly:

| Method | Path (direct)            | Via dashboard proxy               | Action |
|--------|--------------------------|-----------------------------------|--------|
| GET    | `:8001/status`           | `/api/supervisor/status`          | backend running? healthy? pid, uptime |
| POST   | `:8001/start`            | `/api/supervisor/start`           | spawn the backend if not running |
| POST   | `:8001/stop`             | `/api/supervisor/stop`            | terminate the backend (graceful → force) |
| POST   | `:8001/restart`          | `/api/supervisor/restart`         | force-kill + start |

## Behavior & limits

- **Binds to 127.0.0.1 only.** It manages one local backend; it is not a remote
  control surface.
- **Zero third-party deps** (stdlib `http.server` + `subprocess`). A broken
  backend import can never stop the supervisor from restarting it.
- **`owned` flag**: `status` reports `owned: false` when a backend is running
  that the supervisor did not spawn (e.g. one started by hand in a terminal).
  Health is still detected; stop/restart of an unowned process is best-effort
  (frees port 8000 on Windows via `taskkill`/`netstat`).
- **If the supervisor itself is not running**, the panel says so and shows the
  one command to start it. That is the only piece the UI cannot bootstrap.
- **Windows**: process trees are killed with `taskkill /F /T` because uvicorn's
  reloader spawns children that a plain terminate would orphan.

## Backend environment

The supervisor launches the backend with these defaults (any value already set
in the supervisor's own environment wins, so you can override before launch):

```
AUTH_ENABLED = true
DATABASE_URL = sqlite+aiosqlite:///./nexus_dev.db
CEO_API_KEY  = nv_...              (service account key)
SECRET_KEY   = <vault key>          (required for the secrets vault)
```

Ports are overridable via `SUPERVISOR_PORT` (default 8001) and `BACKEND_PORT`
(default 8000).
