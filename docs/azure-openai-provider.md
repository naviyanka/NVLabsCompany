# Azure OpenAI governed streaming provider

ADR 0006, PR 2. Adapter type `azure-openai-native` (registry key `azure_openai_native`), in
`src/nexus/adapters/azure_openai_native.py`. It is **off by default**. Its automated tests run against a local fake server; the Entra scope was validated live (see
"Derived scope") and one application-level acceptance call is recorded under "Live acceptance".

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

### Derived scope: `https://ai.azure.com/.default`

For the supported family (`*.openai.azure.com`) and the implemented path (`/openai/v1/chat/completions`), pages A, B, C
and D all apply and they disagree: A shows `https://cognitiveservices.azure.com/.default`; B, C and D show
`https://ai.azure.com/.default`. Documentation alone could not settle it, so a live probe did.

**Live probe, 2026-10-02.** One user principal, one tenant, one disposable Azure OpenAI resource in South India
(`disableLocalAuth=true`, regional `Standard` `gpt-4.1-mini` deployment, role Cognitive Services OpenAI User at account
scope). One minimal chat completion per candidate scope against `/openai/v1/chat/completions`:

| Scope | Result | Token audience |
|---|---|---|
| `https://cognitiveservices.azure.com/.default` | HTTP 200, reply "OK" | `https://cognitiveservices.azure.com` |
| `https://ai.azure.com/.default` | HTTP 200, reply "OK" | `https://ai.azure.com` |

Both scopes worked. NEXUS deliberately selects `https://ai.azure.com/.default`: it matches the current Learn pages for
this exact path and it is the service-specific audience rather than the shared Cognitive Services one. This page does not
claim the other scope is invalid.

- The scope is derived in code from the endpoint family (`ENTRA_SCOPES` in `azure_openai_native.py`). There is no scope
  setting and no runtime probing, and an `AZURE_OPENAI_TOKEN_SCOPE` environment variable or an agent `adapter_config` value
  is ignored.
- Any endpoint outside the supported family (a Foundry `*.services.ai.azure.com` host, a `*.cognitiveservices.azure.com`
  host, anything else) is rejected before a scope is derived and before any token is requested.
- There is no scope fallback. A token failure is `AZURE_OPENAI_AUTH_FAILED` and is never retried with another scope; an
  inference failure does not request a second token.
- Entra mode is usable for the supported family. The provider is still off by default (`AZURE_OPENAI_ENABLED=false`).
- **Not verified:** managed-identity and service-principal authentication (only a developer login was probed), other
  tenants, other regions and other endpoint families.

### Live acceptance (application level, 2026-10-02)

One paid request through the real NEXUS adapter (not a raw HTTP probe), run from a temporary harness that was not
committed. Azure was enabled only in that process's environment. The same resource as the probe above (South India,
`disableLocalAuth=true`, deployment `probe-mini`, `gpt-4.1-mini`), the developer's existing Azure CLI login through the
adapter's normal `DefaultAzureCredential` path, a throwaway SQLite database and no tools, company data or memory. Limits:
input `Reply with exactly OK`, 16 output tokens, 30 s timeout, no retry, one provider request.

| Check | Result |
|---|---|
| Scope requested | exactly `https://ai.azure.com/.default`, one token acquisition |
| Request | one `POST /openai/v1/chat/completions`, `max_completion_tokens` 16, no `tools` |
| Outcome | success; streamed text and final output both `OK` |
| Latency | 3166 ms end to end |
| Usage captured | 11 input tokens, 1 output token |
| Budget | one hold reserved and settled once (`committed`, 1 cent, the smallest unit); no release |
| Estimated cost | about INR 0.0006 at South India regional list prices; the repository price table maps `gpt-4.1*` to a higher price, so the recorded unit overestimates |
| Token or credential in output, logs, audit rows or tool rows | none found (checked against the in-memory token) |
| Tool invocations | 0 |

Two earlier attempts of the same harness made no token request and no HTTP request (zero cost; the budget hold was
released at 0): the shared test fixture used by the harness replaces `shutil.which`, so `AzureCliCredential` could not
see `az`. That was a test-process problem and needed no production change.

The sanitized record is `docs/testing/evidence/azure-openai-entra/ACCEPTANCE.md`. The latency is a single observation,
not a benchmark. The 1-cent ledger amount is the internal minimum accounting unit, not the Azure retail charge.

Not verified by this run: managed-identity and service-principal authentication (the call used an Azure CLI user
credential), other tenants, other regions and other endpoint families. It is one request from one user principal.
**Production enablement is a separate decision**, and managed identity still needs validation in the deployed
environment.

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
deployment, model, auth mode, endpoint family, the derived Entra scope and its selection basis (`live_validated`),
identity-SDK presence, credential-reference presence, timeout and a stable `unavailable_reason`. It makes no request, asks for no token, calls no tool, creates no turn, writes nothing and shows no
secret. A live probe is out of scope.

## Failure text

A failed provider or registry call never repeats the failure's own text. `chat._call_llm` answers with one fixed,
server-owned message (`PROVIDER_UNAVAILABLE_MESSAGE`) and a durable chat turn that raises stores `EXECUTION_ERROR` with that
same message. Logs carry only the stable code, the adapter identifier, the exception class and the agent, turn and execution
IDs: no message and no traceback. Use `status()` above for a sanitized diagnosis.

## Provider selection

Explicit. OmniRoute and Hermes-native stay available and nothing switches between them and Azure automatically. If Azure
fails the turn fails; there is no fallback.

## Not done here

Azure Speech (STT/TTS, ADR 0006 PR 3), browser voice, Teams, Telegram, attention and calling, migrations, and any Azure
resource beyond the retained test account used above. There is **no production rollout**: managed-identity and service-principal authentication are unverified. Azure Speech will consume this
provider's text events and needs the low-latency conversation strategy above to feel live.
