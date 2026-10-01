# Legacy channel ingress

This note records why the legacy inbound Telegram and Slack routes are disabled,
what still works, and what replaces them. It implements PR 0 of
[ADR 0006](../adr/0006-azure-conversational-ceo.md). It is not a new channel
feature and does not describe either route as secure or supported.

## What changed

| Route | Before | After |
|---|---|---|
| `POST /api/v1/channels/telegram/webhook` | Ran `/status`, `/agents`, `/task`, `/help` for the company of the calling API key. `/task` created a Task. | 410 `LEGACY_CHANNEL_INGRESS_DISABLED`. |
| `POST /api/v1/channels/slack/events` | Answered `url_verification` and created a Task for every `app_mention`. | 410 `LEGACY_CHANNEL_INGRESS_DISABLED`, including for `url_verification`. |

Both handlers now take no request input. They do not read the body, so there is
nothing to size-limit, parse or deserialize, and a replayed or duplicated
delivery cannot have a side effect. They open no database session, call no
provider and send no message. The only trace is one warning naming the channel.
There is no flag, environment variable or fallback that re-enables the old
behavior: the code was removed, not gated. The routes stay registered, marked
`deprecated` in OpenAPI, so existing webhook registrations receive a stable
answer instead of a 404.

The response is the same for every caller and every payload:

```json
{"detail": "Legacy Telegram inbound commands are disabled.", "code": "LEGACY_CHANNEL_INGRESS_DISABLED"}
```

It names no company, agent or policy, and echoes nothing from the request. A
request with no NEXUS credential is still refused earlier by the authentication
middleware with 401 `UNAUTHENTICATED`.

## Why an API key or webhook secret is not human authorization

An API key identifies a company. A Telegram secret token or a Slack signing
secret identifies the sending service. Neither says which human wrote the
message, and the legacy schema has no table linking an external Telegram or
Slack user to a NEXUS user and company membership. The old routes therefore
treated every sender, in every chat the bot could see, as an authorized
operator. That is the vulnerability, and verifying the webhook secret alone
would not have fixed it.

The invariant now enforced: no inbound channel request may create a Task, Goal
or ChatTurn as a human, invoke a tool, approve anything or mutate company data
unless NEXUS can map the externally authenticated sender to an active NEXUS user
and company membership and run normal authorization. The legacy schema cannot
provide that mapping, so the routes fail closed.

There is deliberately no temporary sender allowlist. Identity is not inferred
from a Telegram username, display name, phone number, chat title, a Telegram
user ID without a verified link, or the company API key.

## Vulnerabilities found in the old routes

- The credential named a company, not the sender, so any sender was authorized.
- `/task` and Slack `app_mention` created Tasks from any sender.
- No Telegram `X-Telegram-Bot-Api-Secret-Token` check and no Slack
  `X-Slack-Signature` check.
- No update or event deduplication, so a replayed delivery repeated its effect.
- Telegram's `/status` returned system health and `/agents` returned agent names
  to any sender; error replies echoed raw exception text.
- The reply helper sent to the `chat_id` in the payload using the bot token, so
  a caller could make the bot message any chat.
- The Slack route logged the Slack user and channel IDs.
- The body was parsed with `request.json()` with no size bound.
- With `AUTH_ENABLED=false`, the `X-Company-Id` header became the principal, so
  an unauthenticated caller could create Tasks in any company whose ID they knew.
  `AUTH_ENABLED` defaults to true; `config_validator` only logs a warning when it
  is false.

Both routes were registered unconditionally in `main.py`, with no feature flag,
so they were reachable in every environment. With auth on, a request needed a
NEXUS principal (session, API key or run token); Telegram and Slack cannot send
one natively, so real deliveries reached the routes only through a proxy that
injected an API key.

## What still works

- **Outbound Telegram**: the `msg-telegram-send` workflow node
  (`nexus.nodes.executor._run_telegram_send`) uses `TELEGRAM_BOT_TOKEN`, sends
  to a destination configured in the workflow, and exposes no inbound path.
- **Outbound Slack, Discord and webhook delivery**: `SlackChannel`,
  `DiscordChannel` and `WebhookChannel` in `nexus.communication.channels`.
- **Per-trigger webhooks** at `POST /api/v1/webhooks/{trigger_id}`: unchanged.
  Each trigger has its own secret checked in constant time, a rate limit and a
  body cap, and it runs an admin-configured agent. It is a service integration,
  not a human-sender channel, and it creates no Task, Goal or tool call. Remaining
  gaps there (no replay protection, and the payload reaches an LLM prompt) are out
  of scope for this change.
- **`ChannelRouter.handle_inbound`** persists a `Message` as an agent. No route
  calls it; a guard test keeps it that way.

## Operator behavior

- Telegram and Slack deliveries to the legacy URLs now fail with 410. Telegram
  retries a failing webhook for a while, so expect brief retry traffic; remove the
  webhook with `deleteWebhook` (Telegram) or disable Event Subscriptions (Slack).
- Slack can no longer verify the endpoint, so it cannot be re-registered.
- Create Tasks from the dashboard, API or CLI as an authenticated user.
- Keep `AUTH_ENABLED=true`. Turning it off makes every tenant impersonable
  through `X-Company-Id`, independent of this change.

## Replacement roadmap

Inbound chat channels return through ADR 0006 as separate, flagged PRs. The
secure flow is:

provider verification → channel installation → linked identity → active
membership → NEXUS principal → normal authorization

- Provider verification checks the Telegram secret token or Slack signature and
  rejects replays. It authenticates the service only.
- A channel installation binds a bot or workspace to one company.
- A linked identity maps an external user to a NEXUS user after the user proves
  control of both accounts.
- Active membership is re-checked on every request, so removed users stop working.
- The resulting NEXUS principal goes through the normal authorization,
  ToolPolicy and approval path. No channel gets a second permission engine.

Those flags stay separate from this change. Until they ship, inbound Telegram
and Slack mutation stays off.

## Guard tests

- `tests/test_channel_tenant_binding.py` drives both routes with an API key, a
  forged `X-Company-Id`, no credential, wrong, empty and missing secrets,
  malformed, deep and oversized bodies and replayed deliveries. It asserts a 410
  with a fixed body, no leaked tenant detail, no secrets or payload in logs, and
  an unchanged row count in every table.
- `tests/test_legacy_channel_ingress_guard.py` scans every route module under
  `/api/v1/channels/` and fails if it constructs or imports Task, Goal,
  ChatTurn, ToolInvocation or Approval, opens a `tenant_session`, depends on
  `CurrentCompanyId`, makes an HTTP call, or accepts request input. It also
  fails if any route calls `handle_inbound`.
- PostgreSQL: `test_legacy_channel_webhooks_create_no_task_in_any_company`.
