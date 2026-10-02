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
| `AZURE_OPENAI_ENDPOINT` | `https://<resource>.openai.azure.com`, the **only supported family** (see below). https only, no path, no userinfo/query/fragment, port 443. A Foundry project endpoint (`*.services.ai.azure.com`) is `AZURE_OPENAI_ENDPOINT_FAMILY_UNSUPPORTED`; any other host is `AZURE_OPENAI_ENDPOINT_INVALID`. Loopback is accepted only through the existing SSRF policy (`guard_url`), which is how the tests run. |
| `AZURE_OPENAI_DEPLOYMENT` | The **deployment name**. It is what goes on the wire as `model` (v1 route) or in the URL (dated route). |
| `AZURE_OPENAI_MODEL` | The **model id** (for example `gpt-4o`). Used only to price the budget. It is not sent. |
| `AZURE_OPENAI_API_VERSION` | `v1` (default) uses `/openai/v1/chat/completions` with no `api-version`. Any other value selects `/openai/deployments/<deployment>/chat/completions?api-version=<value>` and `max_tokens`. |
| `AZURE_OPENAI_AUTH` | `entra` (default) or `key`. |
| `AZURE_OPENAI_SECRET_REF` | Secret-backend name of a development key (key auth only). |
| `AZURE_OPENAI_TIMEOUT_SECONDS` | Hard outer timeout for the whole turn (0 < t <= 900). Default 120. |
| `AZURE_OPENAI_MAX_RETRIES` | Bounded retries for 429/5xx/connect failures before the first stream byte (0..5). Default 2. |

No API key is ever a setting, an agent field or a database field. Key auth reads the key from the secret backend and is
meant for development; production uses Entra.

## Entra auth and the token scope

Auth is `Authorization: Bearer <token>` from `azure.identity.aio.DefaultAzureCredential` (managed identity in Azure,
developer login locally). The role needed is Cognitive Services OpenAI User.

### Endpoint families

Two Azure endpoint families exist, and documentation for one is not authority for the other.

| Family | Host | Status here |
|---|---|---|
| Azure OpenAI resource | `<resource>.openai.azure.com` | The only supported family. |
| Azure AI Foundry project | `<resource>.services.ai.azure.com` | **Unsupported.** Disabled with `AZURE_OPENAI_ENDPOINT_FAMILY_UNSUPPORTED`. |
| Anything else (including `*.cognitiveservices.azure.com`) | n/a | `AZURE_OPENAI_ENDPOINT_INVALID`. |

The family is classified from the validated endpoint host. The Foundry family stays off because no page documents one
internally consistent token scope for `/openai/v1/chat/completions` on that host (page C below only says `base_url`
"also accepts" it, with no example on that host; page E documents the dated `/openai/deployments` path, not v1 chat).

### Evidence (all accessed 2026-10-02)

| | Page title | URL | ms.date | Endpoint family in example | API path | Scope shown |
|---|---|---|---|---|---|---|
| A | How to switch between OpenAI and Azure OpenAI endpoints \| Microsoft Learn | https://learn.microsoft.com/en-us/azure/developer/ai/how-to/switching-endpoints | 2026-08-24 | `*.openai.azure.com` (Entra "only supported with Azure OpenAI resources") | `/openai/v1/` | `https://cognitiveservices.azure.com/.default` |
| B | How to switch between OpenAI and Azure OpenAI endpoints with Python - Azure OpenAI Service \| Microsoft Learn | https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/switching-endpoints | 2025-09-30 | `*.openai.azure.com` | `/openai/v1/` | `https://ai.azure.com/.default` |
| C | Azure OpenAI in Microsoft Foundry Models v1 API - Microsoft Foundry \| Microsoft Learn | https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle | 2026-05-13 | `*.openai.azure.com` (text also mentions `*.services.ai.azure.com/openai/v1/`, no example) | `/openai/v1/`, REST `/openai/v1/chat/completions` | `https://ai.azure.com/.default` |
| D | Configure keyless authentication with Microsoft Entra ID - Microsoft Foundry \| Microsoft Learn | https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/configure-entra-id | 2026-08-31 | `<resource>.openai.azure.com` | `/openai/v1/` | `https://ai.azure.com/.default` |
| E | Authentication and authorization in Microsoft Foundry - Microsoft Foundry \| Microsoft Learn | https://learn.microsoft.com/en-us/azure/foundry/concepts/authentication-authorization-foundry | 2026-08-05 | `<resource>.services.ai.azure.com` (Foundry) | dated `/openai/deployments?api-version=2024-10-21` | `https://ai.azure.com/.default` |

The managed-identity page (ms.date 2026-08-04, `https://ai.azure.com/.default`) was cited earlier and not re-read.

### Derived scope: unresolved, so Entra is unavailable

For the supported family (`*.openai.azure.com`) and the implemented path (`/openai/v1/chat/completions`), pages A, B, C
and D all apply, and they **conflict**: A says `https://cognitiveservices.azure.com/.default`; B, C and D say
`https://ai.azure.com/.default`. Nothing in them reconciles the two, so the code does not guess.

