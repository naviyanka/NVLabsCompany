"""Webhook Handler - manages webhook registrations and routes incoming payloads to triggers."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class WebhookRegistration:
    """A registered webhook endpoint mapped to a trigger.

    Attributes:
        id: Unique registration identifier.
        trigger_id: The trigger to fire when this webhook receives data.
        path: The URL path this webhook listens on.
        company_id: Company scope.
        secret: Optional secret for payload verification.
        is_active: Whether the webhook is currently active.
        created_at: When the webhook was registered.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    trigger_id: uuid.UUID = field(default_factory=uuid.uuid4)
    path: str = ""
    company_id: uuid.UUID | None = None
    secret: str | None = None
    is_active: bool = True
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class WebhookEvent:
    """An incoming webhook event to be processed.

    Attributes:
        id: Unique event identifier.
        path: The path the request arrived on.
        payload: The request body/data.
        headers: HTTP headers from the request.
        trigger_id: The trigger that was matched and fired.
        received_at: When the event was received.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    path: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    trigger_id: uuid.UUID | None = None
    received_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class WebhookHandler:
    """Manages webhook registration and routes incoming payloads to matching triggers.

    Webhooks are registered against URL paths and linked to triggers.
    When an incoming request matches a registered path, the corresponding
    trigger is fired.
    """

    def __init__(self) -> None:
        """Initialize the webhook handler."""
        self._registrations: dict[uuid.UUID, WebhookRegistration] = {}
        self._path_index: dict[str, uuid.UUID] = {}
        self._event_log: list[WebhookEvent] = []

    def register_webhook(
        self,
        trigger_id: uuid.UUID,
        path: str,
        company_id: uuid.UUID | None = None,
        secret: str | None = None,
    ) -> WebhookRegistration:
        """Register a new webhook endpoint.

        Args:
            trigger_id: The trigger to fire when this path receives data.
            path: URL path to listen on (e.g., /webhooks/my-trigger).
            company_id: Company scope.
            secret: Optional secret for signature verification.

        Returns:
            The created WebhookRegistration.

        Raises:
            ValueError: If the path is already registered.
        """
        normalized_path = path.strip("/")
        if normalized_path in self._path_index:
            raise ValueError(f"Path '{normalized_path}' is already registered")

        registration = WebhookRegistration(
            trigger_id=trigger_id,
            path=normalized_path,
            company_id=company_id,
            secret=secret,
        )
        self._registrations[registration.id] = registration
        self._path_index[normalized_path] = registration.id
        return registration

    def unregister_webhook(self, registration_id: uuid.UUID) -> bool:
        """Remove a webhook registration.

        Args:
            registration_id: The registration to remove.

        Returns:
            True if removed, False if not found.
        """
        registration = self._registrations.get(registration_id)
        if not registration:
            return False

        normalized_path = registration.path.strip("/")
        self._path_index.pop(normalized_path, None)
        del self._registrations[registration_id]
        return True

    async def handle_incoming(
        self,
        path: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> WebhookEvent | None:
        """Handle an incoming webhook request.

        Matches the path to a registered webhook and creates a
        webhook event for the matching trigger.

        Args:
            path: The URL path of the incoming request.
            payload: The request body.
            headers: HTTP headers from the request.

        Returns:
            A WebhookEvent if a matching registration was found, None otherwise.
        """
        normalized_path = path.strip("/")
        registration_id = self._path_index.get(normalized_path)

        if not registration_id:
            return None

        registration = self._registrations.get(registration_id)
        if not registration or not registration.is_active:
            return None

        # Create the event
        event = WebhookEvent(
            path=normalized_path,
            payload=payload,
            headers=headers or {},
            trigger_id=registration.trigger_id,
        )
        self._event_log.append(event)

        return event

    def list_webhooks(
        self,
        company_id: uuid.UUID | None = None,
        active_only: bool = True,
    ) -> list[WebhookRegistration]:
        """List webhook registrations with optional filters.

        Args:
            company_id: Filter by company. None means all.
            active_only: Whether to only return active webhooks.

        Returns:
            List of matching WebhookRegistration objects.
        """
        results: list[WebhookRegistration] = []
        for reg in self._registrations.values():
            if active_only and not reg.is_active:
                continue
            if company_id and reg.company_id != company_id:
                continue
            results.append(reg)
        return results

    def get_event_log(self, limit: int = 100) -> list[WebhookEvent]:
        """Retrieve recent webhook events.

        Args:
            limit: Maximum events to return.

        Returns:
            List of WebhookEvent objects.
        """
        return self._event_log[-limit:]
