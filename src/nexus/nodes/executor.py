"""Node execution layer for the workflow node library.

Binds real executors to node definitions from the catalog. A node without a
registered executor is browse-only; nodes listed in EXECUTABLE_NODE_IDS run
through :func:`execute_node` with timeout enforcement.
"""

import asyncio
import csv
import io
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60.0


@dataclass
class ExecutorResult:
    """Outcome of a single node execution."""

    success: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    tokens_used: int = 0


ExecutorFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class NodeExecutor:
    """An async executor function bound to one or more node IDs."""

    node_ids: list[str]
    run: ExecutorFn
    description: str = ""


class ExecutorRegistry:
    """Registry mapping node_id -> executor."""

    def __init__(self) -> None:
        self._by_node_id: dict[str, NodeExecutor] = {}

    def register(self, executor: NodeExecutor) -> None:
        for node_id in executor.node_ids:
            self._by_node_id[node_id] = executor

    def get(self, node_id: str) -> NodeExecutor | None:
        return self._by_node_id.get(node_id)

    @property
    def executable_node_ids(self) -> list[str]:
        return sorted(self._by_node_id.keys())


# ---------------------------------------------------------------------------
# Shared LLM plumbing (mirrors chat routing via UASTL + AdapterRegistry)
# ---------------------------------------------------------------------------


async def _llm_prompt(prompt: str, model: str | None = None) -> tuple[str, int]:
    """Send a bare prompt through the default-configured adapter."""
    from nexus.adapters.registry import AdapterRegistry
    from nexus.adapters.uastl import resolve_provider

    registry_key, config = resolve_provider("anthropic", model)
    api_key = config.get("api_key", "")
    if registry_key in ("anthropic", "openai", "azure_openai") and not api_key:
        raise RuntimeError(
            f"No API key configured for adapter '{registry_key}'. "
            "Set the provider environment variable to use AI nodes."
        )

    adapter_registry = AdapterRegistry()
    adapter = adapter_registry.create_adapter(registry_key)

    class _SessionRef:
        id = "node-executor"

    session_config = {**config, "system_prompt": "You are a precise workflow step."}
    session = await adapter.create_session(_SessionRef(), session_config)
    try:
        result = await adapter.execute_task(
            session,
            __import__("uuid").uuid4(),
            {"objective": prompt, "prompt": prompt, "system_prompt": session_config["system_prompt"]},
        )
    finally:
        await adapter.terminate(session)

    if not result.success or not result.output:
        raise RuntimeError(result.error or "LLM returned no output")
    return str(result.output), result.input_tokens + result.output_tokens


def _required(params: dict[str, Any], key: str) -> Any:
    if key not in params or params[key] in (None, ""):
        raise ValueError(f"Missing required parameter '{key}'")
    return params[key]


# ---------------------------------------------------------------------------
# Built-in executors
# ---------------------------------------------------------------------------


async def _run_ai_chat(params: dict[str, Any]) -> dict[str, Any]:
    response, tokens = await _llm_prompt(
        str(_required(params, "prompt")), params.get("model")
    )
    return {"response": response, "tokens_used": tokens}


def _summarize_prompt(text: str, max_length: Any) -> str:
    limit = int(max_length) if max_length else 150
    return (
        f"Summarize the following text in at most {limit} words. "
        "Return only the summary.\n\n" + text
    )


def _translate_prompt(text: str, target_language: Any) -> str:
    lang = target_language or "English"
    return (
        f"Translate the following text into {lang}. Return only the "
        f"translation.\n\n{text}"
    )


def _sentiment_prompt(text: str) -> str:
    return (
        "Classify the sentiment of the following text as exactly one word: "
        "positive, negative, or neutral.\n\n" + text
    )


async def _run_ai_summarize(params):
    summary, _ = await _llm_prompt(_summarize_prompt(str(_required(params, "text")), params.get("max_length")), params.get("model"))
    return {"summary": summary.strip()}


async def _run_ai_translate(params):
    translated, _ = await _llm_prompt(
        _translate_prompt(str(_required(params, "text")), params.get("target_language")),
        params.get("model"),
    )
    return {"translated": translated.strip()}


