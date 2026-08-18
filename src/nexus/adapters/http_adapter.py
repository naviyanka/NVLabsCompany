"""HTTP Agent Adapter - implements AgentAdapter Protocol for generic HTTP endpoints.

Calls any HTTP endpoint that conforms to the NEXUS agent API.
Supports configurable request/response mapping, authentication,
webhook-based async result delivery, and health check polling.
"""

import uuid
from typing import Any

from nexus.adapters.base import BaseAdapter
from nexus.runtime.adapter import AgentSession, TaskResult


class HTTPAdapter(BaseAdapter):
    """Agent adapter for generic HTTP agent endpoints.

    Implements the full AgentAdapter Protocol by making HTTP requests
    to external agent services. Supports Bearer token and API key
    authentication, configurable payload transformation, webhook-based
    async results, and health check polling.
    """

    adapter_type: str = "http"

    def __init__(self) -> None:
        """Initialize the HTTP adapter."""
        super().__init__()

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate that required HTTP configuration keys are present.

        Args:
            config: Configuration dictionary.

        Raises:
            ValueError: If 'base_url' is missing.
        """
        if "base_url" not in config:
            raise ValueError("HTTP adapter requires 'base_url' in config")

    async def _do_create_session(self, session: AgentSession) -> None:
        """Initialize HTTP session with endpoint configuration.

        Args:
            session: The newly created session.
        """
        base_url = session.config["base_url"].rstrip("/")
        session.metadata["base_url"] = base_url
        session.metadata["_headers"] = self._build_headers(session.config)
        session.metadata["timeout"] = session.config.get("timeout", 60.0)

        # Configurable endpoint paths
        session.metadata["execute_path"] = session.config.get(
            "execute_path", "/execute"
        )
        session.metadata["status_path"] = session.config.get(
            "status_path", "/status"
        )
        session.metadata["health_path"] = session.config.get(
            "health_path", "/health"
        )

        # Response field mapping (jmespath-style)
        session.metadata["response_mapping"] = session.config.get(
            "response_mapping",
            {
                "output": "output",
                "success": "success",
                "error": "error",
                "input_tokens": "usage.input_tokens",
                "output_tokens": "usage.output_tokens",
                "cost_cents": "cost_cents",
                "artifacts": "artifacts",
            },
        )

        # Webhook configuration for async results
        session.metadata["webhook_url"] = session.config.get("webhook_url")
        session.metadata["poll_interval"] = session.config.get(
            "poll_interval", 2.0
        )

    def _build_headers(self, config: dict[str, Any]) -> dict[str, str]:
        """Build request headers from configuration.

        Supports Bearer token, API key, and custom headers.

        Args:
            config: Session configuration.

        Returns:
            Dictionary of HTTP headers.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }

        # Bearer token authentication
        if "bearer_token" in config:
            headers["Authorization"] = f"Bearer {config['bearer_token']}"
        elif "api_key" in config:
            # API key in header
            api_key_header = config.get("api_key_header", "X-API-Key")
            headers[api_key_header] = config["api_key"]

        # Custom headers
        custom_headers = config.get("headers", {})
        headers.update(custom_headers)

        return headers

    async def _do_execute(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        """Execute a task via HTTP request to the configured endpoint.

        Args:
            session: The active agent session.
            task_id: The task identifier.
            payload: Task parameters to send in the request body.

        Returns:
            TaskResult with the mapped response data.
        """
        import httpx

        base_url = session.metadata["base_url"]
        headers = session.metadata["_headers"]
        timeout = session.metadata["timeout"]
        execute_path = session.metadata["execute_path"]
        response_mapping = session.metadata["response_mapping"]

        # Build request body with payload transformation
        request_body = self._transform_request(session, task_id, payload)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{base_url}{execute_path}",
                    json=request_body,
                    headers=headers,
                )

            if response.status_code not in (200, 201, 202):
                return TaskResult(
                    task_id=task_id,
                    agent_id=session.agent_id,
                    success=False,
                    error=f"HTTP error {response.status_code}: {response.text}",
                )

            response_data = response.json()

            # Handle async/webhook response (202 Accepted)
            if response.status_code == 202:
                # Poll for result
                poll_url = response_data.get("poll_url") or response_data.get(
                    "status_url"
                )
                if poll_url:
                    response_data = await self._poll_for_result(
                        session, poll_url
                    )

            # Map response fields
            output = self._extract_field(
                response_data, response_mapping.get("output", "output")
            )
            success = self._extract_field(
                response_data, response_mapping.get("success", "success")
            )
            error = self._extract_field(
                response_data, response_mapping.get("error", "error")
            )
            input_tokens = self._extract_field(
                response_data,
                response_mapping.get("input_tokens", "usage.input_tokens"),
            ) or 0
            output_tokens = self._extract_field(
                response_data,
                response_mapping.get("output_tokens", "usage.output_tokens"),
            ) or 0
            cost_cents = self._extract_field(
                response_data, response_mapping.get("cost_cents", "cost_cents")
            ) or 0
            artifacts = self._extract_field(
                response_data, response_mapping.get("artifacts", "artifacts")
            ) or []

            if success is None:
                success = True

            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=bool(success),
                output=output,
                error=error if not success else None,
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
                cost_cents=int(cost_cents),
                artifacts=artifacts if isinstance(artifacts, list) else [],
                logs=[f"Endpoint: {base_url}{execute_path}"],
            )

        except Exception as e:
            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=False,
                error=f"HTTP request failed: {type(e).__name__}: {e}",
            )

    async def _poll_for_result(
        self, session: AgentSession, poll_url: str
    ) -> dict[str, Any]:
        """Poll a URL until a result is available.

        Reuses a single httpx.AsyncClient across all poll iterations
        to avoid creating a new TCP connection for each request.

        Args:
            session: The active agent session.
            poll_url: The URL to poll for results.

        Returns:
            The final response data.
        """
        import asyncio

        import httpx

        headers = session.metadata["_headers"]
        poll_interval = session.metadata["poll_interval"]
        timeout = session.metadata["timeout"]
        max_polls = int(timeout / poll_interval)

        async with httpx.AsyncClient(timeout=30.0) as client:
            for _ in range(max_polls):
                await asyncio.sleep(poll_interval)
                try:
                    response = await client.get(poll_url, headers=headers)
                    if response.status_code == 200:
                        data = response.json()
                        status = data.get("status", "")
                        if status in ("completed", "done", "finished", "error"):
                            return data
                except Exception:
                    continue

        return {"success": False, "error": "Polling timed out"}

    def _transform_request(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Transform the task payload into the expected request format.

        Args:
            session: The active agent session.
            task_id: The task identifier.
            payload: Original task payload.

        Returns:
            Transformed request body.
        """
        # Allow custom request mapping from config
        request_mapping = session.config.get("request_mapping", None)
        if request_mapping:
            transformed: dict[str, Any] = {}
            for target_field, source_field in request_mapping.items():
                if source_field == "__task_id__":
                    transformed[target_field] = str(task_id)
                elif source_field == "__session_id__":
                    transformed[target_field] = session.session_id
                elif source_field in payload:
                    transformed[target_field] = payload[source_field]
            return transformed

        # Default: pass payload as-is with metadata
        return {
            "task_id": str(task_id),
            "session_id": session.session_id,
            "agent_id": str(session.agent_id),
            **payload,
        }

    def _extract_field(
        self, data: dict[str, Any], path: str
    ) -> Any:
        """Extract a field from nested data using dot-notation path.

        Args:
            data: The response data dictionary.
            path: Dot-separated field path (e.g., 'usage.input_tokens').

        Returns:
            The extracted value, or None if not found.
        """
        parts = path.split(".")
        current: Any = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    async def _do_heartbeat(self, session: AgentSession) -> bool:
        """Check health of the HTTP endpoint.

        Args:
            session: The active agent session.

        Returns:
            True if the health endpoint responds with 200.
        """
        import httpx

        base_url = session.metadata["base_url"]
        health_path = session.metadata["health_path"]
        headers = session.metadata["_headers"]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{base_url}{health_path}", headers=headers
                )
                return response.status_code == 200
        except Exception:
            return False

    async def _do_terminate(self, session: AgentSession) -> None:
        """Clean up HTTP session resources.

        Args:
            session: The session being terminated.
        """
        self._conversation_history.pop(session.session_id, None)

    def _get_capabilities(self) -> list[str]:
        """Return HTTP adapter capabilities.

        Returns:
            List of supported capability identifiers.
        """
        return [
            "execute_task",
            "configurable_endpoints",
            "bearer_auth",
            "api_key_auth",
            "custom_headers",
            "webhook_polling",
            "health_check",
            "payload_transformation",
            "response_mapping",
        ]
