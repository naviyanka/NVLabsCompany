# ADR 0004 — Hermes governed tools over an execution-scoped ACP session

**Status:** Experimental, unsafe (gate `HERMES_ACP_TOOLS_ENABLED` defaults to off)
**Date:** 2026-09-29

> **UNSAFE TO ENABLE WITHOUT PREVENTIVE SANDBOXING: Hermes built-in tools can execute before ACP permission denial.**
> This ACP path is an experimental prototype. Do not enable `hermes_acp_tools_enabled`.

## 1. Problem

The Hermes CLI reads MCP servers only from its persistent `config.yaml`, which Nexus must never write. It has no per-invocation MCP flag. So a Hermes CEO or manager chat turn could not receive the governed Nexus tools without either editing global Hermes state or parsing free-form `<tool_call>` text; both are rejected.

## 2. Decision

`hermes acp` accepts `mcpServers` in `session/new` and keeps them in that process's memory. For each tool-enabled Hermes turn `HermesACPTransport` (`adapters/hermes_acp.py`) therefore:

1. starts a fresh `hermes acp` child, contained in a job object (Windows) or its own session (POSIX);
2. sends `initialize`, then one `session/new` whose `cwd` is the real workspace and whose `mcpServers` holds only the execution-scoped Nexus server;
3. sends one `session/prompt`;
4. on any exit path sends `session/cancel` if the turn is live, then ends the whole process tree.

Nothing is shared between turns and nothing is replayed after an uncertain result. Ordinary non-tool Hermes chat keeps the existing `hermes -z` path.

## 3. Credentials

The manager-bridge JWT (company, agent, turn, execution, live lease, no cancel, at most 15 minutes) is minted exactly as for other CLIs. It is placed only in the `session/new` request. It is never written to a file, Hermes config, argv or environment, and the adapter redacts it from output, logs, errors and stderr.

Recovery claims a new execution ID, which invalidates the old token.

## 4. Permissions

- Every `session/request_permission` is answered by deny unless the tool is exactly an offered Nexus tool.
- Client requests (`fs/*`, `terminal/*`) are refused.
- Only the decision kind and outcome are recorded, never titles, commands or paths.
- A `tool_call` update that is not an offered Nexus tool ends the turn with `ACP_POLICY_VIOLATION`.
- `guarded_call` and `ToolPolicy` remain the authority on every MCP call. The catalog rules are unchanged: CEO gets the CEO tools, a manager the manager tools, snapshot-only authorization the snapshot tool, an ordinary employee none.

## 5. Limitation: Hermes cannot be confined by ACP

Hermes always enables its own coding toolset (terminal, files, browser, code execution, delegation) in an ACP session and asks the client only for dangerous commands. A client cannot remove those tools. The violation check is therefore detective: a built-in tool may already have run when the turn is ended. That is why the feature is off by default and must be enabled per deployment by an administrator who accepts this. It is a path for governed organisation tools, not a sandbox.

Hermes also writes its session history to its own state database under its normal home, like any Hermes run.

## 6. Guards

`tests/test_hermes_acp_guard.py` fails if production code runs `hermes mcp add/remove` or references Hermes home or `auth.json`, other than the existing deny list in `hermes_adapter.py`.

## 7. Acceptance status

Verified against a scripted fake `hermes acp` and, without a model call, against the installed Hermes 0.20.5. With a throwaway `HERMES_HOME` holding a dummy local provider, `initialize` and `session/new` succeeded, and Hermes connected to a local probe MCP server named in `mcpServers`, sent the `Authorization` header, and listed its tools. The real Hermes config, auth and `.env` hashes were unchanged and no process or temp directory remained. `session/new` needs a configured provider, so a real deployment must have Hermes authenticated in its own home. Not yet verified: an authenticated real prompt that invokes a governed tool, and the exact `tool_call` title Hermes emits for MCP tools. Until that is done the allow-list match on the title is an assumption, and a mismatch fails closed.
