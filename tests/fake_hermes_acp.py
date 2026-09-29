"""A scripted stand-in for ``hermes acp``: JSON-RPC over stdio, no model.

``FAKE_ACP_SCENARIO`` picks the behaviour; ``FAKE_ACP_RECORD`` is a JSON-lines
file the fake appends what it received to (never the bearer header value).
"""

import json
import os
import subprocess
import sys
import time

SCENARIO = os.environ.get("FAKE_ACP_SCENARIO", "ok")
RECORD = os.environ.get("FAKE_ACP_RECORD")
TOOL = os.environ.get("FAKE_ACP_TOOL", "mcp__nexus__manager_list_reports")


def record(**kw):
    if RECORD:
        with open(RECORD, "a", encoding="utf-8") as f:
            f.write(json.dumps(kw) + "\n")


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def chunk(text):
    send(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "s1",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": text},
                },
            },
        }
    )


def tool_call(title):
    send(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "s1",
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "tc1",
                    "title": title,
                    "kind": "other",
                },
            },
        }
    )


def read():
    line = sys.stdin.readline()
    return json.loads(line) if line else None


def ask_permission(rid, title, kind):
    send(
        {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "session/request_permission",
            "params": {
                "sessionId": "s1",
                "toolCall": {"toolCallId": "tc1", "title": title, "kind": kind},
                "options": [
                    {"optionId": "allow_once", "kind": "allow_once", "name": "Allow"},
                    {"optionId": "deny", "kind": "reject_once", "name": "Deny"},
                ],
            },
        }
    )
    while (reply := read()) is not None:
        if reply.get("id") == rid:
            record(permission_reply=reply["result"]["outcome"])
            return


record(pid=os.getpid())
if SCENARIO == "hang_init":
    time.sleep(600)
if SCENARIO == "grandchild":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    record(grandchild=child.pid)

SEEN_HEADER = ""
while (msg := read()) is not None:
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        if SCENARIO == "crash":
            sys.exit(3)
        if SCENARIO == "malformed":
            sys.stdout.write("this is not json\n")
            sys.stdout.flush()
            continue
        if SCENARIO == "oversized":
            sys.stdout.write("x" * 5000 + "\n")
            sys.stdout.flush()
            continue
        if SCENARIO == "out_of_order":
            send({"jsonrpc": "2.0", "id": 999, "result": {"stray": True}})
        send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": 1}})
        record(method=method)
    elif method == "session/new":
        params = msg["params"]
        record(method=method, cwd=params["cwd"], servers=params["mcpServers"])
        if params["mcpServers"]:
            SEEN_HEADER = params["mcpServers"][0]["headers"][0]["value"]
        if SCENARIO == "setup_error":
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32000, "message": "SECRET-TEXT"}})
        else:
            send({"jsonrpc": "2.0", "id": mid, "result": {"sessionId": "s1"}})
    elif method == "session/prompt":
        record(method=method, prompt=msg["params"]["prompt"][0]["text"])
        if SCENARIO in ("hang_prompt", "grandchild"):
            continue  # waits for session/cancel or a kill
        if SCENARIO == "free_form":
            chunk('<tool_call>{"name": "manager_delegate_task"}</tool_call>')
        elif SCENARIO == "tool_ok":
            tool_call(TOOL)
            chunk("done")
        elif SCENARIO == "tool_bad":
            tool_call("terminal: ls")
            chunk("should never be read")
        elif SCENARIO == "permissions":
            ask_permission(50, TOOL, "other")
            ask_permission(51, "terminal: rm -rf x", "execute")
            ask_permission(52, "read: /etc/passwd", "read")
            ask_permission(53, "browser_navigate", "fetch")
            ask_permission(54, "something new", "teleport")
            chunk("ok")
        elif SCENARIO == "client_requests":
            send(
                {"jsonrpc": "2.0", "id": 60, "method": "fs/read_text_file", "params": {"path": "x"}}
            )
            reply = read()
            record(fs_reply=reply)
            chunk("ok")
        elif SCENARIO == "big_output":
            for _ in range(50):
                chunk("y" * 100)
        elif SCENARIO == "echo_token":
            chunk("leak " + SEEN_HEADER)
            sys.stderr.write("stderr " + SEEN_HEADER + "\n")
            sys.stderr.flush()
        else:
            chunk("hello ")
            chunk("world")
        send(
            {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {"stopReason": "cancelled" if SCENARIO == "cancelled" else "end_turn"},
            }
        )
    elif method == "session/cancel":
        record(method=method)
