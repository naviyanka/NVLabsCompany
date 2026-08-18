"""Persistent Kill Switch - database-backed emergency controls.

Stores kill switch state in PostgreSQL so it survives process restarts.
On startup, loads all active kill switches from the database and syncs
with the in-memory middleware registry.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


class PersistentKillSwitch:
    """Database-backed kill switch that survives restarts.

    Stores activation/deactivation events in the `kill_switch_records` table.
    Syncs with the in-memory _KillSwitchRegistry used by the ASGI middleware
    for fast per-request checks.

    Usage:
        kill_switch = PersistentKillSwitch(async_session_factory)
        await kill_switch.load_active()  # On startup
        await kill_switch.activate(company_id, reason, activated_by)
        await kill_switch.deactivate(company_id)
        is_killed = await kill_switch.is_active(company_id)
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Initialize with a session factory.

        Args:
            session_factory: SQLAlchemy async session factory.
        """
        self._session_factory = session_factory

    async def activate(
        self,
        company_id: uuid.UUID,
        reason: str,
        activated_by: str = "system",
    ) -> dict[str, Any]:
        """Activate the kill switch for a company (persists to DB).

        Args:
            company_id: The company to shut down.
            reason: Why the kill switch is being activated.
            activated_by: Who is activating it (user/system/incident).

        Returns:
            Dict with activation details.
        """
        from nexus.governance.kill_switch_model import KillSwitchRecord
        from nexus.api.middleware import kill_switch_registry

        now = datetime.utcnow()

        async with self._session_factory() as session:
            # Check if already active
            stmt = select(KillSwitchRecord).where(
                KillSwitchRecord.company_id == company_id,
                KillSwitchRecord.is_active == True,  # noqa: E712
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # Already active — update reason
                existing.reason = reason
                existing.activated_by = activated_by
                await session.commit()
            else:
                # Create new activation record
                record = KillSwitchRecord(
                    company_id=company_id,
                    is_active=True,
                    reason=reason,
                    activated_at=now,
                    activated_by=activated_by,
                )
                session.add(record)
                await session.commit()

        # Sync to in-memory registry for fast middleware checks
        kill_switch_registry.activate(company_id)

        logger.warning(
            "Kill switch ACTIVATED for company %s: %s (by %s)",
            company_id,
            reason,
            activated_by,
        )

        return {
            "company_id": str(company_id),
            "is_active": True,
            "reason": reason,
            "activated_at": now.isoformat(),
            "activated_by": activated_by,
        }

    async def deactivate(
        self,
        company_id: uuid.UUID,
        deactivated_by: str = "system",
    ) -> dict[str, Any]:
        """Deactivate the kill switch for a company.

        Args:
            company_id: The company to resume.
            deactivated_by: Who is deactivating it.

        Returns:
            Dict with deactivation details.
        """
        from nexus.governance.kill_switch_model import KillSwitchRecord
        from nexus.api.middleware import kill_switch_registry

        now = datetime.utcnow()

        async with self._session_factory() as session:
            stmt = (
                update(KillSwitchRecord)
                .where(
                    KillSwitchRecord.company_id == company_id,
                    KillSwitchRecord.is_active == True,  # noqa: E712
                )
                .values(
                    is_active=False,
                    deactivated_at=now,
                )
            )
            await session.execute(stmt)
            await session.commit()

        # Sync to in-memory registry
        kill_switch_registry.deactivate(company_id)

        logger.info(
            "Kill switch DEACTIVATED for company %s (by %s)",
            company_id,
            deactivated_by,
        )

        return {
            "company_id": str(company_id),
            "is_active": False,
            "deactivated_at": now.isoformat(),
            "deactivated_by": deactivated_by,
        }

    async def is_active(self, company_id: uuid.UUID) -> bool:
        """Check if the kill switch is active for a company (from DB).

        For hot-path checks, use the in-memory middleware registry directly.
        This method queries the database for authoritative state.

        Args:
            company_id: The company to check.

        Returns:
            True if the kill switch is currently active.
        """
        from nexus.governance.kill_switch_model import KillSwitchRecord

        async with self._session_factory() as session:
            stmt = select(KillSwitchRecord).where(
                KillSwitchRecord.company_id == company_id,
                KillSwitchRecord.is_active == True,  # noqa: E712
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def load_active(self) -> int:
        """Load all active kill switches from DB into memory on startup.

        Called during application startup to sync the in-memory registry
        with persisted state.

        Returns:
            Number of active kill switches loaded.
        """
        from nexus.governance.kill_switch_model import KillSwitchRecord
        from nexus.api.middleware import kill_switch_registry

        async with self._session_factory() as session:
            stmt = select(KillSwitchRecord).where(
                KillSwitchRecord.is_active == True  # noqa: E712
            )
            result = await session.execute(stmt)
            records = list(result.scalars().all())

        for record in records:
            kill_switch_registry.activate(record.company_id)

        if records:
            logger.info(
                "Loaded %d active kill switch(es) from database",
                len(records),
            )

        return len(records)

    async def get_history(
        self,
        company_id: uuid.UUID,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get kill switch activation history for a company.

        Args:
            company_id: The company to query.
            limit: Maximum number of records to return.

        Returns:
            List of activation records ordered by most recent first.
        """
        from nexus.governance.kill_switch_model import KillSwitchRecord

        async with self._session_factory() as session:
            stmt = (
                select(KillSwitchRecord)
                .where(KillSwitchRecord.company_id == company_id)
                .order_by(KillSwitchRecord.activated_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            records = list(result.scalars().all())

        return [
            {
                "id": str(r.id),
                "company_id": str(r.company_id),
                "is_active": r.is_active,
                "reason": r.reason,
                "activated_at": r.activated_at.isoformat() if r.activated_at else None,
                "activated_by": r.activated_by,
                "deactivated_at": r.deactivated_at.isoformat() if r.deactivated_at else None,
            }
            for r in records
        ]
