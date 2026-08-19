"""Tests for hive_protocol module - FIPA-lite message schema."""

from datetime import datetime, timezone

from nexus.communication.hive_protocol import (
    HOP_CAP,
    REPLY_OBLIGATING_ACTS,
    AgentStatus,
    HiveAgentMeta,
    HiveMessage,
    MessageAct,
    requires_reply_for_act,
)


class TestHiveMessage:
    """Tests for HiveMessage model."""

    def test_hive_message_defaults(self) -> None:
        """HiveMessage should generate id, set hops=0, requires_reply=False, and created_at."""
        msg = HiveMessage(
            conversation="conv-1",
            from_agent="agent-a",
            to_agent="agent-b",
            act=MessageAct.INFORM,
            subject="test",
            body="hello",
        )
        assert msg.id is not None
        assert len(msg.id) == 24  # token_hex(12) produces 24 char string
        assert msg.hops == 0
        assert msg.requires_reply is False
        assert msg.needs_human is False
        assert msg.in_reply_to is None
        assert isinstance(msg.created_at, datetime)
        assert msg.created_at.tzinfo is not None

    def test_hive_message_custom_fields(self) -> None:
        """All HiveMessage fields should be settable."""
        msg = HiveMessage(
            id="custom-id",
            conversation="conv-2",
            in_reply_to="prev-msg",
            from_agent="agent-x",
            to_agent="broadcast",
            act=MessageAct.REQUEST,
            subject="help",
            body="need assistance",
            hops=5,
            requires_reply=True,
            needs_human=True,
        )
        assert msg.id == "custom-id"
        assert msg.conversation == "conv-2"
        assert msg.in_reply_to == "prev-msg"
        assert msg.from_agent == "agent-x"
        assert msg.to_agent == "broadcast"
        assert msg.act == MessageAct.REQUEST
        assert msg.subject == "help"
        assert msg.body == "need assistance"
        assert msg.hops == 5
        assert msg.requires_reply is True
        assert msg.needs_human is True


class TestMessageAct:
    """Tests for MessageAct enum."""

    def test_message_act_values(self) -> None:
        """All 7 acts should have correct string values."""
        assert MessageAct.REQUEST == "request"
        assert MessageAct.INFORM == "inform"
        assert MessageAct.PROPOSE == "propose"
        assert MessageAct.QUERY == "query"
        assert MessageAct.AGREE == "agree"
        assert MessageAct.REFUSE == "refuse"
        assert MessageAct.DONE == "done"
        assert len(MessageAct) == 7


class TestRequiresReply:
    """Tests for requires_reply_for_act helper."""

    def test_requires_reply_for_act(self) -> None:
        """Only REQUEST, QUERY, PROPOSE should obligate a reply."""
        assert requires_reply_for_act(MessageAct.REQUEST) is True
        assert requires_reply_for_act(MessageAct.QUERY) is True
        assert requires_reply_for_act(MessageAct.PROPOSE) is True
        assert requires_reply_for_act(MessageAct.INFORM) is False
        assert requires_reply_for_act(MessageAct.AGREE) is False
        assert requires_reply_for_act(MessageAct.REFUSE) is False
        assert requires_reply_for_act(MessageAct.DONE) is False


class TestHiveAgentMeta:
    """Tests for HiveAgentMeta model."""

    def test_hive_agent_meta_defaults(self) -> None:
        """HiveAgentMeta should have correct defaults."""
        meta = HiveAgentMeta(id="agent-1", name="TestAgent")
        assert meta.id == "agent-1"
        assert meta.name == "TestAgent"
        assert meta.provider is None
        assert meta.role is None
        assert meta.capabilities == []
        assert meta.cwd == ""
        assert meta.is_god is False
        assert meta.status == AgentStatus.IDLE
        assert meta.last_seen == 0.0
        assert meta.archived is False


class TestConstants:
    """Tests for module-level constants."""

    def test_hop_cap_constant(self) -> None:
        """HOP_CAP should be 12."""
        assert HOP_CAP == 12

    def test_reply_obligating_acts(self) -> None:
        """REPLY_OBLIGATING_ACTS should contain exactly request, query, propose."""
        assert REPLY_OBLIGATING_ACTS == frozenset(["request", "query", "propose"])
