"""The pipeline builder's save contract.

The builder saves the edited graph as the pipeline's ``stages`` through
``PUT /api/v1/pipelines/{id}``. What it saves must be what a reload reads
back, from both the single and the list route, and another tenant can
neither change nor see it. Creating, changing and deleting a pipeline needs
pipeline write permission; running, pausing and stopping one needs pipeline
execute permission. A refused request leaves every pipeline and run as it was.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.routes import pipelines
from nexus.auth.principal import Principal
from nexus.models.company import Company
from nexus.governance import rbac
from nexus.models.pipeline import Pipeline, PipelineRun

EXECUTOR_STAGE = {
    "id": "s1",
    "name": "Build",
    "prompt": "Compile the release",
    "agent_id": "agent-1",
    "quality_gate": {"min_score": 0.7},
}


@pytest.fixture
async def world(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pipelines.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)
    # A started run stays "running": these tests are about who may start,
    # pause and stop it, not about executing its stages.
    import nexus.temporal.client as temporal_client

    monkeypatch.setattr(temporal_client, "is_temporal_enabled", lambda: False)
    monkeypatch.setattr(pipelines, "_execute_pipeline_bg", lambda *args: None)

    acme, other = Company(name="Acme"), Company(name="Other")
    async with factory() as db:
        db.add_all([acme, other])
        await db.flush()
        pipeline = Pipeline(company_id=acme.id, name="Release", stages=[EXECUTOR_STAGE])
        db.add(pipeline)
        await db.commit()

    principals = {
        "manager": Principal(kind="user", company_id=acme.id, role="manager", user_id=uuid.uuid4()),
        "viewer": Principal(kind="user", company_id=acme.id, role="viewer", user_id=uuid.uuid4()),
        # A run token: acts as an agent of Acme.
        "agent": Principal(
            kind="run", company_id=acme.id, role="agent", run_id=uuid.uuid4(), agent_id=uuid.uuid4()
        ),
        "editor": Principal(kind="user", company_id=acme.id, role="editor", user_id=uuid.uuid4()),
        "operator": Principal(kind="user", company_id=acme.id, role="operator", user_id=uuid.uuid4()),
        "outsider": Principal(kind="user", company_id=other.id, role="admin", user_id=uuid.uuid4()),
    }
    app = FastAPI()
    app.include_router(pipelines.router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        request.state.principal = principals[request.headers["x-test-principal"]]
        return await call_next(request)

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield {"client": client, "factory": factory, "acme": acme.id, "other": other.id, "pipeline": pipeline.id}
    await client.aclose()
    await engine.dispose()


async def _call(w, who, method, path, body=None):
    return await w["client"].request(method, path, json=body, headers={"x-test-principal": who})


async def test_saved_stages_are_what_a_reload_reads(world) -> None:
    # What the builder sends: its own fields plus the executor fields it carried over.
    edited = [
        {"id": "t1", "name": "Kickoff", "category": "trigger", "x": 80, "y": 200},
        {
            **EXECUTOR_STAGE,
            "name": "Build and sign",
            "category": "ai",
            "nodeId": "agent_task",
            "params": {"model": "fast"},
            "x": 360,
            "y": 200,
        },
    ]
    path = f"/api/v1/pipelines/{world['pipeline']}"
    saved = await _call(world, "manager", "PUT", path, {"name": "Release v2", "stages": edited})
    assert saved.status_code == 200
    assert saved.json()["stages"] == edited

    single = (await _call(world, "manager", "GET", path)).json()
    company_path = f"/api/v1/companies/{world['acme']}/pipelines"
    listed = (await _call(world, "manager", "GET", company_path)).json()
    assert (single["name"], single["stages"]) == ("Release v2", edited)
    assert [(p["name"], p["stages"]) for p in listed] == [("Release v2", edited)]


async def test_another_tenant_cannot_save_over_a_pipeline(world) -> None:
    path = f"/api/v1/pipelines/{world['pipeline']}"
    refused = await _call(world, "outsider", "PUT", path, {"stages": []})
    assert refused.status_code == 404
    assert (await _call(world, "outsider", "GET", path)).status_code == 404
    assert (await _call(world, "manager", "GET", path)).json()["stages"] == [EXECUTOR_STAGE]


# --- Mutations need pipeline write permission. --------------------------------


async def _pipelines(w) -> list[tuple]:
    async with w["factory"]() as db:
        rows = (await db.execute(select(Pipeline).order_by(Pipeline.name))).scalars()
        return [(r.id, r.company_id, r.name, r.stages) for r in rows]


def _mutations(w, company=None) -> list[tuple[str, str, dict | None]]:
    company = company or w["acme"]
    single = f"/api/v1/pipelines/{w['pipeline']}"
    return [
        ("POST", f"/api/v1/companies/{company}/pipelines", {"name": "Hotfix"}),
        ("POST", f"/api/v1/companies/{company}/pipelines/import", {"name": "Imported"}),
        ("PUT", single, {"name": "Renamed", "stages": []}),
        ("DELETE", single, None),
    ]


async def test_an_authorized_role_may_create_change_and_delete(world) -> None:
    statuses = [
        (await _call(world, "manager", method, path, body)).status_code
        for method, path, body in _mutations(world)
    ]
    assert statuses == [201, 201, 200, 204]
    assert sorted(p[2] for p in await _pipelines(world)) == ["Hotfix", "Imported"]


async def test_a_viewer_may_read_but_not_change_pipelines(world) -> None:
    before = await _pipelines(world)
    for method, path, body in _mutations(world):
        refused = await _call(world, "viewer", method, path, body)
        assert refused.status_code == 403, (method, path, refused.text)
        assert refused.json()["detail"] == "Role 'viewer' may not write pipeline"
    assert await _pipelines(world) == before
    path = f"/api/v1/pipelines/{world['pipeline']}"
    assert (await _call(world, "viewer", "GET", path)).status_code == 200


async def test_another_company_cannot_change_or_delete_a_pipeline(world) -> None:
    before = await _pipelines(world)
    # Addressed by id: the pipeline is invisible to another tenant.
    changed = [
        (await _call(world, "outsider", method, path, body)).status_code
        for method, path, body in _mutations(world)[2:]
    ]
    # Addressed by company path: no standing in that company at all (as the
    # tenant middleware answers), so nothing can be created there.
    created = [
        (await _call(world, "outsider", method, path, body)).status_code
        for method, path, body in _mutations(world)[:2]
    ]
    assert (changed, created) == ([404, 404], [403, 403])
    assert await _pipelines(world) == before


# --- Running, pausing and stopping need pipeline execute permission. ---------


async def _runs(w) -> list[tuple]:
    async with w["factory"]() as db:
        rows = (await db.execute(select(PipelineRun).order_by(PipelineRun.started_at))).scalars()
        return [(r.id, r.company_id, r.status) for r in rows]


async def _seed_running(w) -> None:
    async with w["factory"]() as db:
        db.add(PipelineRun(pipeline_id=w["pipeline"], company_id=w["acme"], status="running"))
        await db.commit()


def _executions(w) -> list[str]:
    return [f"/api/v1/pipelines/{w['pipeline']}/{verb}" for verb in ("run", "pause", "stop")]


async def test_a_manager_may_run_pause_and_stop(world) -> None:
    run, pause, stop = [await _call(world, "manager", "POST", p) for p in _executions(world)]
    assert (run.status_code, pause.status_code, stop.status_code) == (201, 200, 200)
    assert pause.json() == {"run_id": run.json()["id"], "status": "paused"}
    assert await _runs(world) == [(uuid.UUID(run.json()["id"]), world["acme"], "cancelled")]


@pytest.mark.parametrize("who", ["viewer", "agent"])
async def test_roles_without_execute_cannot_run_pause_or_stop(world, who) -> None:
    await _seed_running(world)
    before = (await _pipelines(world), await _runs(world))
    for path in _executions(world):
        refused = await _call(world, who, "POST", path)
        assert refused.status_code == 403, (path, refused.text)
        assert refused.json()["detail"] == f"Role '{who}' may not execute pipeline"
    assert (await _pipelines(world), await _runs(world)) == before


async def test_another_company_cannot_run_pause_or_stop(world) -> None:
    await _seed_running(world)
    before = (await _pipelines(world), await _runs(world))
    statuses = [(await _call(world, "outsider", "POST", p)).status_code for p in _executions(world)]
    assert statuses == [404, 404, 404]
    assert (await _pipelines(world), await _runs(world)) == before


async def test_write_and_execute_are_granted_separately(world, monkeypatch) -> None:
    read = rbac.Permission(action="read", resource_type="*", resource_id="*")
    for name, action in (("editor", "write"), ("operator", "execute")):
        grant = rbac.Permission(action=action, resource_type="pipeline", resource_id="*")
        monkeypatch.setitem(rbac.STANDARD_ROLES, name, rbac.Role(name=name, permissions=[read, grant]))
    run_path = _executions(world)[0]
    edit_path, edit = f"/api/v1/pipelines/{world['pipeline']}", {"name": "Renamed"}

    assert (await _call(world, "editor", "POST", run_path)).status_code == 403
    assert (await _call(world, "operator", "PUT", edit_path, edit)).status_code == 403
    assert (await _call(world, "editor", "PUT", edit_path, edit)).status_code == 200
    assert (await _call(world, "operator", "POST", run_path)).status_code == 201
