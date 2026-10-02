"""Streaming semantics of the governed loop, with no database and no network.

Tool-free call: text is final on arrival, so each delta is released as it arrives.
Tool-capable round: text is provisional (a later native tool_call discards it), so it is
held until the round ends and released only if the round made no tool call.
"""

import uuid
from types import SimpleNamespace

import pytest

from nexus.adapters import governed_loop as gl

SECRET_ARGS = '{"path": "SECRET-ARGUMENT-VALUE"}'
TOOL = {"name": "read_note", "description": "d", "inputSchema": {"type": "object"}}
USAGE = {"prompt_tokens": 7, "completion_tokens": 3}


def text(piece):
    return {"choices": [{"index": 0, "delta": {"content": piece}}]}


def part(index, call_id=None, name=None, arguments=None):
    fn = {k: v for k, v in (("name", name), ("arguments", arguments)) if v is not None}
    return {
        "choices": [
            {"index": 0, "delta": {"tool_calls": [{"index": index, "id": call_id, "function": fn}]}}
        ]
    }


def finish(reason, usage=None):
    chunk = {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}
    return {**chunk, "usage": usage} if usage else chunk


class Server:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"content": [{"text": "ok"}], "isError": False}


class Meter:
    """Records every begin/end; a round is settled exactly when ``end`` ran for its hold."""

    def __init__(self):
        self.begun, self.ended = 0, []

    async def begin(self, messages, tools):
        self.begun += 1
        return self.begun

    async def end(self, hold, usage, started, output_chars):
        self.ended.append((hold, usage, started, output_chars))


@pytest.fixture(autouse=True)
def bridge(monkeypatch):
    async def bind(company_id, agent_id, task_id):
        return None

    monkeypatch.setattr("nexus.tools.manager_bridge.bind", bind)


def drive(rounds, *, tools, log=None, cancelled=None, on_event=None):
    """Run the loop over scripted rounds; returns (outcome, events, meter, server)."""
    server, meter, events = Server(), Meter(), []
    prepared = gl.Prepared(
        SimpleNamespace(company_id=uuid.uuid4(), agent_id=uuid.uuid4()),
        server,
        [TOOL] if tools else [],
    )
    script = iter(rounds)
    log = log if log is not None else []

    def transport(messages, offered):
        chunks = next(script)

        async def stream():
            for chunk in chunks:
                log.append(f"yield:{chunk['choices'][0]['delta'].get('content', '')}")
                yield chunk
            log.append("end")

        return stream()

    def record(event):
        events.append(event)
        if on_event is not None:
            on_event(event)

    async def go():
        return await gl.run(
            prepared,
            uuid.uuid4(),
            [{"role": "user", "content": "hi"}],
            transport,
            gl.Limits("T"),
            meter=meter,
            on_event=record,
            cancelled=cancelled,
        )

    return go, events, meter, server


def deltas(events):
    return [e.text for e in events if e.type == gl.TEXT_DELTA]


class TestToolFreeCall:
    async def test_the_first_delta_arrives_before_the_stream_completes(self):
        log = []
        go, events, _, _ = drive(
            [[text("Hel"), text("lo"), finish("stop")]],
            tools=False,
            log=log,
            on_event=lambda e: log.append(f"delta:{e.text}") if e.type == gl.TEXT_DELTA else None,
        )
        result = await go()
        assert result.text == "Hello" and deltas(events) == ["Hel", "lo"]
        # each delta is released before the transport is asked for the next chunk
        assert log == ["yield:Hel", "delta:Hel", "yield:lo", "delta:lo", "yield:", "end"]

    async def test_cancellation_stops_later_deltas(self):
        flag = []
        go, events, meter, _ = drive(
            [[text("a"), text("b"), text("c"), finish("stop")]],
            tools=False,
            cancelled=lambda: bool(flag),
            on_event=lambda e: flag.append(1) if e.type == gl.TEXT_DELTA else None,
        )
        with pytest.raises(gl.ProviderError, match="T_CANCELLED"):
            await go()
        assert deltas(events) == ["a"] and events[-1].type == gl.CANCELLED
        assert len(meter.ended) == meter.begun == 1  # settled, not left open

    async def test_tool_looking_text_is_stopped_before_the_completing_delta_is_released(self):
        go, events, meter, _ = drive(
            [[text("see <tool_"), text("call>x"), finish("stop")]], tools=False
        )
        with pytest.raises(gl.ProviderError, match="T_TOOL_TEXT"):
            await go()
        assert deltas(events) == ["see <tool_"] and events[-1].error == "T_TOOL_TEXT"
        assert len(meter.ended) == 1

    async def test_a_native_tool_call_is_refused_and_its_arguments_never_appear(self):
        rounds = [[text("hi"), part(0, "c1", "read_note", SECRET_ARGS), finish("tool_calls")]]
        go, events, meter, server = drive(rounds, tools=False)
        with pytest.raises(gl.ProviderError, match="T_BAD_TOOL_CALL"):
            await go()
        assert server.calls == [] and "SECRET-ARGUMENT-VALUE" not in repr(events)
        assert len(meter.ended) == 1