async def _run_ai_sentiment(params):
    raw, _ = await _llm_prompt(_sentiment_prompt(str(_required(params, "text"))), params.get("model"))
    sentiment = raw.strip().split()[0].lower().strip(".!?,")
    score = {"positive": 0.9, "negative": -0.9}.get(sentiment, 0.0)
    return {"sentiment": sentiment if sentiment in ("positive", "negative", "neutral") else "neutral", "score": score}


async def _run_http_request(params: dict[str, Any]) -> dict[str, Any]:
    import httpx

    from nexus.governance.ssrf_protection import SSRFGuard

    url = str(_required(params, "url"))
    method = str(params.get("method") or "GET").upper()
    guard = SSRFGuard()
    if not guard.is_safe_url(url):
        raise ValueError(f"URL blocked by SSRF protection: {url}")

    headers = params.get("headers") or {}
    body = params.get("body")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(method, url, headers=headers, json=body)
    try:
        parsed = response.json()
    except Exception:
        parsed = response.text
    return {
        "status": response.status_code,
        "body": parsed,
        "headers": dict(response.headers),
    }


async def _run_webhook_notify(params: dict[str, Any]) -> dict[str, Any]:
    import httpx

    from nexus.governance.ssrf_protection import SSRFGuard

    url = str(_required(params, "url"))
    payload = params.get("payload") or {}
    if not SSRFGuard().is_safe_url(url):
        raise ValueError(f"URL blocked by SSRF protection: {url}")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload)
    return {"status_code": response.status_code}


async def _run_json_parse(params: dict[str, Any]) -> dict[str, Any]:
    text = str(_required(params, "text"))
    return {"data": json.loads(text)}


async def _run_csv_parse(params: dict[str, Any]) -> dict[str, Any]:
    content = str(_required(params, "content"))
    delimiter = str(params.get("delimiter") or ",")[0]
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    rows = [row for row in reader]
    headers_row = rows[0] if rows else []
    data_rows = rows[1:]
    as_dicts = [dict(zip(headers_row, row)) for row in data_rows]
    return {"rows": as_dicts, "headers": headers_row}


# ---------------------------------------------------------------------------
# Database executors
# ---------------------------------------------------------------------------


async def _run_redis_get(params: dict[str, Any]) -> dict[str, Any]:
    import redis.asyncio as aioredis

    from nexus.config import settings

    key = str(_required(params, "key"))
    client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=5.0)
    try:
        value = await client.get(key)
    finally:
        await client.aclose()
    return {"value": value}


async def _run_redis_set(params: dict[str, Any]) -> dict[str, Any]:
    import redis.asyncio as aioredis

    from nexus.config import settings

    key = str(_required(params, "key"))
    value = str(_required(params, "value"))
    ttl = params.get("ttl")
    client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=5.0)
    try:
        if ttl:
            await client.set(key, value, ex=int(ttl))
        else:
            await client.set(key, value)
    finally:
        await client.aclose()
    return {"ok": True}


async def _run_sqlite_query(params: dict[str, Any]) -> dict[str, Any]:
    import sqlite3

    path = str(_required(params, "path"))
    query = str(_required(params, "query"))
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(query)
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
    return {"rows": rows}


# ---------------------------------------------------------------------------
# Messaging executors (reuse real channel implementations)
# ---------------------------------------------------------------------------


async def _run_slack_send(params: dict[str, Any]) -> dict[str, Any]:
    import httpx

    channel = str(_required(params, "channel"))
    text = str(_required(params, "text"))
    import os

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        raise ValueError("SLACK_WEBHOOK_URL not configured")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(webhook_url, json={"channel": channel, "text": text})
    if resp.status_code >= 300:
        raise RuntimeError(f"Slack returned HTTP {resp.status_code}")
    return {"ts": resp.text}


async def _run_discord_send(params: dict[str, Any]) -> dict[str, Any]:
    import httpx

    channel_id = str(_required(params, "channel_id"))
    content = str(_required(params, "content"))
    import os

    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN not configured")
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers={"Authorization": f"Bot {token}"}, json={"content": content[:2000]})
    if resp.status_code >= 300:
        raise RuntimeError(f"Discord returned HTTP {resp.status_code}")
    data = resp.json()
    return {"message_id": data.get("id", "")}


