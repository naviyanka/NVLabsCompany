"""Company export/import (Phase 5.3).

A company is the tenant boundary, so "the company graph" is every row in every
table that carries a ``company_id``, plus the child rows those own through a
foreign key (a secret's versions, a meeting's participants, an agent's skills).
Rather than hand-listing ~75 tables and drifting the moment a model lands, both
directions walk ``SQLModel.metadata``: the schema already records which tables
are tenant-scoped and which foreign keys connect them.

Export scrubs secret material by column name and records what it removed, so an
archive is safe to hand over and the recipient can see the holes. Import mints a
fresh UUID for every row and rewrites every reference, so an archive can be
restored into the database it came from without colliding with the original.
"""

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Table, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.models._time import utcnow

ARCHIVE_VERSION = 1

#: Substrings that mark a column as secret material. Matched against the column
#: name, because the value itself is opaque -- an encrypted blob and a display
#: name are both just strings by the time they reach here.
SCRUB_PATTERNS = (
    "encrypted",
    "password",
    "token_hash",
    "key_hash",
    "credential",
    "secret_value",
    "api_key",
    "private_key",
)

_COMPANIES = "companies"


def _is_secret(column_name: str) -> bool:
    """Return True if a column holds secret material that must not be exported."""
    lowered = column_name.lower()
    return any(pattern in lowered for pattern in SCRUB_PATTERNS)


