"""WP-22e / M7: budget infra failure fails closed (R12).

At baseline `_reserve_budget` caught every exception and returned None
("allowing call") — fail-open. R12 requires fail-closed: if the ledger is
unreachable the call is refused, unless BUDGET_FAIL_OPEN is set.

R1: tests invoke _reserve_budget. R10: no network — the ledger failure is
injected by monkeypatching BudgetService to raise.
"""

import uuid

import pytest

from nexus.api.routes import chat as chat_module
from nexus.config import settings
from nexus.models_router.preflight import BudgetInfraUnavailable


class _FakeAgent:
    id = uuid.uuid4()
    company_id = uuid.uuid4()
    adapter_type = "anthropic"
    name = "Tester"


def _break_budget_service(monkeypatch):
    """Make any BudgetService(...) construction raise, simulating a dead ledger."""
    def boom(*a, **k):
        raise RuntimeError("ledger unreachable")

    monkeypatch.setattr(chat_module, "BudgetService", boom, raising=False)
    # BudgetService is imported inside _reserve_budget from the service module;
    # patch it there too so the local import picks up the broken one.
    import nexus.services.budget_service as bs
    monkeypatch.setattr(bs, "BudgetService", boom)


async def _reserve(agent):
    return await chat_module._reserve_budget(
        agent, "sys", "hello", [], {"model": "claude-haiku-4-5"}
    )


async def test_budget_infra_failure_refuses_call(monkeypatch):
    """Fail-closed: ledger error raises BudgetInfraUnavailable (R12)."""
    _break_budget_service(monkeypatch)
    monkeypatch.setattr(settings, "budget_fail_open", False)

    with pytest.raises(BudgetInfraUnavailable):
        await _reserve(_FakeAgent())


async def test_budget_infra_failure_allows_when_fail_open(monkeypatch):
    """Escape hatch: BUDGET_FAIL_OPEN=true keeps the old allow-on-error path."""
    _break_budget_service(monkeypatch)
    monkeypatch.setattr(settings, "budget_fail_open", True)

    # Returns None (no hold), call proceeds — no exception.
    assert await _reserve(_FakeAgent()) is None
