"""Tests for A2A Router - structured communication modes."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nexus.communication.a2a_router import A2AMessage, A2ARouter, CommunicationMode
from nexus.runtime.cycle_guard import CycleGuard, CycleGuardError


def _make_message(
    sender: uuid.UUID | None = None,
    recipient: uuid.UUID | None = None,
    mode: CommunicationMode = CommunicationMode.notify,
    payload: dict | None = None,
    correlation_id: str | None = None,
    timeout_seconds: float | None = None,
    created_at: datetime | None = None,
) -> A2AMessage:
    """Helper to create A2AMessage instances for testing."""
    msg = A2AMessage(
        id=uuid.uuid4(),
        sender=sender or uuid.uuid4(),
        recipient=recipient or uuid.uuid4(),
        mode=mode,
        payload=payload or {"task": "test"},
        correlation_id=correlation_id or str(uuid.uuid4()),
        timeout_seconds=timeout_seconds,
    )
    if created_at is not None:
        msg.created_at = created_at
    return msg


class TestCommunicationMode:
    """Tests for CommunicationMode enum."""

    def test_notify_value(self) -> None:
        assert CommunicationMode.notify.value == "notify"

    def test_consult_value(self) -> None:
        assert CommunicationMode.consult.value == "consult"

    def test_delegate_value(self) -> None:
        assert CommunicationMode.delegate.value == "delegate"

    def test_all_modes_exist(self) -> None:
        modes = [m.value for m in CommunicationMode]
        assert sorted(modes) == ["consult", "delegate", "notify"]


class TestA2AMessage:
    """Tests for A2AMessage dataclass."""

    def test_message_creation(self) -> None:
        msg_id = uuid.uuid4()
        sender = uuid.uuid4()
        recipient = uuid.uuid4()
        msg = A2AMessage(
            id=msg_id,
            sender=sender,
            recipient=recipient,
            mode=CommunicationMode.notify,
            payload={"key": "value"},
            correlation_id="corr-123",
        )
        assert msg.id == msg_id
        assert msg.sender == sender
        assert msg.recipient == recipient
        assert msg.mode == CommunicationMode.notify
        assert msg.payload == {"key": "value"}
        assert msg.correlation_id == "corr-123"
        assert msg.timeout_seconds is None
        assert msg.response is None
        assert msg.response_received_at is None
        assert msg.status == "pending"

    def test_message_with_timeout(self) -> None:
        msg = _make_message(timeout_seconds=30.0)
        assert msg.timeout_seconds == 30.0

    def test_message_default_status(self) -> None:
        msg = _make_message()
        assert msg.status == "pending"

    def test_message_created_at_auto(self) -> None:
        before = datetime.now(timezone.utc)
        msg = _make_message()
        after = datetime.now(timezone.utc)
        assert before <= msg.created_at <= after


class TestA2ARouterNotifyMode:
    """Tests for notify mode: fire-and-forget delivery."""

    def test_notify_delivers_immediately(self) -> None:
        router = A2ARouter()
        msg = _make_message(mode=CommunicationMode.notify)
        result = router.send(msg)
        assert result.status == "delivered"

    def test_notify_no_response_tracking(self) -> None:
        router = A2ARouter()
        sender = uuid.uuid4()
        recipient = uuid.uuid4()
        msg = _make_message(
            sender=sender,
            recipient=recipient,
            mode=CommunicationMode.notify,
        )
        router.send(msg)
        # No pending consults should exist for notify messages
        assert router.get_pending_consults(recipient) == []

    def test_notify_multiple_messages(self) -> None:
        router = A2ARouter()
        for _ in range(5):
            msg = _make_message(mode=CommunicationMode.notify)
            result = router.send(msg)
            assert result.status == "delivered"


class TestA2ARouterConsultMode:
    """Tests for consult mode: request-response with tracking."""

    def test_consult_message_pending(self) -> None:
        router = A2ARouter()
        msg = _make_message(mode=CommunicationMode.consult)
        result = router.send(msg)
        assert result.status == "pending"

    def test_consult_respond_resolves(self) -> None:
        router = A2ARouter()
        msg = _make_message(mode=CommunicationMode.consult, correlation_id="corr-001")
        router.send(msg)

        response_payload = {"answer": "42"}
        resolved = router.respond("corr-001", response_payload)

        assert resolved is not None
        assert resolved.status == "responded"
        assert resolved.response == {"answer": "42"}
        assert resolved.response_received_at is not None

    def test_consult_respond_nonexistent_returns_none(self) -> None:
        router = A2ARouter()
        result = router.respond("nonexistent-id", {"data": "test"})
        assert result is None

    def test_consult_pending_until_response(self) -> None:
        router = A2ARouter()
        recipient = uuid.uuid4()
        msg = _make_message(
            recipient=recipient,
            mode=CommunicationMode.consult,
            correlation_id="corr-002",
        )
        router.send(msg)

        pending = router.get_pending_consults(recipient)
        assert len(pending) == 1
        assert pending[0].correlation_id == "corr-002"

    def test_consult_removed_after_response(self) -> None:
        router = A2ARouter()
        recipient = uuid.uuid4()
        msg = _make_message(
            recipient=recipient,
            mode=CommunicationMode.consult,
            correlation_id="corr-003",
        )
        router.send(msg)
        router.respond("corr-003", {"done": True})

        pending = router.get_pending_consults(recipient)
        assert len(pending) == 0


class TestA2ARouterConsultTimeout:
    """Tests for consult mode timeout behavior."""

    def test_timeout_marks_expired_messages(self) -> None:
        router = A2ARouter()
        # Create a message with a very short timeout that has already expired
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        msg = _make_message(
            mode=CommunicationMode.consult,
            timeout_seconds=5.0,
            created_at=past,
            correlation_id="timeout-001",
        )
        router.send(msg)

        timed_out = router.check_timeouts()
        assert len(timed_out) == 1
        assert timed_out[0].status == "timed_out"
        assert timed_out[0].correlation_id == "timeout-001"

    def test_timeout_does_not_affect_non_expired(self) -> None:
        router = A2ARouter()
        msg = _make_message(
            mode=CommunicationMode.consult,
            timeout_seconds=9999.0,
            correlation_id="not-expired",
        )
        router.send(msg)

        timed_out = router.check_timeouts()
        assert len(timed_out) == 0

    def test_timeout_removes_from_pending(self) -> None:
        router = A2ARouter()
        recipient = uuid.uuid4()
        past = datetime.now(timezone.utc) - timedelta(seconds=20)
        msg = _make_message(
            recipient=recipient,
            mode=CommunicationMode.consult,
            timeout_seconds=5.0,
            created_at=past,
            correlation_id="timeout-002",
        )
        router.send(msg)

        router.check_timeouts()
        pending = router.get_pending_consults(recipient)
        assert len(pending) == 0

    def test_timeout_no_timeout_seconds_not_expired(self) -> None:
        router = A2ARouter()
        # Message without timeout_seconds should never time out
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        msg = _make_message(
            mode=CommunicationMode.consult,
            timeout_seconds=None,
            created_at=past,
            correlation_id="no-timeout",
        )
        router.send(msg)

        timed_out = router.check_timeouts()
        assert len(timed_out) == 0


class TestA2ARouterDelegateMode:
    """Tests for delegate mode with CycleGuard integration."""

    def test_delegate_works_without_cycle_guard(self) -> None:
        router = A2ARouter()
        msg = _make_message(mode=CommunicationMode.delegate)
        result = router.send(msg)
        assert result.status == "delivered"

    def test_delegate_allowed_by_cycle_guard(self) -> None:
        cycle_guard = CycleGuard()
        router = A2ARouter(cycle_guard=cycle_guard)
        sender = uuid.uuid4()
        recipient = uuid.uuid4()
        msg = _make_message(
            sender=sender,
            recipient=recipient,
            mode=CommunicationMode.delegate,
        )
        result = router.send(msg)
        assert result.status == "delivered"

    def test_delegate_raises_cycle_guard_error_on_loop(self) -> None:
        cycle_guard = CycleGuard(max_cycle_count=2)
        router = A2ARouter(cycle_guard=cycle_guard)
        sender = uuid.uuid4()
        recipient = uuid.uuid4()

        # First two delegations should succeed (max_cycle_count=2)
        for _ in range(2):
            msg = _make_message(
                sender=sender,
                recipient=recipient,
                mode=CommunicationMode.delegate,
            )
            router.send(msg)

        # Third should raise CycleGuardError
        msg = _make_message(
            sender=sender,
            recipient=recipient,
            mode=CommunicationMode.delegate,
        )
        with pytest.raises(CycleGuardError):
            router.send(msg)

    def test_delegate_tracks_execution_chain(self) -> None:
        cycle_guard = CycleGuard()
        router = A2ARouter(cycle_guard=cycle_guard)
        sender = uuid.uuid4()
        recipient = uuid.uuid4()
        msg = _make_message(
            sender=sender,
            recipient=recipient,
            mode=CommunicationMode.delegate,
        )
        router.send(msg)

        chain = router.get_execution_chain()
        assert len(chain) == 1
        assert chain[0] == (sender, recipient)

    def test_delegate_multiple_delegations_build_chain(self) -> None:
        cycle_guard = CycleGuard()
        router = A2ARouter(cycle_guard=cycle_guard)

        agents = [uuid.uuid4() for _ in range(4)]
        for i in range(3):
            msg = _make_message(
                sender=agents[i],
                recipient=agents[i + 1],
                mode=CommunicationMode.delegate,
            )
            router.send(msg)

        chain = router.get_execution_chain()
        assert len(chain) == 3
        assert chain[0] == (agents[0], agents[1])
        assert chain[1] == (agents[1], agents[2])
        assert chain[2] == (agents[2], agents[3])


class TestA2ARouterPermissions:
    """Tests for permission checks."""

    def test_no_permissions_allows_all(self) -> None:
        router = A2ARouter()
        sender = uuid.uuid4()
        recipient = uuid.uuid4()
        assert router.check_permission(sender, recipient, CommunicationMode.notify) is True
        assert router.check_permission(sender, recipient, CommunicationMode.consult) is True
        assert router.check_permission(sender, recipient, CommunicationMode.delegate) is True

    def test_permission_denied_when_not_registered(self) -> None:
        router = A2ARouter()
        sender = uuid.uuid4()
        recipient = uuid.uuid4()
        other_sender = uuid.uuid4()
        # Register permission for one pair
        router.register_permission(other_sender, recipient, [CommunicationMode.notify])
        # Now the unregistered pair should be denied
        assert router.check_permission(sender, recipient, CommunicationMode.notify) is False

    def test_permission_allowed_when_registered(self) -> None:
        router = A2ARouter()
        sender = uuid.uuid4()
        recipient = uuid.uuid4()
        router.register_permission(sender, recipient, [CommunicationMode.notify])
        assert router.check_permission(sender, recipient, CommunicationMode.notify) is True

    def test_permission_denied_for_wrong_mode(self) -> None:
        router = A2ARouter()
        sender = uuid.uuid4()
        recipient = uuid.uuid4()
        router.register_permission(sender, recipient, [CommunicationMode.notify])
        assert router.check_permission(sender, recipient, CommunicationMode.consult) is False

    def test_permission_multiple_modes(self) -> None:
        router = A2ARouter()
        sender = uuid.uuid4()
        recipient = uuid.uuid4()
        router.register_permission(
            sender, recipient, [CommunicationMode.notify, CommunicationMode.consult]
        )
        assert router.check_permission(sender, recipient, CommunicationMode.notify) is True
        assert router.check_permission(sender, recipient, CommunicationMode.consult) is True
        assert router.check_permission(sender, recipient, CommunicationMode.delegate) is False

    def test_send_raises_permission_error(self) -> None:
        router = A2ARouter()
        sender = uuid.uuid4()
        recipient = uuid.uuid4()
        other = uuid.uuid4()
        # Register some permission to activate permission checking
        router.register_permission(other, recipient, [CommunicationMode.notify])

        msg = _make_message(sender=sender, recipient=recipient, mode=CommunicationMode.notify)
        with pytest.raises(PermissionError):
            router.send(msg)

    def test_send_with_registered_permission_succeeds(self) -> None:
        router = A2ARouter()
        sender = uuid.uuid4()
        recipient = uuid.uuid4()
        router.register_permission(sender, recipient, [CommunicationMode.notify])
        msg = _make_message(sender=sender, recipient=recipient, mode=CommunicationMode.notify)
        result = router.send(msg)
        assert result.status == "delivered"


class TestA2ARouterCorrelationTracking:
    """Tests for multiple messages with correlation tracking."""

    def test_multiple_consults_tracked_independently(self) -> None:
        router = A2ARouter()
        recipient = uuid.uuid4()

        msg1 = _make_message(
            recipient=recipient,
            mode=CommunicationMode.consult,
            correlation_id="corr-A",
        )
        msg2 = _make_message(
            recipient=recipient,
            mode=CommunicationMode.consult,
            correlation_id="corr-B",
        )
        router.send(msg1)
        router.send(msg2)

        pending = router.get_pending_consults(recipient)
        assert len(pending) == 2

        # Respond to first
        router.respond("corr-A", {"result": "A"})
        pending = router.get_pending_consults(recipient)
        assert len(pending) == 1
        assert pending[0].correlation_id == "corr-B"

    def test_get_pending_consults_filters_by_agent(self) -> None:
        router = A2ARouter()
        agent_a = uuid.uuid4()
        agent_b = uuid.uuid4()

        msg1 = _make_message(
            recipient=agent_a,
            mode=CommunicationMode.consult,
            correlation_id="for-a",
        )
        msg2 = _make_message(
            recipient=agent_b,
            mode=CommunicationMode.consult,
            correlation_id="for-b",
        )
        router.send(msg1)
        router.send(msg2)

        pending_a = router.get_pending_consults(agent_a)
        pending_b = router.get_pending_consults(agent_b)
        assert len(pending_a) == 1
        assert pending_a[0].correlation_id == "for-a"
        assert len(pending_b) == 1
        assert pending_b[0].correlation_id == "for-b"

    def test_correlation_id_unique_resolution(self) -> None:
        router = A2ARouter()
        msg = _make_message(
            mode=CommunicationMode.consult,
            correlation_id="unique-corr",
        )
        router.send(msg)

        # Respond once
        result = router.respond("unique-corr", {"first": True})
        assert result is not None
        assert result.response == {"first": True}

        # Second respond returns None (already resolved)
        result2 = router.respond("unique-corr", {"second": True})
        assert result2 is None


class TestA2ARouterExecutionChain:
    """Tests for get_execution_chain tracking delegations."""

    def test_empty_chain_initially(self) -> None:
        router = A2ARouter()
        assert router.get_execution_chain() == []

    def test_chain_grows_with_delegations(self) -> None:
        router = A2ARouter(cycle_guard=CycleGuard())
        s1, r1 = uuid.uuid4(), uuid.uuid4()
        s2, r2 = uuid.uuid4(), uuid.uuid4()

        router.send(_make_message(sender=s1, recipient=r1, mode=CommunicationMode.delegate))
        router.send(_make_message(sender=s2, recipient=r2, mode=CommunicationMode.delegate))

        chain = router.get_execution_chain()
        assert len(chain) == 2
        assert chain[0] == (s1, r1)
        assert chain[1] == (s2, r2)

    def test_chain_not_affected_by_notify_or_consult(self) -> None:
        router = A2ARouter(cycle_guard=CycleGuard())
        router.send(_make_message(mode=CommunicationMode.notify))
        router.send(_make_message(mode=CommunicationMode.consult))
        assert router.get_execution_chain() == []

    def test_chain_returns_copy(self) -> None:
        router = A2ARouter(cycle_guard=CycleGuard())
        s, r = uuid.uuid4(), uuid.uuid4()
        router.send(_make_message(sender=s, recipient=r, mode=CommunicationMode.delegate))

        chain = router.get_execution_chain()
        chain.append((uuid.uuid4(), uuid.uuid4()))
        # Original should be unaffected
        assert len(router.get_execution_chain()) == 1