def _serialize(value: Any) -> Any:
    """Convert a database value into something ``json.dumps`` accepts."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _as_uuid(value: Any) -> uuid.UUID | None:
    """Return ``value`` as a UUID, or None if it is not one."""
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return None
    return None


def _coerce(table: Table, row: dict[str, Any]) -> dict[str, Any]:
    """Convert a serialized row back into database-native values."""
    out: dict[str, Any] = {}
    for name, value in row.items():
        column = table.c.get(name)
        if column is None or value is None:
            out[name] = value
            continue
        kind = type(column.type).__name__
        if kind == "Uuid":
            out[name] = _as_uuid(value) or value
        elif kind == "DateTime" and isinstance(value, str):
            out[name] = datetime.fromisoformat(value)
        else:
            out[name] = value
    return out


class CompanyPortabilityService:
    """Exports a company's full graph to a versioned archive and restores it.

    Example:
        service = CompanyPortabilityService(session)
        archive = await service.export_company(company_id)
        clone_id = await service.import_company(archive, new_name="Acme (copy)")
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # --- export -------------------------------------------------------------

    async def export_company(self, company_id: uuid.UUID) -> dict[str, Any]:
        """Export one company's entire graph as a JSON-serializable archive.

        Walks every tenant-scoped table, then follows foreign keys to pick up
        child rows that carry no ``company_id`` of their own, repeating until
        nothing new is reachable.

        Args:
            company_id: The company to export.

        Returns:
            An archive dict with a ``manifest`` and a ``tables`` map of
            table name to list of row dicts.

        Raises:
            ValueError: If no company with that ID exists.
        """
        md = SQLModel.metadata
        companies = md.tables[_COMPANIES]

        result = await self._db.execute(
            select(companies).where(companies.c.id == company_id)
        )
        company_row = result.mappings().first()
        if company_row is None:
            raise ValueError(f"company {company_id} not found")

        scrubbed: dict[str, int] = {}
        tables: dict[str, list[dict[str, Any]]] = {
            _COMPANIES: [self._row(companies, company_row, scrubbed)]
        }
        known_ids: set[uuid.UUID] = {company_id}

        for table in md.sorted_tables:
            if table.name == _COMPANIES or "company_id" not in table.c:
                continue
            result = await self._db.execute(
                select(table).where(table.c.company_id == company_id)
            )
            rows = [self._row(table, r, scrubbed) for r in result.mappings()]
            if rows:
                tables[table.name] = rows
                known_ids.update(self._ids(rows))

        await self._collect_children(tables, known_ids, scrubbed)

        covered = set(tables) | {
            t.name for t in md.sorted_tables if "company_id" in t.c
        }
        skipped = sorted(
            t.name
            for t in md.sorted_tables
            if t.name not in covered and not self._has_known_fk(t, covered)
        )

        return {
            "manifest": {
                "archive_version": ARCHIVE_VERSION,
                "company_id": str(company_id),
                "company_name": company_row["name"],
                "exported_at": utcnow().isoformat(),
                "row_counts": {name: len(rows) for name, rows in tables.items()},
                "scrubbed": dict(sorted(scrubbed.items())),
                "skipped_tables": skipped,
            },
            "tables": tables,
        }

    async def _collect_children(
        self,
        tables: dict[str, list[dict[str, Any]]],
        known_ids: set[uuid.UUID],
        scrubbed: dict[str, int],
    ) -> None:
        """Pull in rows of un-scoped tables that point at already-exported rows.

        One pass suffices because ``sorted_tables`` is in dependency order, so a
        child table is always visited after the table it references -- including
        a chain of children, each of which adds its own IDs to ``known_ids``
        before the next is read.
        """
        for table in SQLModel.metadata.sorted_tables:
            if table.name == _COMPANIES or "company_id" in table.c:
                continue
            fk_columns = [c for c in table.c if c.foreign_keys]
            if not fk_columns:
                continue
            result = await self._db.execute(select(table))
            rows = [
                self._row(table, r, scrubbed)
                for r in result.mappings()
                if any(r[c.name] in known_ids for c in fk_columns)
            ]
            if rows:
                tables[table.name] = rows
                known_ids.update(self._ids(rows))

    def _row(
        self, table: Table, row: Any, scrubbed: dict[str, int]
    ) -> dict[str, Any]:
        """Serialize one row, dropping secret columns and counting each drop."""
        out: dict[str, Any] = {}
        for column in table.c:
            value = row[column.name]
            if _is_secret(column.name):
                if value is not None:
                    scrubbed[f"{table.name}.{column.name}"] = (
                        scrubbed.get(f"{table.name}.{column.name}", 0) + 1
                    )
                out[column.name] = None if column.nullable else ""
                continue
            out[column.name] = _serialize(value)
        return out

    @staticmethod
    def _ids(rows: list[dict[str, Any]]) -> set[uuid.UUID]:
        """Collect the primary-key UUIDs of serialized rows."""
        found = set()
        for row in rows:
            as_uuid = _as_uuid(row.get("id"))
            if as_uuid is not None:
                found.add(as_uuid)
        return found

    @staticmethod
    def _has_known_fk(table: Table, covered: set[str]) -> bool:
        """Return True if any foreign key on ``table`` targets a covered table."""
        return any(
            fk.column.table.name in covered
            for column in table.c
            for fk in column.foreign_keys
        )

    # --- import -------------------------------------------------------------

    async def import_company(
        self, archive: dict[str, Any], *, new_name: str | None = None
    ) -> uuid.UUID:
        """Restore an archive under freshly minted IDs and return the new company ID.

        Every exported row gets a new UUID and every reference to an exported ID
        is rewritten, so the archive can be imported into the same database it
        came from without colliding with the original rows.

        Args:
            archive: An archive produced by :meth:`export_company`.
            new_name: Optional replacement name for the imported company.

        Returns:
            The ID of the newly created company.

        Raises:
            ValueError: If the archive version is unsupported or the archive
                carries no company row.
        """
        version = archive.get("manifest", {}).get("archive_version")
        if version != ARCHIVE_VERSION:
            raise ValueError(
                f"unsupported archive version {version!r}, expected {ARCHIVE_VERSION}"
            )
        tables: dict[str, list[dict[str, Any]]] = archive.get("tables", {})
        if not tables.get(_COMPANIES):
            raise ValueError("archive contains no company row")

        id_map: dict[uuid.UUID, uuid.UUID] = {}
        for rows in tables.values():
            for row in rows:
                old = _as_uuid(row.get("id"))
                if old is not None and old not in id_map:
                    id_map[old] = uuid.uuid4()

        old_company_id = _as_uuid(tables[_COMPANIES][0]["id"])
        assert old_company_id is not None  # every row is keyed by a UUID id
        new_company_id = id_map[old_company_id]

        md = SQLModel.metadata
        for table in md.sorted_tables:
            rows = tables.get(table.name)
            if not rows:
                continue
            remapped = [_coerce(table, self._remap(row, id_map)) for row in rows]
            if table.name == _COMPANIES and new_name is not None:
                remapped[0]["name"] = new_name
            await self._db.execute(insert(table), remapped)

        await self._db.commit()
        return new_company_id

    @staticmethod
    def _remap(
        row: dict[str, Any], id_map: dict[uuid.UUID, uuid.UUID]
    ) -> dict[str, Any]:
        """Rewrite every value in ``row`` that is a known exported ID.

        Keyed on the value rather than on the column, so plain UUID columns that
        carry no database-level foreign key (``departments.head_agent_id``,
        ``budget_policies.scope_id``) are remapped too. UUIDs are unique, so a
        value match is a reference match.
        """
        out: dict[str, Any] = {}
        for name, value in row.items():
            as_uuid = _as_uuid(value)
            out[name] = str(id_map[as_uuid]) if as_uuid in id_map else value
        return out


def dump_archive(archive: dict[str, Any]) -> str:
    """Serialize an archive to JSON text."""
    return json.dumps(archive, indent=2)


def load_archive(text: str) -> dict[str, Any]:
    """Parse archive JSON text."""
    return json.loads(text)
