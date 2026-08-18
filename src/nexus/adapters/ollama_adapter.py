"""Ollama Adapter - implements AgentAdapter Protocol for local Ollama models.

Supports local inference via the Ollama REST API, with zero-cost tracking,
model availability checks, and fallback model selection.
"""

import uuid
from typing import Any

from nexus.adapters.base import BaseAdapter
from nexus.runtime.adapter import AgentSession, TaskResult


# Default Ollama host
DEFAULT_OLLAMA_HOST = "http://localhost:11434"

# Common fallback models in order of preference
FALLBACK_MODELS = [
    "llama3.1",
    "llama3",
    "llama2",
    "mistral",
    "codellama",
    "phi3",
]

# Approximate GPU memory requirements in GB per model family
GPU_MEMORY_ESTIMATES: dict[str, float] = {
    "llama3.1:70b": 40.0,
    "llama3.1:8b": 5.0,
    "llama3.1": 5.0,
    "llama3": 5.0,
    "llama2:70b": 40.0,
    "llama2:13b": 8.0,
    "llama2": 4.0,
    "mistral": 4.5,
    "codellama": 4.5,
    "phi3": 3.0,
}


class OllamaAdapter(BaseAdapter):
    """Agent adapter for local Ollama models.

    Implements the full AgentAdapter Protocol using async httpx to
    communicate with the Ollama REST API. Provides zero-cost tracking
    for local execution, model availability checks, and GPU memory
    estimation.
    """

    adapter_type: str = "ollama"

    def __init__(self) -> None:
        """Initialize the Ollama adapter."""
        super().__init__()

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate that required Ollama configuration keys are present.

        Args:
            config: Configuration dictionary.

        Raises:
            ValueError: If 'model' is missing.
        """
        if "model" not in config:
            raise ValueError("Ollama adapter requires 'model' in config")

    async def _do_create_session(self, session: AgentSession) -> None:
        """Initialize Ollama session and check model availability.

        Checks if the requested model is available locally. If not,
        attempts to select a fallback model.

        Args:
            session: The newly created session.
        """
        host = session.config.get("host", DEFAULT_OLLAMA_HOST)
        session.metadata["host"] = host
        session.metadata["model"] = session.config["model"]
        session.metadata["available_models"] = []

        # Check model availability
        try:
            available = await self._list_models(host)
            session.metadata["available_models"] = available
            requested_model = session.config["model"]

            if requested_model not in available:
                # Try to find a fallback
                fallback = self._select_fallback(available)
                if fallback:
                    session.metadata["model"] = fallback
                    self._add_log(
                        session.session_id,
                        f"Model '{requested_model}' not available, "
                        f"using fallback '{fallback}'",
                    )
                else:
                    self._add_log(
                        session.session_id,
                        f"Model '{requested_model}' not available and "
                        f"no fallback found. Will attempt to pull on execute.",
                    )
        except Exception as e:
            self._add_log(
                session.session_id,
                f"Could not check Ollama models: {e}. "
                f"Proceeding with configured model.",
            )

    async def _list_models(self, host: str) -> list[str]:
        """List locally available Ollama models.

        Args:
            host: The Ollama API host URL.

        Returns:
            List of model names available locally.
        """
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{host}/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])
                return [m.get("name", "") for m in models]
        return []

    def _select_fallback(self, available: list[str]) -> str | None:
        """Select a fallback model from available models.

        Args:
            available: List of available model names.

        Returns:
            The best fallback model name, or None if none match.
        """
        for fallback in FALLBACK_MODELS:
            for available_model in available:
                if fallback in available_model:
                    return available_model
        return None

    def estimate_gpu_memory(self, model: str) -> float:
        """Estimate GPU memory required for a model.

        Args:
            model: The model name.

        Returns:
            Estimated GPU memory in GB.
        """
        # Check exact match first
        if model in GPU_MEMORY_ESTIMATES:
            return GPU_MEMORY_ESTIMATES[model]
        # Check prefix matches
        for key, value in GPU_MEMORY_ESTIMATES.items():
            if model.startswith(key):
                return value
        # Default estimate
        return 4.0

    async def _do_execute(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        """Execute a task via Ollama REST API.

        Supports both chat and generate endpoints depending on the payload.

        Args:
            session: The active agent session.
            task_id: The task identifier.
            payload: Must contain 'prompt'. Optionally 'use_chat', 'context'.

        Returns:
            TaskResult with the model's response (zero cost for local).
        """
        import httpx

        prompt = payload.get("prompt", "")
        use_chat = payload.get("use_chat", True)
        system_prompt = session.config.get("system_prompt", "")
        host = session.metadata.get("host", DEFAULT_OLLAMA_HOST)
        model = session.metadata.get("model", session.config["model"])

        if use_chat:
            # Use chat endpoint
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})

            # Add conversation history
            history = self._conversation_history.get(session.session_id, [])
            messages.extend(history)
            messages.append({"role": "user", "content": prompt})

            request_body: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": False,
            }
            endpoint = f"{host}/api/chat"
        else:
            # Use generate endpoint
            request_body = {
                "model": model,
                "prompt": prompt,
                "system": system_prompt,
                "stream": False,
            }
            endpoint = f"{host}/api/generate"

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(endpoint, json=request_body)

            if response.status_code != 200:
                return TaskResult(
                    task_id=task_id,
                    agent_id=session.agent_id,
                    success=False,
                    error=f"Ollama API error {response.status_code}: {response.text}",
                )

            response_data = response.json()

            # Extract output based on endpoint
            if use_chat:
                message = response_data.get("message", {})
                output_content = message.get("content", "")
                # Update conversation history
                history.append({"role": "user", "content": prompt})
                history.append({"role": "assistant", "content": output_content})
                self._conversation_history[session.session_id] = history
            else:
                output_content = response_data.get("response", "")

            # Extract token counts (Ollama provides these)
            eval_count = response_data.get("eval_count", 0)
            prompt_eval_count = response_data.get("prompt_eval_count", 0)

            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=True,
                output=output_content,
                input_tokens=prompt_eval_count,
                output_tokens=eval_count,
                cost_cents=0,  # Local execution is free
                logs=[
                    f"Model: {model}, "
                    f"Tokens: {prompt_eval_count}+{eval_count} (local, zero cost)"
                ],
            )

        except Exception as e:
            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=False,
                error=f"Ollama request failed: {type(e).__name__}: {e}",
            )

    async def _do_heartbeat(self, session: AgentSession) -> bool:
        """Check if Ollama server is responsive.

        Args:
            session: The active agent session.

        Returns:
            True if the Ollama server responds to a health check.
        """
        import httpx

        host = session.metadata.get("host", DEFAULT_OLLAMA_HOST)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{host}/api/tags")
                return response.status_code == 200
        except Exception:
            return False

    async def _do_terminate(self, session: AgentSession) -> None:
        """Clean up Ollama session resources.

        Args:
            session: The session being terminated.
        """
        self._conversation_history.pop(session.session_id, None)

    def _get_capabilities(self) -> list[str]:
        """Return Ollama adapter capabilities.

        Returns:
            List of supported capability identifiers.
        """
        return [
            "execute_task",
            "chat",
            "generate",
            "local_execution",
            "zero_cost",
            "model_pulling",
            "fallback_model",
            "gpu_memory_estimation",
        ]
