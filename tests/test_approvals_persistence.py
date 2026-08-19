"""Tests for ApprovalEngine persistence, history, and notification features."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nexus.governance.approvals import (
    ApprovalEngine,
    ApprovalRequest,
    AutoApprovalPolicy,
)


@pytest.fixture
def tmp_path_file(tmp_path: Path) -> Path:
    """Return a path to a non-existent JSON file in a temp directory."""
    return tmp_path / "approvals.json"


@pytest.fixture
def company_id() -> uuid.UUID:
    """Return a fixed company UUID for tests."""
    return uuid.uuid4()


@pytest.fixture
def agent_id() -> uuid.UUID:
    """Return a fixed agent UUID for tests."""
    return uuid.uuid4()


# --- Backward compatibility ---


async def test_persist_path_none_keeps_in_memory_only(
    company_id: uuid.UUID, agent_id: uuid.UUID
) -> None:
    """Engine with persist_path=None operates in memory only (backward compat)."""
    engine = ApprovalEngine()
    req = await engine.submit_for_approval(
        company_id=company_id,
        approval_type="budget_override",
        requested_by_agent_id=agent_id,
        payload={"cost_cents": 100},
    )
    assert req.status == "pending"
    assert engine.get_approval(req.id) is req


# --- Persistence roundtrip ---


async def test_submit_persists_and_new_instance_loads_state(
    tmp_path_file: Path, company_id: uuid.UUID, agent_id: uuid.UUID
) -> None:
    """Submitted approval survives a simulated restart (new instance reads file)."""
    engine = ApprovalEngine(persist_path=tmp_path_file)
    req = await engine.submit_for_approval(
        company_id=company_id,
        approval_type="tool_access",
        requested_by_agent_id=agent_id,
        payload={"tool": "browser"},
    )

    # Simulated restart: create a new engine pointing at same file
    engine2 = ApprovalEngine(persist_path=tmp_path_file)
    loaded = engine2.get_approval(req.id)

    assert loaded is not None
    assert loaded.id == req.id
    assert loaded.company_id == company_id
    assert loaded.requested_by_agent_id == agent_id
    assert loaded.type == "tool_access"
    assert loaded.payload == {"tool": "browser"}
    assert loaded.status == "pending"
    assert isinstance(loaded.id, uuid.UUID)
    assert isinstance(loaded.created_at, datetime)


async def test_process_approval_persists_updated_state(
    tmp_path_file: Path, company_id: uuid.UUID, agent_id: uuid.UUID
) -> None:
    """Processing an approval persists the updated decision state."""
    engine = ApprovalEngine(persist_path=tmp_path_file)
    req = await engine.submit_for_approval(
        company_id=company_id,
        approval_type="deployment",
        requested_by_agent_id=agent_id,
        payload={"env": "production"},
    )

    await engine.process_approval(
        approval_id=req.id,
        decision="approved",
        decided_by="admin@example.com",
        note="Looks good",
    )

    # Reload from file
    engine2 = ApprovalEngine(persist_path=tmp_path_file)
    loaded = engine2.get_approval(req.id)

    assert loaded is not None
    assert loaded.status == "approved"
    assert loaded.decided_by == "admin@example.com"
    assert loaded.decision_note == "Looks good"
    assert loaded.decided_at is not None
    assert isinstance(loaded.decided_at, datetime)


# --- get_approval_history ---


async def test_get_approval_history_returns_resolved_sorted(
    tmp_path_file: Path, company_id: uuid.UUID, agent_id: uuid.UUID
) -> None:
    """get_approval_history returns only resolved approvals sorted by decided_at desc."""
    engine = ApprovalEngine(persist_path=tmp_path_file)

    # Submit three approvals
    req1 = await engine.submit_for_approval(
        company_id=company_id,
        approval_type="deploy",
        requested_by_agent_id=agent_id,
        payload={},
    )
    req2 = await engine.submit_for_approval(
        company_id=company_id,
        approval_type="deploy",
        requested_by_agent_id=agent_id,
        payload={},
    )
    req3 = await engine.submit_for_approval(
        company_id=company_id,
        approval_type="deploy",
        requested_by_agent_id=agent_id,
        payload={},
    )

    # Process them in order (req1 first, req3 last)
    await engine.process_approval(req1.id, "approved", "user1")
    await engine.process_approval(req2.id, "denied", "user2")
    # req3 stays pending

    history = engine.get_approval_history(company_id)

    # Only resolved (approved/denied), not pending
    assert len(history) == 2
    assert all(h.status in ("approved", "denied") for h in history)
    # Most recent decided_at first
    assert history[0].decided_at >= history[1].decided_at  # type: ignore[operator]


async def test_get_approval_history_respects_limit(
    tmp_path_file: Path, company_id: uuid.UUID, agent_id: uuid.UUID
) -> None:
    """get_approval_history respects the limit parameter."""
    engine = ApprovalEngine(persist_path=tmp_path_file)

    for _ in range(5):
        req = await engine.submit_for_approval(
            company_id=company_id,
            approval_type="deploy",
            requested_by_agent_id=agent_id,
            payload={},
        )
        await engine.process_approval(req.id, "approved", "admin")

    history = engine.get_approval_history(company_id, limit=3)
    assert len(history) == 3


# --- on_approval_needed callback ---


async def test_on_approval_needed_fires_for_pending(
    tmp_path_file: Path, company_id: uuid.UUID, agent_id: uuid.UUID
) -> None:
    """on_approval_needed callback fires for pending requests."""
    callback = MagicMock()
    engine = ApprovalEngine(persist_path=tmp_path_file, on_approval_needed=callback)

    req = await engine.submit_for_approval(
        company_id=company_id,
        approval_type="budget_override",
        requested_by_agent_id=agent_id,
        payload={"cost_cents": 500},
    )

    callback.assert_called_once_with(req)


async def test_on_approval_needed_does_not_fire_for_auto_approved(
    tmp_path_file: Path, company_id: uuid.UUID, agent_id: uuid.UUID
) -> None:
    """on_approval_needed callback does NOT fire for auto-approved requests."""
    callback = MagicMock()
    engine = ApprovalEngine(persist_path=tmp_path_file, on_approval_needed=callback)

    # Add a policy that auto-approves budget_override under 1000 cents
    policy = AutoApprovalPolicy(
        company_id=company_id,
        approval_type="budget_override",
        conditions={"max_cost_cents": 1000},
    )
    engine.add_policy(policy)

    req = await engine.submit_for_approval(
        company_id=company_id,
        approval_type="budget_override",
        requested_by_agent_id=agent_id,
        payload={"cost_cents": 100},
    )

    assert req.status == "approved"
    callback.assert_not_called()


async def test_on_approval_needed_none_does_not_crash(
    tmp_path_file: Path, company_id: uuid.UUID, agent_id: uuid.UUID
) -> None:
    """on_approval_needed=None does not crash when submitting."""
    engine = ApprovalEngine(persist_path=tmp_path_file, on_approval_needed=None)

    req = await engine.submit_for_approval(
        company_id=company_id,
        approval_type="budget_override",
        requested_by_agent_id=agent_id,
        payload={},
    )

    assert req.status == "pending"


# --- Atomic write safety ---


async def test_atomic_write_produces_valid_json(
    tmp_path_file: Path, company_id: uuid.UUID, agent_id: uuid.UUID
) -> None:
    """After a save, the persisted file contains valid JSON."""
    engine = ApprovalEngine(persist_path=tmp_path_file)
    await engine.submit_for_approval(
        company_id=company_id,
        approval_type="deploy",
        requested_by_agent_id=agent_id,
        payload={"env": "staging"},
    )

    # File should exist and be valid JSON
    assert tmp_path_file.exists()
    content = tmp_path_file.read_text(encoding="utf-8")
    data = json.loads(content)
    assert isinstance(data, dict)
    assert len(data) == 1


# --- Missing/corrupt file handling ---


async def test_missing_file_on_init_starts_empty(tmp_path_file: Path) -> None:
    """Engine with a persist_path pointing to a non-existent file starts empty."""
    engine = ApprovalEngine(persist_path=tmp_path_file)
    assert engine.get_pending_approvals() == []


async def test_corrupt_file_on_init_starts_empty(tmp_path_file: Path) -> None:
    """Engine handles a corrupt (invalid JSON) persistence file gracefully."""
    tmp_path_file.write_text("not valid json {{{{", encoding="utf-8")

    engine = ApprovalEngine(persist_path=tmp_path_file)
    assert engine.get_pending_approvals() == []
