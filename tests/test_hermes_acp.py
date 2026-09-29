"""The Hermes ACP transport, against a scripted fake ``hermes acp`` (no model)."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from nexus.adapters.hermes_acp import ACPError, HermesACPTransport, redact, tool_wire_name

FAKE = str(Path(__file__).parent / "fake_hermes_acp.py")
TOKEN = "tok-SECRET-123"
SERVER = {"type": "http", "name": "nexus", "url": "http://127.0.0.1:1/mcp",
          "headers": [{"name": "Authorization", "value": f"Bearer {TOKEN}"}]}
OFFERED = tool_wire_name("nexus", "manager_list_reports")


def alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def transport(tmp_path, scenario, **kw):
    rec = tmp_path / "rec.jsonl"
    env = {**os.environ, "FAKE_ACP_SCENARIO": scenario, "FAKE_ACP_RECORD": str(rec)}
    args = dict(cwd=str(tmp_path), env=env, mcp_servers=[SERVER], allowed_tools=[OFFERED],
                turn_timeout=10, startup_timeout=10, secrets=[TOKEN])
    args.update(kw)
    return HermesACPTransport([sys.executable, FAKE], **args), rec


async def eventually(check, seconds=8):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        await asyncio.sleep(0.1)
    return check()


class TestProtocol:
    async def test_handshake_session_new_and_prompt_in_order(self, tmp_path):
        t, rec = transport(tmp_path, "ok")
        result = await t.run("hi there")
        assert result.text == "hello world" and result.stop_reason == "end_turn"
        seen = records(rec)
        order = [r["method"] for r in seen if r.get("method") not in (None, "session/cancel")]
        assert order == ["initialize", "session/new", "session/prompt"]
        new = next(r for r in seen if r.get("method") == "session/new")
        # The real workspace, and the MCP server only in the session request.
        assert new["cwd"] == str(tmp_path) and new["servers"] == [SERVER]
        assert next(r for r in seen if r.get("method") == "session/prompt")["prompt"] == "hi there"

    async def test_out_of_order_and_unknown_responses_are_ignored(self, tmp_path):
        t, _ = transport(tmp_path, "out_of_order")
        assert (await t.run("x")).text == "hello world"

    async def test_setup_error_is_structured_and_carries_no_remote_text(self, tmp_path):
        t, _ = transport(tmp_path, "setup_error")
        with pytest.raises(ACPError) as err:
            await t.run("x")
        assert err.value.code == "ACP_REQUEST_FAILED" and "SECRET-TEXT" not in str(err.value)

    async def test_free_form_tool_text_is_only_text(self, tmp_path):
        t, _ = transport(tmp_path, "free_form")
        result = await t.run("x")
        assert "<tool_call>" in result.text and result.tool_calls == []

    async def test_client_requests_are_refused(self, tmp_path):
        t, rec = transport(tmp_path, "client_requests")
        await t.run("x")
        reply = next(r["fs_reply"] for r in records(rec) if "fs_reply" in r)
        assert reply["id"] == 60 and reply["error"]["code"] == -32601


class TestBounds:
    async def test_malformed_message_fails_closed(self, tmp_path):
        t, _ = transport(tmp_path, "malformed")
        with pytest.raises(ACPError) as err:
            await t.run("x")
        assert err.value.code == "ACP_PROTOCOL"

    async def test_oversized_frame(self, tmp_path):
        t, _ = transport(tmp_path, "oversized", max_frame=1024)
        with pytest.raises(ACPError) as err:
            await t.run("x")
        assert err.value.code == "ACP_FRAME_TOO_LARGE"

    async def test_output_is_bounded(self, tmp_path):
        t, _ = transport(tmp_path, "big_output", max_output=1000)
        with pytest.raises(ACPError) as err:
            await t.run("x")
        assert err.value.code == "ACP_OUTPUT_LIMIT"

    async def test_child_crash(self, tmp_path):
        t, _ = transport(tmp_path, "crash")
        with pytest.raises(ACPError) as err:
            await t.run("x")
        assert err.value.code == "ACP_CHILD_EXIT"

    async def test_startup_timeout_ends_the_child(self, tmp_path):
        t, rec = transport(tmp_path, "hang_init", startup_timeout=1)
        with pytest.raises(ACPError) as err:
            await t.run("x")
        assert err.value.code == "ACP_TIMEOUT"
        pid = records(rec)[0]["pid"]
        assert await eventually(lambda: not alive(pid))

    async def test_turn_timeout_cancels_then_ends_the_whole_tree(self, tmp_path):
        t, rec = transport(tmp_path, "grandchild", turn_timeout=1)
        with pytest.raises(ACPError) as err:
            await t.run("x")
        assert err.value.code == "ACP_TIMEOUT"
        seen = records(rec)
        assert any(r.get("method") == "session/cancel" for r in seen)  # ACP cancel first
        pids = [seen[0]["pid"], next(r["grandchild"] for r in seen if "grandchild" in r)]
        assert await eventually(lambda: not any(alive(p) for p in pids))

    async def test_task_cancellation_ends_the_child_and_never_replays(self, tmp_path):
        t, rec = transport(tmp_path, "hang_prompt", turn_timeout=60)
        task = asyncio.create_task(t.run("x"))
        assert await eventually(lambda: any(r.get("method") == "session/prompt" for r in records(rec)))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await eventually(lambda: not alive(records(rec)[0]["pid"]))
        assert [r.get("method") for r in records(rec)].count("session/prompt") == 1


class TestPermissions:
    async def test_only_the_offered_nexus_tool_is_allowed(self, tmp_path):
        t, rec = transport(tmp_path, "permissions")
        result = await t.run("x")
        replies = [r["permission_reply"] for r in records(rec) if "permission_reply" in r]
        assert replies[0] == {"outcome": "selected", "optionId": "allow_once"}
        assert all(r == {"outcome": "selected", "optionId": "deny"} for r in replies[1:])
        assert [p["decision"] for p in result.permissions] == ["allow"] + ["deny"] * 4
        # Safe metadata only: no titles, commands or paths.
        assert "rm -rf" not in json.dumps(result.permissions) and "passwd" not in json.dumps(
            result.permissions)

    async def test_offered_tool_call_is_recorded_and_others_end_the_turn(self, tmp_path):
        ok, _ = transport(tmp_path, "tool_ok")
        assert (await ok.run("x")).tool_calls == [OFFERED]
        bad, _ = transport(tmp_path, "tool_bad")
        with pytest.raises(ACPError) as err:
            await bad.run("x")
        assert err.value.code == "ACP_POLICY_VIOLATION" and "terminal" not in str(err.value)
        assert bad.result.tool_calls == ["[denied]"]


class TestRedaction:
    def test_redact_removes_the_secret(self):
        assert redact(f"Authorization: Bearer {TOKEN}", [TOKEN]) == (
            "Authorization: Bearer [REDACTED]")

    async def test_stderr_tail_is_redacted_and_nothing_persists(self, tmp_path):
        t, _ = transport(tmp_path, "ok")
        await t.run("x")
        t._stderr_tail = f"boom {TOKEN}".encode()
        assert TOKEN not in t.stderr_tail
        # No credential file is written anywhere in the workspace.
        assert not [p for p in tmp_path.iterdir() if p.name != "rec.jsonl"]
