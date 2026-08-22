"""Timestamp helper shared by the table definitions.

Every ``datetime`` column in this package maps to a naive ``TIMESTAMP``
(no model declares ``timezone=True``), and asyncpg rejects a timezone-aware
value for such a column outright::

    asyncpg.exceptions.DataError: invalid input for query argument $2

Comparing an aware value against a naive one loaded from the database raises
``TypeError`` as well, which is why session-expiry and token-expiry checks must
use the same clock as the column defaults.

:func:`utcnow` therefore returns naive UTC, matching the existing columns
without calling the deprecated ``datetime`` class method of the same name.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime."""
    return datetime.now(UTC).replace(tzinfo=None)