- The scope is derived in code from the endpoint family (`ENTRA_SCOPES` in `azure_openai_native.py`). There is no
  scope setting and an `AZURE_OPENAI_TOKEN_SCOPE` environment variable is ignored.
- For the resource family the derived scope is currently `None`. Entra mode reports
  `AZURE_OPENAI_ENTRA_SCOPE_UNRESOLVED`, requests no token and makes no network call.
- There is no scope fallback. A token failure is `AZURE_OPENAI_AUTH_FAILED` and is never retried with another scope.
- The only usable mode today is development **key** auth through a secret reference.
- A live probe in the disposable Azure tenant must verify one scope before it is filled into `ENTRA_SCOPES` and Entra
  is enabled for production. That probe has not been done.

### Runtime dependency

`azure-identity>=1.26.0,<1.27` and `aiohttp>=3.10,<4` (the async transport `azure.identity.aio` needs; constructing
`DefaultAzureCredential` without it raises `ImportError`) are normal `pyproject.toml` dependencies, not an extra.
`Dockerfile.prod` already installs the project (`pip install ".[otel]"`), so the production image carries them with no
Dockerfile change, and the provider stays disabled by default. CI runs an import-smoke on the exact built production
image (`deploy-pipeline.yml`, "Import-smoke Azure provider runtime", `--network none`): it imports both packages and
asserts the provider reports `AZURE_OPENAI_DISABLED`.

If either module is missing while Entra is enabled, the status is `AZURE_OPENAI_IDENTITY_SDK_MISSING` before any turn
work. Nothing is ever installed at runtime, and no credential is printed or logged.

## Wire format

`POST {endpoint}/openai/v1/chat/completions`, body `model`, `messages`, `stream: true`,
`stream_options.include_usage: true`, `max_completion_tokens`, and `tools` plus `tool_choice: "auto"` when tools are
offered. Responses are SSE `data:` lines; tool calls arrive as `delta.tool_calls` fragments that are reassembled by index.
Only structured `tool_calls` execute. A tool-looking text answer is rejected, and a malformed or unexpected argument
fails closed.

## Streaming event contract

Provider-neutral (`governed_loop.Event`): `text_delta`, `tool_requested`, `tool_running`, `tool_completed`,
`usage_update`, `completed`, `cancelled`, `error`. No channel or audio concepts. Tool arguments never appear in an event.
A callback that raises cannot skip cancellation, budget settlement or audit.

Two cases, and only one of them streams:

- **Tool-free call** (no tools offered): text cannot be invalidated by a later tool call, so each `text_delta` is
  emitted as its chunk arrives, with nothing buffered. Tool-looking text is still rejected (checked against a short
  tail so a marker split across chunks is stopped before the completing delta). A native tool call here is refused with
  `BAD_TOOL_CALL`, and its arguments are never emitted.
- **Tool-capable governed round**: text is provisional, because a later native `tool_call` may invalidate it. It is held
  internally and never released as safe output while the round runs. If the round makes a tool call, the text is
  discarded. If it ends without one, the buffered text is released at completion. That is buffered end-of-round
  release, **not token streaming**, and it is not low-latency.

Low-latency governed voice therefore needs a later conversation strategy, for example a tool-free conversational profile
for ordinary turns, governed tool rounds followed by an explicit tool-free final-answer round, or another separately
approved two-phase design. That coordinator is not part of this PR. Through `_call_llm` the chat route still receives the
whole reply at once.

## Budget

Every round is metered separately (`services/streaming_budget.py`): reserve before the outbound request, then settle
from the authoritative `usage` when the stream sent it, otherwise from a conservative bounded estimate (3 characters per
token, capped at the output bound), and release the unused hold. A round that never started (HTTP refusal, cancel before
the first byte) bills nothing and is released. Cancel, timeout and error settle in a shielded cleanup scope. A stream that
ends early never reads as zero. A later round is refused once earlier rounds used the budget, and finished rounds stay
billed. `chat._call_llm` skips its own reservation for this adapter so a call is not counted twice. Self-metering is an
internal capability of the adapter registry (`register_adapter(..., self_metered=True)`, accepted only for a class that
declares `meters_budget`, set only for this provider in `_register_defaults`). Agent configuration or a forged class
attribute cannot skip the chat layer's reservation for any other adapter.
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
deployment, model, auth mode, endpoint family, derived Entra scope and whether it is resolved, identity-SDK presence, credential-reference presence, timeout and a stable
`unavailable_reason`. It makes no request, asks for no token, calls no tool, creates no turn, writes nothing and shows no
secret. A live probe is out of scope.

## Provider selection

Explicit. OmniRoute and Hermes-native stay available and nothing switches between them and Azure automatically. If Azure
fails the turn fails; there is no fallback.

## Not done here

Azure Speech (STT/TTS, ADR 0006 PR 3), browser voice, Teams, Telegram, attention and calling, migrations, live Azure
resources and any real or paid call. There is **no production or live acceptance yet**, and a live Entra probe in the
disposable Azure tenant is still required, to verify the token scope, before any rollout. Azure Speech will consume this
provider's text events and needs the low-latency conversation strategy above to feel live.