class TestToolCapableRound:
    async def test_text_followed_by_a_tool_call_emits_no_safe_text(self):
        rounds = [
            [text("let me check"), part(0, "c1", "read_note", SECRET_ARGS), finish("tool_calls")],
            [text("all"), text(" quiet"), finish("stop")],
        ]
        go, events, _, server = drive(rounds, tools=True)
        result = await go()
        assert server.calls == [("read_note", {"path": "SECRET-ARGUMENT-VALUE"})]
        assert deltas(events) == ["all", " quiet"] and result.text == "all quiet"
        assert "let me check" not in repr(events)  # the discarded round's text is never released

    async def test_a_round_that_ends_without_a_tool_call_releases_only_its_final_text_at_the_end(
        self,
    ):
        log = []
        go, events, _, _ = drive(
            [[text("fi"), text("nal"), finish("stop")]],
            tools=True,
            log=log,
            on_event=lambda e: log.append(f"delta:{e.text}") if e.type == gl.TEXT_DELTA else None,
        )
        result = await go()
        assert result.text == "final" and deltas(events) == ["fi", "nal"]
        # buffered release: nothing leaves until the stream has ended; not token streaming
        assert log.index("end") < log.index("delta:fi")

    async def test_mixed_text_and_tool_fragments_never_leak(self):
        rounds = [
            [
                text("a"),
                part(0, "c1", "read_note", '{"path": "SECRET-'),
                text("b"),
                part(0, None, None, 'ARGUMENT-VALUE"}'),
                text("c"),
                finish("tool_calls"),
            ],
            [text("done"), finish("stop")],
        ]
        go, events, _, server = drive(rounds, tools=True)
        await go()
        assert deltas(events) == ["done"]
        assert all("SECRET-ARGUMENT" not in repr(e) for e in events)
        assert server.calls == [("read_note", {"path": "SECRET-ARGUMENT-VALUE"})]

    async def test_tool_looking_text_releases_nothing(self):
        go, events, _, _ = drive([[text('{"tool_calls": []}'), finish("stop")]], tools=True)
        with pytest.raises(gl.ProviderError, match="T_TOOL_TEXT"):
            await go()
        assert deltas(events) == []


@pytest.mark.parametrize("tools", [False, True])
class TestBudgetAndCallbacks:
    async def test_a_failing_callback_still_settles_every_round(self, tools):
        def boom(event):
            raise RuntimeError("consumer bug")

        rounds = [[text("x"), finish("stop", USAGE)]]
        go, _, meter, _ = drive(rounds, tools=tools, on_event=boom)
        result = await go()  # the callback is dropped; the turn still completes
        assert result.text == "x"
        assert meter.begun == 1 and meter.ended == [(1, USAGE, True, 1)]

    async def test_usage_is_settled_and_reported_the_same_in_both_modes(self, tools):
        rounds = [[text("ab"), text("c"), finish("stop", USAGE)]]
        go, events, meter, _ = drive(rounds, tools=tools)
        result = await go()
        assert (
            result.usage == USAGE and events[-1].type == gl.COMPLETED and events[-1].usage == USAGE
        )
        assert meter.ended == [(1, USAGE, True, 3)]

    async def test_a_failed_round_is_settled_once(self, tools):
        second_choice = {"choices": [{"index": 1, "delta": {}}]}  # a malformed response mid-stream
        go, _, meter, _ = drive([[text("x"), second_choice]], tools=tools)
        with pytest.raises(gl.ProviderError):
            await go()
        assert meter.begun == 1 and len(meter.ended) == 1 and meter.ended[0][2] is True
