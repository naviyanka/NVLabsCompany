# ADR 0005 — Hermes governed tools over native API tool calls

**Status:** Proposed (draft PR). Supersedes the ACP prototype of ADR 0004, which is unsafe and stays disabled.
**Date:** 2026-09-29

## Problem

A Hermes CEO or manager turn needs the governed Nexus tools, and the tools must be prevented, not merely denied after the fact. ADR 0004 (Hermes over ACP) cannot do that: Hermes 0.20.5 always enables its built-in terminal, file, browser and code tools in an ACP session, so a client-side denial happens after a built-in tool may already have run.

## Paths investigated

1. **Hermes/Nous OpenAI-compatible API (chosen).** The chat-completions protocol has native `tools`, structured `message.tool_calls` with IDs, `role: tool` results, streamed `delta.tool_calls` and model selection. The model only produces tool-call objects; it executes nothing.
2. **Disable built-in tools in Hermes 0.20.5.** Not possible per invocation through ACP (no toolset selection in `session/new`); the only route is editing Hermes' global config, which Nexus must never do.
3. **Existing Nexus sandbox.** `evolution/isolated_sandbox.py` runs `docker run --memory --cpus --network=none --read-only --tmpfs /tmp` and falls back to an unsandboxed local subprocess when Docker is absent. It has no capability drop, no `no-new-privileges`, no PID limit, and `--network=none` forbids the model and MCP endpoints Hermes would need. It does not meet the requirements, and Windows Job Objects do not restrict filesystem or network access.

## Decision

`HermesProviderAdapter` (`adapter_type` `hermes_native`, agent `adapter_type` `hermes-native`, `adapters/hermes_provider.py`):

- The tool schema is the server-built catalog of the turn's agent (`MCPServer(ctx, node_tools=False)`): CEO tools, manager tools, snapshot-only, or none. No shell, filesystem, browser or network tool is ever offered.
- Tool calls are read only from the structured `tool_calls` field. Tool-call-like text in message content fails the turn. Nothing is parsed from free text.
- Every call goes through `MCPServer.call_tool`, hence catalog, `guarded_call` and `ToolPolicy`, with the identity of the durable turn (`manager_bridge.bind`: run principal, turn and session). Model-supplied identity fields fail argument validation.
- A whole response is validated before any call runs: complete IDs and names, JSON-object arguments, `finish_reason` `tool_calls`, unique IDs, offered names, call-count limits.
- Before each call the turn must still be running under this execution ID with a live lease and no cancel request.
- Bounds: iterations, total calls, calls per response, argument size, response size, tool-result size, tokens and total wall time.
- The API key is read from the secret backend (`hermes_native_secret_ref`); the endpoint is an operator setting (`hermes_native_base_url`), https unless loopback. Neither comes from agent config. The key appears in no argv, log, prompt, message or metadata, and errors are redacted.
- No fallback to ACP, the CLI, Claude or another adapter; there is no `register_tool`.

## Limits

- Not run against the live Nous endpoint (no paid call). The auth mechanism of Nous Portal is unverified: the Hermes CLI uses OAuth device login, and static API keys are unconfirmed. The adapter needs a bearer key in the secret backend; an OpenRouter or self-hosted OpenAI-compatible Hermes endpoint works the same way.
- Streaming behaviour is proven against a fake server only.
- The legacy `hermes` adapter still reads Hermes' `auth.json` and parses `<tool_call>` text; it is untouched and its governed prefixes stay blocked.
- Hermes ACP remains experimental and unsafe; `hermes_acp_tools_enabled` stays off.
