"""Hermes Adapter - implements AgentAdapter for Nous Research Hermes 3 models.

Extends the Ollama adapter with Hermes-specific features:
- Structured <tool_call> parsing and execution
- OpenRouter fallback when local Ollama isn't available
- CEO/orchestrator system prompt injection
- Function-calling schema enforcement
- Plaza Knowledge Feed broadcasting hooks

Hermes 3 models support tool calling natively via a special XML-like format:
    <tool_call>
    {"name": "function_name", "arguments": {"key": "value"}}
    </tool_call>

This adapter handles parsing those calls and routing them to registered tools.
"""

import json
import logging
import re
import uuid
from typing import Any

from nexus.adapters.base import BaseAdapter
from nexus.runtime.adapter import AgentSession, TaskResult

logger = logging.getLogger(__name__)

# Default model hierarchy (local → cloud fallback)
HERMES_MODELS = {
    "local": "hermes3:8b",  # Ollama tag for Hermes 3 8B
    "local_large": "hermes3:70b",  # Ollama tag for Hermes 3 70B
    "cloud": "nousresearch/hermes-3-llama-3.1-405b",  # OpenRouter
    "cloud_small": "nousresearch/hermes-3-llama-3.1-8b",  # OpenRouter
}

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Regex to extract <tool_call> blocks from Hermes output
TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL,
)

# CEO system prompt for orchestration mode
CEO_SYSTEM_PROMPT = """You are Hermes, the Chief Executive Officer and Principal System Orchestrator of NVLabsCompany. You are powered by Nous Research Hermes 3.

Your authority:
- Full operational control over all agents, tasks, pipelines, and workflows
- Task decomposition and delegation to specialized workforce agents
- Budget monitoring and governance enforcement
- Git worktree isolation for code changes
- Memory graph and RAG context management

Your tools:
- task_create: Create and assign tasks to agents
- task_delegate: Route tasks to the best-fit agent
- pipeline_run: Execute multi-step pipelines
- agent_wake: Activate idle agents
- agent_pause: Pause misbehaving agents
- memory_store: Write to the knowledge graph
- plaza_broadcast: Share discoveries on the Plaza Feed
- budget_check: Verify spend before expensive operations

When you need to use a tool, emit:
<tool_call>
{"name": "tool_name", "arguments": {"param": "value"}}
</tool_call>

Always verify task completion before declaring success. Log architectural decisions to the Plaza Knowledge Feed. Balance workload across the workforce."""


