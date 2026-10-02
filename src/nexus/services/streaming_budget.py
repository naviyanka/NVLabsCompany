"""Per-round budget metering for a streamed, tool-looping model call.

One reservation is taken before every outbound round and settled or released when
that round ends, whether it finished, was cancelled, timed out or failed. Round
holds are independent, so a later round is refused (not silently allowed) once an
earlier round has used the budget, and spend from completed rounds is never lost
when a later round fails.

Settlement uses the provider's authoritative usage when it sent any; otherwise a
conservative bounded estimate once the stream has started (so an early end never
reads as zero). A round that never started (HTTP refusal, cancel before the first
byte) bills nothing and its hold is released.

Identity: ``cost_events`` has company, agent and chat session. The durable turn and
execution ids are not columns (no migration here), so they are logged on every
settlement and carried by the tool-call audit rows.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 3  # conservative: fewer chars per token means a higher estimate

# Registry keys whose adapter meters every round itself; callers must not also reserve.
SELF_METERED = frozenset({"azure_openai_native"})


@dataclass
class Hold:
    ids: list[Any]
    input_tokens: int
    cents: int


class RoundMeter:
    """``governed_loop.Meter`` backed by ``BudgetService`` reservations."""

    def __init__(
        self,
        *,
        company_id: uuid.UUID,
        agent_id: uuid.UUID | None,
        provider: str,
        model: str,
        max_output_tokens: int,
        session_id: uuid.UUID | None = None,
        turn_id: uuid.UUID | None = None,
        execution_id: uuid.UUID | None = None,
    ) -> None:
        self.company_id = company_id
        self.agent_id = agent_id
        self.provider = provider
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.session_id = session_id
        self.turn_id = turn_id
        self.execution_id = execution_id

    def _cents(self, input_tokens: int, output_tokens: int) -> int:
        from nexus.models_router.pricing import TokenSplit, estimate_cost_usd

        usd = estimate_cost_usd(self.model, TokenSplit(input_tokens, output_tokens))
        return math.ceil(usd * 100) if input_tokens or output_tokens else 0

    async def begin(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Hold | None:
        from nexus.config import settings
        from nexus.models_router.preflight import BudgetExceededError, BudgetInfraUnavailable
        from nexus.models_router.pricing import TokenSplit, estimate_cost_usd

        chars = len(json.dumps(messages, default=str)) + len(json.dumps(tools, default=str))
        input_tokens = math.ceil(chars / CHARS_PER_TOKEN)
        # Worst case for this round: the whole prompt plus the full output bound.
        cents = max(1, self._cents(input_tokens, self.max_output_tokens))
        try:
            from nexus.database import tenant_session
            from nexus.services.budget_service import BudgetService

            async with tenant_session(self.company_id) as db:
                allowed, ids, result = await BudgetService(db).reserve_chain(
                    company_id=self.company_id,
                    estimate_cents=cents,
                    agent_id=self.agent_id,
                    provider=self.provider,
                    model=self.model,
                )
                if self.session_id is not None and ids:
                    await self._link(db, ids)
        except Exception as exc:  # noqa: BLE001 -- the ledger is unreachable
            if settings.budget_fail_open:
                logger.warning("Budget reservation failed, allowing round (fail-open): %s", exc)
                return None
            logger.error("Budget reservation failed, refusing round (fail-closed): %s", exc)
            raise BudgetInfraUnavailable(
                "Budget ledger is unavailable and BUDGET_FAIL_OPEN is off"
            ) from exc
        if not allowed:
            usd = estimate_cost_usd(self.model, TokenSplit(input_tokens, self.max_output_tokens))
            raise BudgetExceededError(
                self.model, usd, result.used_cents / 100.0, result.limit_cents / 100.0
            )
        return Hold(ids, input_tokens, cents) if ids else None

    async def _link(self, db: Any, ids: list[Any]) -> None:
        try:
            from sqlalchemy import update

            from nexus.models.budget import CostEvent

            await db.execute(
                update(CostEvent)
                .where(CostEvent.company_id == self.company_id, CostEvent.id.in_(ids))
                .values(session_id=self.session_id)
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 -- attribution must not refuse a round
            logger.warning("Could not link cost events to session %s: %s", self.session_id, exc)

    async def end(
        self, hold: Hold | None, usage: dict[str, Any] | None, started: bool, output_chars: int
    ) -> None:
        if hold is None:
            return
        in_tok = int((usage or {}).get("prompt_tokens") or 0)
        out_tok = int((usage or {}).get("completion_tokens") or 0)
        source = "usage"
        if not (in_tok or out_tok):
            source = "estimate"
            if started:
                in_tok = hold.input_tokens
                out_tok = min(
                    max(1, math.ceil(output_chars / CHARS_PER_TOKEN)), self.max_output_tokens
                )
        cents = max(1, self._cents(in_tok, out_tok)) if (in_tok or out_tok) else 0
        logger.info(
            "streamed round settled company=%s agent=%s turn=%s execution=%s source=%s cents=%s",
            self.company_id, self.agent_id, self.turn_id, self.execution_id,
            source if cents else "released", cents,
        )
        try:
            from nexus.database import tenant_session
            from nexus.services.budget_service import BudgetService

            for rid in hold.ids:
                async with tenant_session(self.company_id) as db:
                    service = BudgetService(db)
                    if cents > 0:
                        await service.commit_reservation(
                            rid, cost_cents=cents, input_tokens=in_tok,
                            output_tokens=out_tok, model=self.model,
                        )
                    else:
                        await service.release_reservation(rid)
        except Exception as exc:  # noqa: BLE001 -- the hold expires on its own TTL
            logger.warning("Budget settlement failed for %s: %s", hold.ids, exc)
