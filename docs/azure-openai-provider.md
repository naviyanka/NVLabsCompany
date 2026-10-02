# Azure OpenAI governed streaming provider

ADR 0006, PR 2. Adapter type `azure-openai-native` (registry key `azure_openai_native`), in
`src/nexus/adapters/azure_openai_native.py`. It is **off by default** and has had **no live acceptance**: no real Azure
call, token request or model call was made while building it. Every test runs against a local fake server.

## What it is

A streaming chat-completions transport that plugs into the same governed tool loop as the Hermes-native provider
(`src/nexus/adapters/governed_loop.py`). The loop owns everything that is not wire format: native `tool_calls` only,
no textual tool-call parsing, rejection of tool-looking text, the round and call-count caps, argument validation,
`manager_bridge.bind` before every tool, `MCPServer.call_tool` and `guarded_call` and `ToolPolicy`, cancellation checks,
tool results returned under the right tool-call id, ToolInvocation and audit identity, and secret redaction.
Hermes-native behaves as before and its tests pass unchanged.

The old `adapters/azure_adapter.py` (registry key `azure_openai`) is non-streaming, authenticates with an `api-key`
header, has no SSRF guard and no tool loop. It is **unsuitable for governed CEO tool use**: `ceo_service.tool_support`
refuses it and nothing routes governed traffic to it. It is left in place; removing it needs separate approval.

## Configuration (operator settings only)

Nothing here can come from agent `adapter_config`. Missing or invalid values fail closed with a stable, sanitized
reason (`AZURE_OPENAI_<REASON>`).

| Setting | Meaning |
|---|---|
| `AZURE_OPENAI_ENABLED` | Gate. Default `false`. |
| `AZURE_OPENAI_ENDPOINT` | `https://<resource>.openai.azure.com` (also `.services.ai.azure.com`, `.cognitiveservices.azure.com`). https only, no path, no userinfo/query/fragment, port 443. Loopback is accepted only through the existing SSRF policy (`guard_url`), which is how the tests run. |
| `AZURE_OPENAI_DEPLOYMENT` | The **deployment name**. It is what goes on the wire as `model` (v1 route) or in the URL (dated route). |
| `AZURE_OPENAI_MODEL` | The **model id** (for example `gpt-4o`). Used only to price the budget. It is not sent. |
| `AZURE_OPENAI_API_VERSION` | `v1` (default) uses `/openai/v1/chat/completions` with no `api-version`. Any other value selects `/openai/deployments/<deployment>/chat/completions?api-version=<value>` and `max_tokens`. |
| `AZURE_OPENAI_AUTH` | `entra` (default) or `key`. |
| `AZURE_OPENAI_TOKEN_SCOPE` | Entra scope. **No default**, see below. |
| `AZURE_OPENAI_SECRET_REF` | Secret-backend name of a development key (key auth only). |
| `AZURE_OPENAI_TIMEOUT_SECONDS` | Hard outer timeout for the whole turn (0 < t <= 900). Default 120. |
| `AZURE_OPENAI_MAX_RETRIES` | Bounded retries for 429/5xx/connect failures before the first stream byte (0..5). Default 2. |

No API key is ever a setting, an agent field or a database field. Key auth reads the key from the secret backend and is
meant for development; production uses Entra.

## Entra auth and the token scope

Auth is `Authorization: Bearer <token>` from `azure.identity.aio.DefaultAzureCredential` (managed identity in Azure,
developer login locally). `azure-identity` is an **optional** extra (`pip install nexus[azure]`); without it the provider
reports `AZURE_OPENAI_IDENTITY_SDK_MISSING`. The role needed is Cognitive Services OpenAI User.

**The scope is not settled by Microsoft's own documentation.** Sources, all accessed 2026-10-02:

- Microsoft Learn, "Azure OpenAI v1 API" (ms.date 2026-05-13) and the managed-identity page (ms.date 2026-08-04): `https://ai.azure.com/.default`.
- Microsoft Learn, "switching-endpoints" (ms.date 2026-08-24): `https://cognitiveservices.azure.com/.default`.