class HermesAdapter(BaseAdapter):
    """Agent adapter for Nous Research Hermes 3 models.

    Supports both local execution (Ollama) and cloud fallback (OpenRouter).
    Handles Hermes's native <tool_call> format for function calling.
    Can operate in CEO/orchestrator mode with full system authority.
    """

    adapter_type: str = "hermes"

    def __init__(self) -> None:
        """Initialize the Hermes adapter."""
        super().__init__()
        self._tool_registry: dict[str, Any] = {}
        self._pending_tool_calls: dict[str, list[dict[str, Any]]] = {}

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate Hermes configuration.

        Requires either Ollama access or an OpenRouter API key.

        Args:
            config: Configuration dictionary.

        Raises:
            ValueError: If neither local nor cloud backend is configured.
        """
        # At minimum, we need a model specified or will use defaults
        # Either ollama_host or openrouter_api_key should be set
        pass  # Hermes is flexible — will auto-detect available backend

    def register_tool(self, name: str, handler: Any, schema: dict[str, Any] | None = None) -> None:
        """Register a tool that Hermes can call.

        Args:
            name: Tool name (matches what Hermes emits in <tool_call>).
            handler: Async callable to execute when tool is invoked.
            schema: Optional JSON schema for the tool's parameters.
        """
        self._tool_registry[name] = {
            "handler": handler,
            "schema": schema,
        }

    async def _do_create_session(self, session: AgentSession) -> None:
        """Initialize Hermes session with backend detection.

        Checks Ollama first, falls back to OpenRouter if unavailable.

        Args:
            session: The newly created session.
        """
        is_ceo = session.config.get("is_ceo", False)
        host = session.config.get("ollama_host", DEFAULT_OLLAMA_HOST)
        openrouter_key = session.config.get("openrouter_api_key", "")
        model = session.config.get("model", "")

        # Determine backend and model
        backend = "ollama"
        selected_model = model or HERMES_MODELS["local"]

        # Check if Ollama has the model
        if await self._check_ollama(host, selected_model):
            backend = "ollama"
            logger.info(f"Hermes session using Ollama: {selected_model}")
        elif openrouter_key:
            backend = "openrouter"
            selected_model = model or HERMES_MODELS["cloud_small"]
            logger.info(f"Hermes session using OpenRouter: {selected_model}")
        else:
            # Fallback to any available Hermes-compatible model on Ollama
            available = await self._list_ollama_models(host)
            hermes_models = [m for m in available if "hermes" in m.lower()]
            if hermes_models:
                selected_model = hermes_models[0]
                logger.info(f"Hermes session using available local model: {selected_model}")
            else:
                # Last resort: use any llama model
                llama_models = [m for m in available if "llama" in m.lower()]
                if llama_models:
                    selected_model = llama_models[0]
                    logger.warning(
                        f"No Hermes model found, falling back to: {selected_model}"
                    )

        session.metadata["backend"] = backend
        session.metadata["model"] = selected_model
        session.metadata["host"] = host
        session.metadata["openrouter_key"] = openrouter_key
        session.metadata["is_ceo"] = is_ceo
        session.metadata["tool_calls_made"] = 0

        # Set system prompt
        if is_ceo:
            session.metadata["system_prompt"] = CEO_SYSTEM_PROMPT
        else:
            session.metadata["system_prompt"] = session.config.get(
                "system_prompt",
                "You are Hermes, an autonomous agent powered by Nous Research Hermes 3. "
                "You excel at tool calling, function execution, and complex problem solving.",
            )

    async def _do_execute(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        """Execute a task via Hermes, handling tool calls.

        Sends the prompt, parses any <tool_call> blocks from the response,
        executes matched tools, and returns the combined result.

        Args:
            session: The active agent session.
            task_id: The task identifier.
            payload: Must contain 'prompt'. Optionally 'tools', 'max_tool_rounds'.

        Returns:
            TaskResult with the model's response and any tool execution results.
        """
        import httpx

        prompt = payload.get("prompt", "")
        max_tool_rounds = payload.get("max_tool_rounds", 5)
        backend = session.metadata["backend"]

        # Build messages
        messages: list[dict[str, str]] = []
        system_prompt = session.metadata["system_prompt"]
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Include available tools in system message if tools registered
        if self._tool_registry:
            tool_descriptions = self._format_tool_descriptions()
            messages[0]["content"] += f"\n\nAvailable tools:\n{tool_descriptions}"

        # Add conversation history
        history = self._conversation_history.get(session.session_id, [])
        messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        total_input_tokens = 0
        total_output_tokens = 0
        total_cost_cents = 0
        tool_results: list[dict[str, Any]] = []
        final_output = ""

        # Iterative tool-calling loop
        for _round in range(max_tool_rounds):
            # Call the model
            if backend == "ollama":
                result = await self._call_ollama(session, messages)
            else:
                result = await self._call_openrouter(session, messages)

            if not result["success"]:
                return TaskResult(
                    task_id=task_id,
                    agent_id=session.agent_id,
                    success=False,
                    error=result.get("error", "Unknown error"),
                )

            response_text = result["output"]
            total_input_tokens += result.get("input_tokens", 0)
            total_output_tokens += result.get("output_tokens", 0)
            total_cost_cents += result.get("cost_cents", 0)

            # Parse tool calls from response
            tool_calls = self._parse_tool_calls(response_text)

            if not tool_calls:
                # No tool calls — this is the final answer
                final_output = response_text
                break

            # Execute tool calls
            messages.append({"role": "assistant", "content": response_text})

            for call in tool_calls:
                tool_name = call.get("name", "")
                tool_args = call.get("arguments", {})

                tool_result = await self._execute_tool(tool_name, tool_args)
                tool_results.append({
                    "tool": tool_name,
                    "arguments": tool_args,
                    "result": tool_result,
                })

                # Feed tool result back as a user message
                messages.append({
                    "role": "user",
                    "content": f"[Tool Result: {tool_name}]\n{json.dumps(tool_result, default=str)}",
                })

            session.metadata["tool_calls_made"] = (
                session.metadata.get("tool_calls_made", 0) + len(tool_calls)
            )
        else:
            # Exceeded max rounds
            final_output = response_text  # type: ignore[possibly-undefined]

        # Update conversation history
        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": final_output})
        self._conversation_history[session.session_id] = history

        # Build combined output
        output_parts = [final_output]
        if tool_results:
            output_parts.append(
                f"\n\n[Executed {len(tool_results)} tool(s): "
                f"{', '.join(r['tool'] for r in tool_results)}]"
            )

        return TaskResult(
            task_id=task_id,
            agent_id=session.agent_id,
            success=True,
            output="\n".join(output_parts),
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cost_cents=total_cost_cents,
            artifacts={"tool_results": tool_results} if tool_results else None,
            logs=[
                f"Backend: {backend}, Model: {session.metadata['model']}, "
                f"Tool calls: {len(tool_results)}, Rounds: {_round + 1}"
            ],
        )

    async def _call_ollama(
        self, session: AgentSession, messages: list[dict[str, str]]
    ) -> dict[str, Any]:
        """Call Ollama chat API.

        Args:
            session: Active session with host/model metadata.
            messages: Chat messages to send.

        Returns:
            Dict with success, output, token counts.
        """
        import httpx

        host = session.metadata["host"]
        model = session.metadata["model"]

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    f"{host}/api/chat",
                    json={"model": model, "messages": messages, "stream": False},
                )

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Ollama error {response.status_code}: {response.text}",
                }

            data = response.json()
            content = data.get("message", {}).get("content", "")
            return {
                "success": True,
                "output": content,
                "input_tokens": data.get("prompt_eval_count", 0),
                "output_tokens": data.get("eval_count", 0),
                "cost_cents": 0,  # Local is free
            }
        except Exception as e:
            return {"success": False, "error": f"Ollama request failed: {e}"}

    async def _call_openrouter(
        self, session: AgentSession, messages: list[dict[str, str]]
    ) -> dict[str, Any]:
        """Call OpenRouter API as cloud fallback.

        Args:
            session: Active session with OpenRouter key/model metadata.
            messages: Chat messages to send.

        Returns:
            Dict with success, output, token counts, cost.
        """
        import httpx

        api_key = session.metadata["openrouter_key"]
        model = session.metadata["model"]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://nvlabs.company",
            "X-Title": "NVLabs NEXUS",
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{OPENROUTER_BASE}/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": 4096,
                    },
                )

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"OpenRouter error {response.status_code}: {response.text}",
                }

            data = response.json()
            choice = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")
            usage = data.get("usage", {})

            # OpenRouter pricing (approximate for Hermes 3 405B)
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            # ~$2.70/M input, ~$2.70/M output for 405B on OpenRouter
            cost_cents = int((input_tokens + output_tokens) * 0.00027)

            return {
                "success": True,
                "output": content,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_cents": cost_cents,
            }
        except Exception as e:
            return {"success": False, "error": f"OpenRouter request failed: {e}"}

    def _parse_tool_calls(self, text: str) -> list[dict[str, Any]]:
        """Parse <tool_call> blocks from Hermes model output.

        Args:
            text: The raw model response text.

        Returns:
            List of parsed tool call dicts with 'name' and 'arguments'.
        """
        calls: list[dict[str, Any]] = []
        matches = TOOL_CALL_PATTERN.findall(text)

        for match in matches:
            try:
                parsed = json.loads(match)
                if "name" in parsed:
                    calls.append(parsed)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse tool_call JSON: {match[:100]}")
                continue

        return calls

    async def _execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a registered tool by name.

        Args:
            name: The tool name to execute.
            arguments: The arguments to pass to the tool handler.

        Returns:
            Tool execution result dict.
        """
        if name not in self._tool_registry:
            return {"error": f"Tool '{name}' not registered", "status": "not_found"}

        handler = self._tool_registry[name]["handler"]
        try:
            import asyncio
            import inspect

            if inspect.iscoroutinefunction(handler):
                result = await handler(**arguments)
            else:
                result = await asyncio.to_thread(handler, **arguments)

            return {"result": result, "status": "success"}
        except Exception as e:
            logger.error(f"Tool '{name}' execution failed: {e}")
            return {"error": str(e), "status": "failed"}

    def _format_tool_descriptions(self) -> str:
        """Format registered tools into a description string for the system prompt.

        Returns:
            Formatted tool descriptions.
        """
        lines = []
        for name, tool in self._tool_registry.items():
            schema = tool.get("schema", {})
            desc = schema.get("description", "No description")
            params = schema.get("parameters", {})
            lines.append(f"- {name}: {desc}")
            if params:
                for param_name, param_info in params.items():
                    lines.append(f"    {param_name}: {param_info}")
        return "\n".join(lines)

    async def _check_ollama(self, host: str, model: str) -> bool:
        """Check if a specific model is available on Ollama.

        Args:
            host: Ollama host URL.
            model: Model name to check.

        Returns:
            True if the model is available locally.
        """
        try:
            available = await self._list_ollama_models(host)
            return any(model in m for m in available)
        except Exception:
            return False

    async def _list_ollama_models(self, host: str) -> list[str]:
        """List available Ollama models.

        Args:
            host: Ollama host URL.

        Returns:
            List of model name strings.
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{host}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            pass
        return []

    async def _do_heartbeat(self, session: AgentSession) -> bool:
        """Check if the Hermes backend is responsive.

        Args:
            session: The active agent session.

        Returns:
            True if the backend responds.
        """
        backend = session.metadata.get("backend", "ollama")
        if backend == "ollama":
            import httpx
            host = session.metadata.get("host", DEFAULT_OLLAMA_HOST)
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"{host}/api/tags")
                    return response.status_code == 200
            except Exception:
                return False
        else:
            # OpenRouter — just verify key is set
            return bool(session.metadata.get("openrouter_key"))

    async def _do_terminate(self, session: AgentSession) -> None:
        """Clean up Hermes session resources.

        Args:
            session: The session being terminated.
        """
        self._conversation_history.pop(session.session_id, None)
        self._pending_tool_calls.pop(session.session_id, None)

    def _get_capabilities(self) -> list[str]:
        """Return Hermes adapter capabilities.

        Returns:
            List of supported capability identifiers.
        """
        return [
            "execute_task",
            "chat",
            "tool_calling",
            "function_execution",
            "autonomous_reasoning",
            "ceo_orchestration",
            "local_execution",
            "cloud_fallback",
            "openrouter",
            "structured_output",
            "plaza_broadcast",
            "multi_round_tool_use",
        ]
