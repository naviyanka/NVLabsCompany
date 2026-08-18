"""Event Bus for pub/sub event handling with async and sync handler support.

Provides a publish/subscribe event system with event persistence, handler
registration (both sync and async), and historical event replay capabilities.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from nexus.models.communication import Event

# Event type constants
TASK_COMPLETED = "task_completed"
AGENT_ERROR = "agent_error"
APPROVAL_NEEDED = "approval_needed"
BUDGET_WARNING = "budget_warning"
AGENT_HIRED = "agent_hired"
MEETING_STARTED = "meeting_started"


class EventBus:
    """Pub/sub event bus supporting both synchronous and asynchronous handlers.

    Provides event publication with fan-out to registered handlers,
    event persistence using the Event model, and historical event replay.

    All operations are scoped by company_id for multi-tenant isolation.

    Attributes:
        db: Optional async database session for event persistence.
    """

    def __init__(self, db: Optional[Any] = None) -> None:
        """Initialize the EventBus.

        Args:
            db: Optional AsyncSession for database persistence.
        """
        self.db = db
        # Handlers registry: event_type -> list of (handler, is_async) tuples
        self._handlers: dict[str, list[tuple[Callable[..., Any], bool]]] = {}
        # Persisted events for replay
        self._events: list[Event] = []

    def subscribe(
        self,
        event_type: str,
        handler: Callable[..., Any],
        is_async: bool = True,
    ) -> None:
        """Register a handler for a specific event type.

        Args:
            event_type: The event type to subscribe to (e.g., TASK_COMPLETED).
            handler: Callable to invoke when the event is published.
                     Async handlers receive (event_type, payload, event) as args.
                     Sync handlers receive (event_type, payload, event) as args.
            is_async: Whether the handler is an async coroutine. Defaults to True.
        """
        self._handlers.setdefault(event_type, []).append((handler, is_async))

    def unsubscribe(
        self,
        event_type: str,
        handler: Callable[..., Any],
    ) -> bool:
        """Remove a handler subscription for a specific event type.

        Args:
            event_type: The event type to unsubscribe from.
            handler: The handler function to remove.

        Returns:
            True if the handler was found and removed, False otherwise.
        """
        handlers = self._handlers.get(event_type, [])
        for i, (h, _) in enumerate(handlers):
            if h is handler:
                handlers.pop(i)
                return True
        return False

    async def publish(
        self,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
        source_agent_id: Optional[uuid.UUID] = None,
        company_id: Optional[uuid.UUID] = None,
    ) -> Event:
        """Publish an event and notify all registered handlers.

        Creates an Event record, persists it if a database session is available,
        and dispatches to all registered handlers. Sync handlers are called
        immediately inline; async handlers are gathered concurrently.

        Args:
            event_type: The type of event being published.
            payload: Optional event data payload.
            source_agent_id: UUID of the agent that triggered the event.
            company_id: Company scope for tenant isolation.

        Returns:
            The created Event object.
        """
        event = Event(
            id=uuid.uuid4(),
            company_id=company_id or uuid.uuid4(),
            event_type=event_type,
            source_agent_id=source_agent_id or uuid.uuid4(),
            payload=payload,
            handled=False,
            created_at=datetime.now(timezone.utc),
        )

        # Store in memory for replay
        self._events.append(event)

        # Persist to DB if available
        if self.db is not None:
            self.db.add(event)
            await self.db.commit()

        # Dispatch to handlers
        handlers = self._handlers.get(event_type, [])
        async_tasks: list[Any] = []

        for handler, is_async in handlers:
            if is_async:
                async_tasks.append(handler(event_type, payload, event))
            else:
                # Sync handlers are called immediately
                handler(event_type, payload, event)

        # Await all async handlers concurrently
        if async_tasks:
            await asyncio.gather(*async_tasks)

        # Mark event as handled
        event.handled = True

        return event

    async def replay(
        self,
        event_type: str,
        since: Optional[datetime] = None,
        company_id: Optional[uuid.UUID] = None,
    ) -> list[Event]:
        """Replay historical events of a specific type.

        Retrieves events from the in-memory store (or database if configured)
        filtered by type and optional time/company constraints. Dispatches
        them to currently registered handlers.

        Args:
            event_type: The event type to replay.
            since: Optional datetime filter; only events after this time are replayed.
            company_id: Optional company filter for tenant isolation.

        Returns:
            List of Event objects that were replayed.
        """
        matching_events: list[Event] = []

        for event in self._events:
            if event.event_type != event_type:
                continue
            if company_id and event.company_id != company_id:
                continue
            if since and event.created_at < since:
                continue
            matching_events.append(event)

        # Dispatch to handlers
        handlers = self._handlers.get(event_type, [])

        for event in matching_events:
            async_tasks: list[Any] = []
            for handler, is_async in handlers:
                if is_async:
                    async_tasks.append(handler(event_type, event.payload, event))
                else:
                    handler(event_type, event.payload, event)
            if async_tasks:
                await asyncio.gather(*async_tasks)

        return matching_events

    def get_events(
        self,
        event_type: Optional[str] = None,
        company_id: Optional[uuid.UUID] = None,
    ) -> list[Event]:
        """Retrieve stored events with optional filtering.

        Args:
            event_type: Optional event type filter.
            company_id: Optional company filter.

        Returns:
            List of matching Event objects.
        """
        results: list[Event] = []
        for event in self._events:
            if event_type and event.event_type != event_type:
                continue
            if company_id and event.company_id != company_id:
                continue
            results.append(event)
        return results

    def handler_count(self, event_type: str) -> int:
        """Get the number of registered handlers for an event type.

        Args:
            event_type: The event type to query.

        Returns:
            Number of registered handlers.
        """
        return len(self._handlers.get(event_type, []))
