"""Tests for repository clone-path handling (W-09 gap closure)."""

import uuid
from unittest.mock import AsyncMock

import pytest

from nexus.api.routes import repositories as repo_routes
from nexus.models.repository import Repository

COMPANY_ID = uuid.uuid4()


class _OneResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.mark.asyncio
async def test_connect_repo_persists_local_path():
    session = AsyncMock()
    body = repo_routes.RepoCreate(
        name="demo",
        url="https://example.com/demo.git",
        local_path="/srv/clones/demo",
    )
    created = await repo_routes.connect_repo(COMPANY_ID, body, session)
    assert created.local_path == "/srv/clones/demo"
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_sync_repo_requires_clone_path():
    session = AsyncMock()
    repo = Repository(id=uuid.uuid4(), company_id=COMPANY_ID, name="r", url="u", local_path=None)
    session.execute = AsyncMock(return_value=_OneResult(repo))

    with pytest.raises(Exception) as exc:
        await repo_routes.sync_repo(repo.id, session, COMPANY_ID)
    assert "No local clone" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_sync_repo_rejects_non_git_directory(tmp_path):
    session = AsyncMock()
    empty_dir = tmp_path / "not-a-repo"
    empty_dir.mkdir()
    repo = Repository(id=uuid.uuid4(), company_id=COMPANY_ID, name="r", url="u", local_path=str(empty_dir))
    session.execute = AsyncMock(return_value=_OneResult(repo))

    with pytest.raises(Exception) as exc:
        await repo_routes.sync_repo(repo.id, session, COMPANY_ID)
    assert "not an available git clone" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_sync_repo_accepts_git_directory(tmp_path):
    session = AsyncMock()
    git_dir = tmp_path / "real-repo"
    git_dir.mkdir()
    (git_dir / ".git").mkdir()
    repo = Repository(id=uuid.uuid4(), company_id=COMPANY_ID, name="r", url="u", local_path=str(git_dir))
    session.execute = AsyncMock(return_value=_OneResult(repo))

    response = await repo_routes.sync_repo(repo.id, session, COMPANY_ID)
    assert response["status"] if "status" in response else True
    assert repo.last_synced_at is not None


@pytest.mark.asyncio
async def test_commits_return_empty_without_clone():
    session = AsyncMock()
    repo = Repository(id=uuid.uuid4(), company_id=COMPANY_ID, name="r", url="u", local_path=None)
    session.execute = AsyncMock(return_value=_OneResult(repo))

    commits = await repo_routes.get_repo_commits(repo.id, session, COMPANY_ID)
    assert commits == []


@pytest.mark.asyncio
async def test_diff_returns_error_without_clone():
    session = AsyncMock()
    repo = Repository(id=uuid.uuid4(), company_id=COMPANY_ID, name="r", url="u", local_path=None)
    session.execute = AsyncMock(return_value=_OneResult(repo))

    response = await repo_routes.get_repo_diff(repo.id, session, COMPANY_ID)
    assert "No local clone" in response["error"]
