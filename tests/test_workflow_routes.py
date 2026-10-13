"""The legacy workflow routes can no longer start ungoverned work.

``POST /api/v1/workflows/company`` and ``/task`` used to run CompanyWorkflow /
TaskFlow in an in-process ``asyncio`` task with no budget reservation, approval
gate, lease or recovery. They now answer ``410 Gone`` and create nothing. The
read routes stay tenant scoped and never execute anything.

Requests go through the real router; the principal is placed in the ASGI scope
the way ``AuthenticationMiddleware`` does, and the DB session is a recorder, so
any row the routes tried to create or any engine they tried to start is visible.
"""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from nexus.api.deps import get_db
from nexus.api.routes import workflows as wf_routes
from nexus.auth.principal import Principal
from nexus.models.workflow_run import WorkflowRun

COMPANY_ID = uuid.uuid4()
OTHER_COMPANY_ID = uuid.uuid4()


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _RecordingSession:
    """Answers every query with ``rows`` and records writes."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.added: list = []
        self.queries = 0

    async def execute(self, _stmt):
        self.queries += 1
        return _Result(self.rows)

    def add(self, obj):
        self.added.append(obj)


def _run(status_value="running", company_id=COMPANY_ID) -> WorkflowRun:
    return WorkflowRun(
        id=uuid.uuid4(),
        company_id=company_id,
        workflow_type="company",
        status=status_value,
        objective="obj",
        steps=[],
        total_cost_cents=0,
        started_at=datetime.now(UTC).replace(tzinfo=None),
    )


def _client(session: _RecordingSession, principal: Principal | None) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(wf_routes.router)

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db

    async def asgi(scope, receive, send):
        if principal is not None:
            scope.setdefault("state", {})["principal"] = principal
        await app(scope, receive, send)

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=asgi), base_url="http://t")


def _member(company_id=COMPANY_ID, role="admin") -> Principal:
    return Principal(kind="user", company_id=company_id, role=role, user_id=uuid.uuid4())


@pytest.fixture
def no_engines(monkeypatch):
    """Fail loudly if anything constructs a legacy engine during a request."""
    import nexus.workflows.company_flow as company_flow
    import nexus.workflows.task_flow as task_flow

    def boom(*_a, **_k):
        raise AssertionError("legacy engine constructed")

    monkeypatch.setattr(company_flow.CompanyWorkflow, "__init__", boom)
    monkeypatch.setattr(task_flow.TaskFlow, "__init__", boom)


START_ROUTES = ("/api/v1/workflows/company", "/api/v1/workflows/task")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", START_ROUTES)
async def test_start_routes_are_gone_and_create_nothing(path, no_engines):
    session = _RecordingSession()
    async with _client(session, _member()) as client:
        # Retries of the same request: each one is refused, none creates work.
        for _ in range(3):
            response = await client.post(path, json={"objective": "Ship the thing"})
            assert response.status_code == 410
            assert response.json()["code"] == wf_routes.LEGACY_WORKFLOW_START_DISABLED
            assert "/api/v1/work" in response.json()["detail"]
    assert session.added == []
    assert session.queries == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("path", START_ROUTES)
async def test_start_routes_still_require_authentication(path, no_engines):
    session = _RecordingSession()
    async with _client(session, None) as client:
        response = await client.post(path, json={"objective": "x"})
    assert response.status_code == 401
    assert session.added == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", START_ROUTES)
async def test_start_routes_refuse_any_body_including_a_foreign_company(path, no_engines):
    session = _RecordingSession()
    async with _client(session, _member()) as client:
        response = await client.post(
            path, json={"objective": "x", "company_id": str(OTHER_COMPANY_ID)}
        )
    assert response.status_code == 410
    assert session.added == []


def test_no_background_runner_remains():
    """The in-process runners and their task registry are gone, not just unused."""
    for name in (
        "_running_tasks",
        "_run_company_flow",
        "_run_task_flow",
        "_register_company_agents",
        "_persist_completion",
    ):
        assert not hasattr(wf_routes, name), name


@pytest.mark.asyncio
async def test_read_routes_return_rows_without_executing(no_engines):
    run = _run("running")
    session = _RecordingSession([run])
    async with _client(session, _member()) as client:
        status_resp = await client.get(f"/api/v1/workflows/{run.id}/status")
        trace_resp = await client.get(f"/api/v1/workflows/{run.id}/trace")
        list_resp = await client.get(f"/api/v1/companies/{COMPANY_ID}/workflows")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "running"
    assert trace_resp.status_code == 200
    assert list_resp.status_code == 200
    assert isinstance(list_resp.json(), list)
    assert run.status == "running"
    assert session.added == []


@pytest.mark.asyncio
async def test_list_refuses_another_companys_id():
    session = _RecordingSession([_run(company_id=OTHER_COMPANY_ID)])
    async with _client(session, _member()) as client:
        response = await client.get(f"/api/v1/companies/{OTHER_COMPANY_ID}/workflows")
    assert response.status_code == 403
    assert session.queries == 0


@pytest.mark.asyncio
async def test_status_of_unknown_or_malformed_id_is_404():
    session = _RecordingSession([])
    async with _client(session, _member()) as client:
        assert (await client.get("/api/v1/workflows/not-a-uuid/status")).status_code == 404
        assert (await client.get(f"/api/v1/workflows/{uuid.uuid4()}/trace")).status_code == 404


@pytest.mark.asyncio
async def test_cancel_marks_a_stranded_run_cancelled(no_engines):
    run = _run("running")
    session = _RecordingSession([run])
    async with _client(session, _member()) as client:
        response = await client.post(f"/api/v1/workflows/{run.id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert run.status == "cancelled"
    assert run.completed_at is not None


@pytest.mark.asyncio
async def test_cancel_never_rewrites_a_terminal_run():
    run = _run("failed")
    session = _RecordingSession([run])
    async with _client(session, _member()) as client:
        response = await client.post(f"/api/v1/workflows/{run.id}/cancel")
    assert response.status_code == 200
    assert run.status == "failed"
    assert session.added == []


@pytest.mark.asyncio
async def test_cancel_requires_write_permission():
    run = _run("running")
    session = _RecordingSession([run])
    async with _client(session, _member(role="viewer")) as client:
        response = await client.post(f"/api/v1/workflows/{run.id}/cancel")
    assert response.status_code == 403
    assert run.status == "running"