ADR 0006 requires one verified scope, no guessed second scope, no silent fallback, and a disposable authenticated
probe. That probe has not been done. So the code picks none: the operator must set `AZURE_OPENAI_TOKEN_SCOPE` to exactly
one of the two documented values (anything else is `AZURE_OPENAI_TOKEN_SCOPE_INVALID`, empty is
`AZURE_OPENAI_TOKEN_SCOPE_UNSET`). Only that scope is ever requested; a token failure is
`AZURE_OPENAI_AUTH_FAILED` and is never retried with the other scope. A unit test pins the allow-list.

**Production enablement is withheld** until the approved one-time probe confirms which scope the service accepts and the
default is then fixed to that value.

## Wire format

`POST {endpoint}/openai/v1/chat/completions`, body `model`, `messages`, `stream: true`,
`stream_options.include_usage: true`, `max_completion_tokens`, and `tools` plus `tool_choice: "auto"` when tools are
offered. Responses are SSE `data:` lines; tool calls arrive as `delta.tool_calls` fragments that are reassembled by index.
Only structured `tool_calls` execute. A tool-looking text answer is rejected, and a malformed or unexpected argument
fails closed.

## Streaming event contract

Provider-neutral (`governed_loop.Event`): `text_delta`, `tool_requested`, `tool_running`, `tool_completed`,
`usage_update`, `completed`, `cancelled`, `error`. No channel or audio concepts. Tool arguments never appear in an event.
A round that turns out to carry tool calls never releases its text, so an unfinished or obsolete step is never a final
answer. A callback that raises cannot skip cancellation, budget settlement or audit.

**Limitation:** text is released when its round is final, not token by token, because a tool round's text must be
discardable. A consumer therefore sees the reply at the end of the final round. Live typing (and sentence-safe speech)
needs a follow-up that can prove the text is final earlier. Through `_call_llm` the chat route also receives the whole
reply at once.

## Budget

Every round is metered separately (`services/streaming_budget.py`): reserve before the outbound request, then settle
from the authoritative `usage` when the stream sent it, otherwise from a conservative bounded estimate (3 characters per
token, capped at the output bound), and release the unused hold. A round that never started (HTTP refusal, cancel before
the first byte) bills nothing and is released. Cancel, timeout and error settle in a shielded cleanup scope. A stream that
ends early never reads as zero. A later round is refused once earlier rounds used the budget, and finished rounds stay
billed. `chat._call_llm` skips its own reservation for this adapter so a call is not counted twice.
`cost_events` has company, agent and chat session; the turn and execution ids are logged on each settlement and carried
on the ToolInvocation audit rows (no migration).

The same change also meters the API-adapter streaming path `_stream_llm` (anthropic and openai), which previously
reserved nothing.

## Cancellation and timeout

Cancelling closes the HTTP stream. The loop checks cancellation before each request, between deltas and before each tool,
so no tool starts after a cancel. `AZURE_OPENAI_TIMEOUT_SECONDS` is a hard outer `asyncio.timeout` over the whole turn,
so a server that keeps trickling bytes still ends, reported as `AZURE_OPENAI_TIMEOUT`. No background task survives.

## Diagnostics (read-only)

`azure_openai_native.status()` (also under `azure_openai_native` in the CEO status) reports the flag, endpoint shape,
deployment, model, auth mode, scope validity, identity-SDK presence, credential-reference presence, timeout and a stable
`unavailable_reason`. It makes no request, asks for no token, calls no tool, creates no turn, writes nothing and shows no
secret. A live probe is out of scope.

## Provider selection

Explicit. OmniRoute and Hermes-native stay available and nothing switches between them and Azure automatically. If Azure
fails the turn fails; there is no fallback.

## Not done here

Azure Speech (STT/TTS, ADR 0006 PR 3), browser voice, Teams, Telegram, attention and calling, migrations, live Azure
resources and any real or paid call. Azure Speech will consume this provider's text events and needs the buffered-text
limitation above resolved to feel live.