async def _run_telegram_send(params: dict[str, Any]) -> dict[str, Any]:
    import httpx

    chat_id = str(_required(params, "chat_id"))
    text = str(_required(params, "text"))
    import os

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not configured")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json={"chat_id": chat_id, "text": text})
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram error: {data.get('description', 'unknown')}")
    return {"message_id": data["result"]["message_id"]}


def build_default_registry() -> ExecutorRegistry:
    """Register all built-in executors."""
    registry = ExecutorRegistry()

    registry.register(NodeExecutor(node_ids=["ai-chat"], run=_run_ai_chat))
    registry.register(
        NodeExecutor(
            node_ids=["ai-summarize", "ai-translate", "ai-sentiment"],
            run=lambda params: _dispatch_ai(params),
            description="Prompt-based AI utility nodes",
        )
    )
    registry.register(NodeExecutor(node_ids=["http-request"], run=_run_http_request))
    registry.register(NodeExecutor(node_ids=["msg-webhook-notify"], run=_run_webhook_notify))
    registry.register(NodeExecutor(node_ids=["file-json-parse"], run=_run_json_parse))
    registry.register(NodeExecutor(node_ids=["file-csv-parse"], run=_run_csv_parse))
    registry.register(NodeExecutor(node_ids=["db-redis-get"], run=_run_redis_get))
    registry.register(NodeExecutor(node_ids=["db-redis-set"], run=_run_redis_set))
    registry.register(NodeExecutor(node_ids=["db-sqlite-query"], run=_run_sqlite_query))
    registry.register(NodeExecutor(node_ids=["msg-slack-send"], run=_run_slack_send))
    registry.register(NodeExecutor(node_ids=["msg-discord-send"], run=_run_discord_send))
    registry.register(NodeExecutor(node_ids=["msg-telegram-send"], run=_run_telegram_send))
    return registry


async def _dispatch_ai(params: dict[str, Any]) -> dict[str, Any]:
    """Route shared-signature AI nodes by their declared 'operation' hint.

    The route layer passes the node_id separately; this indirection keeps a
    single registered callable per NodeExecutor entry.
    """
    operation = params.pop("__operation__", "")
    if operation == "ai-summarize":
        return await _run_ai_summarize(params)
    if operation == "ai-translate":
        return await _run_ai_translate(params)
    if operation == "ai-sentiment":
        return await _run_ai_sentiment(params)
    raise ValueError(f"Unknown AI operation '{operation}'")


_default_registry: ExecutorRegistry | None = None


def get_default_registry() -> ExecutorRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = build_default_registry()
    return _default_registry


async def execute_node(
    node_id: str,
    params: dict[str, Any],
    registry: ExecutorRegistry | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> ExecutorResult:
    """Execute a node by ID with timeout enforcement."""
    from nexus.observability.tracing import get_tracer

    tracer = get_tracer("nexus.nodes")
    with tracer.start_as_current_span("execute_node") as span:
        span.set_attribute("node_id", node_id)
        reg = registry or get_default_registry()
        executor = reg.get(node_id)
        if executor is None:
            return ExecutorResult(success=False, error=f"No executor registered for node '{node_id}'")

        call_params = dict(params)
        call_params["__operation__"] = node_id
        try:
            outputs = await asyncio.wait_for(executor.run(call_params), timeout=timeout_seconds)
            span.set_attribute("success", True)
            return ExecutorResult(success=True, outputs=outputs)
        except asyncio.TimeoutError:
            span.set_attribute("success", False)
            return ExecutorResult(success=False, error=f"Execution timed out after {timeout_seconds}s")
        except ValueError as exc:
            span.set_attribute("success", False)
            span.record_exception(exc)
            return ExecutorResult(success=False, error=str(exc))
        except Exception as exc:
            span.set_attribute("success", False)
            span.record_exception(exc)
            logger.warning("Node %s execution failed: %s", node_id, exc)
            return ExecutorResult(success=False, error=str(exc))
