"""AWS Bedrock Adapter - implements AgentAdapter Protocol for AWS Bedrock models.

Supports Anthropic Claude models and Amazon Titan on AWS Bedrock.
Uses async httpx with AWS Signature V4 authentication for API communication
and retry logic for rate limits.
"""

import asyncio
import datetime as dt
import hashlib
import hmac
import uuid
from typing import Any
from urllib.parse import quote

from nexus.adapters.base import BaseAdapter
from nexus.runtime.adapter import AgentSession, TaskResult


# Per-model pricing in cents per 1K tokens (input, output)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "anthropic.claude-3-5-sonnet": (0.3, 1.5),
    "anthropic.claude-3-haiku": (0.025, 0.125),
    "amazon.titan-text-express": (0.02, 0.06),
}

# Default max retries for rate limit errors
MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 1.0

# Maximum number of messages to retain in conversation history per session
MAX_HISTORY_MESSAGES = 50


class BedrockAdapter(BaseAdapter):
    """Agent adapter for AWS Bedrock models.

    Implements the full AgentAdapter Protocol using async httpx to
    communicate with the AWS Bedrock InvokeModel endpoint. Signs requests
    using AWS Signature V4.
    """

    adapter_type: str = "bedrock"

    def __init__(self) -> None:
        """Initialize the Bedrock adapter."""
        super().__init__()

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate that required AWS Bedrock configuration keys are present.

        Args:
            config: Configuration dictionary.

        Raises:
            ValueError: If required keys are missing.
        """
        if "aws_access_key_id" not in config:
            raise ValueError("Bedrock adapter requires 'aws_access_key_id' in config")
        if "aws_secret_access_key" not in config:
            raise ValueError("Bedrock adapter requires 'aws_secret_access_key' in config")
        if "region" not in config:
            raise ValueError("Bedrock adapter requires 'region' in config")
        if "model" not in config:
            raise ValueError("Bedrock adapter requires 'model' in config")

    async def _do_create_session(self, session: AgentSession) -> None:
        """Initialize Bedrock session with conversation history.

        Sets up the system prompt from agent config if provided.

        Args:
            session: The newly created session.
        """
        system_prompt = session.config.get("system_prompt", "")
        if system_prompt:
            session.metadata["system_prompt"] = system_prompt

    async def _do_execute(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        """Execute a task via AWS Bedrock InvokeModel API.

        Sends the task using the Anthropic Claude message format on Bedrock.
        Signs the request with AWS Signature V4 and applies retry with
        exponential backoff on rate limit (429) responses.

        Args:
            session: The active agent session.
            task_id: The task identifier.
            payload: Must contain 'prompt'. Optionally 'temperature', 'max_tokens'.

        Returns:
            TaskResult with the model's response and usage metrics.
        """
        import httpx

        prompt = payload.get("prompt", "")
        max_tokens = payload.get("max_tokens", 4096)

        aws_access_key_id = session.config["aws_access_key_id"]
        aws_secret_access_key = session.config["aws_secret_access_key"]
        region = session.config["region"]
        model = session.config["model"]

        # Build conversation messages
        history = self._conversation_history.get(session.session_id, [])
        history.append({"role": "user", "content": prompt})

        # Build request body (Anthropic Claude format on Bedrock)
        request_body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": history,
            "max_tokens": max_tokens,
        }

        # Add system prompt if configured
        system_prompt = session.metadata.get("system_prompt", "")
        if system_prompt:
            request_body["system"] = system_prompt

        host = f"bedrock-runtime.{region}.amazonaws.com"
        path = f"/model/{quote(model, safe='')}/invoke"
        url = f"https://{host}{path}"

        import json
        body_bytes = json.dumps(request_body).encode("utf-8")

        # Retry with exponential backoff on rate limits
        response_data: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=120.0) as client:
            for attempt in range(MAX_RETRIES):
                # Sign the request with AWS Signature V4
                headers = self._sign_request(
                    method="POST",
                    host=host,
                    path=path,
                    body=body_bytes,
                    region=region,
                    service="bedrock",
                    access_key=aws_access_key_id,
                    secret_key=aws_secret_access_key,
                )
                headers["Content-Type"] = "application/json"
                headers["Accept"] = "application/json"

                response = await client.post(
                    url,
                    content=body_bytes,
                    headers=headers,
                )

                if response.status_code == 429:
                    wait_time = BASE_BACKOFF_SECONDS * (2**attempt)
                    self._add_log(
                        session.session_id,
                        f"Rate limited (429), retrying in {wait_time}s "
                        f"(attempt {attempt + 1}/{MAX_RETRIES})",
                    )
                    await asyncio.sleep(wait_time)
                    continue

                if response.status_code != 200:
                    error_text = response.text
                    return TaskResult(
                        task_id=task_id,
                        agent_id=session.agent_id,
                        success=False,
                        error=f"Bedrock API error {response.status_code}: {error_text}",
                    )

                response_data = response.json()
                break
            else:
                return TaskResult(
                    task_id=task_id,
                    agent_id=session.agent_id,
                    success=False,
                    error="Max retries exceeded due to rate limiting",
                )

        # Parse response (Anthropic Claude format)
        content_blocks = response_data.get("content", [])
        output_content = ""
        for block in content_blocks:
            if block.get("type") == "text":
                output_content += block.get("text", "")

        usage = response_data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        # Calculate cost
        pricing = MODEL_PRICING.get(model, (0.3, 1.5))
        cost_cents = round(
            (input_tokens / 1000 * pricing[0])
            + (output_tokens / 1000 * pricing[1])
        )

        # Add assistant response to history
        history.append({"role": "assistant", "content": output_content})
        # Cap conversation history to prevent unbounded growth
        if len(history) > MAX_HISTORY_MESSAGES:
            history = history[-MAX_HISTORY_MESSAGES:]
        self._conversation_history[session.session_id] = history

        return TaskResult(
            task_id=task_id,
            agent_id=session.agent_id,
            success=True,
            output=output_content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=cost_cents,
            artifacts=[],
            logs=[f"Model: {model}, Tokens: {input_tokens}+{output_tokens}"],
        )

    async def _do_heartbeat(self, session: AgentSession) -> bool:
        """Verify Bedrock session is alive.

        Args:
            session: The active agent session.

        Returns:
            True (Bedrock sessions are stateless, always alive).
        """
        return True

    async def _do_terminate(self, session: AgentSession) -> None:
        """Clean up Bedrock session resources.

        Args:
            session: The session being terminated.
        """
        self._conversation_history.pop(session.session_id, None)

    def _get_capabilities(self) -> list[str]:
        """Return Bedrock adapter capabilities.

        Returns:
            List of supported capability identifiers.
        """
        return [
            "execute_task",
            "conversation_history",
            "system_prompt",
            "retry_on_rate_limit",
        ]

    @staticmethod
    def _sign_request(
        method: str,
        host: str,
        path: str,
        body: bytes,
        region: str,
        service: str,
        access_key: str,
        secret_key: str,
    ) -> dict[str, str]:
        """Sign an HTTP request using AWS Signature Version 4.

        Implements the AWS SigV4 signing process for authenticating
        requests to AWS services.

        Args:
            method: HTTP method (e.g., "POST").
            host: The target host (e.g., "bedrock-runtime.us-east-1.amazonaws.com").
            path: The request path (e.g., "/model/anthropic.claude-3/invoke").
            body: The request body as bytes.
            region: AWS region (e.g., "us-east-1").
            service: AWS service name (e.g., "bedrock").
            access_key: AWS access key ID.
            secret_key: AWS secret access key.

        Returns:
            Dictionary of headers including Authorization and other required headers.
        """
        now = dt.datetime.now(dt.timezone.utc)
        datestamp = now.strftime("%Y%m%d")
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")

        # Step 1: Create canonical request
        content_hash = hashlib.sha256(body).hexdigest()
        canonical_headers = f"host:{host}\nx-amz-content-sha256:{content_hash}\nx-amz-date:{amz_date}\n"
        signed_headers = "host;x-amz-content-sha256;x-amz-date"

        canonical_request = "\n".join([
            method,
            path,
            "",  # query string (empty)
            canonical_headers,
            signed_headers,
            content_hash,
        ])

        # Step 2: Create string to sign
        credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ])

        # Step 3: Calculate signature
        def _sign(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        signing_key = _sign(
            _sign(
                _sign(
                    _sign(f"AWS4{secret_key}".encode("utf-8"), datestamp),
                    region,
                ),
                service,
            ),
            "aws4_request",
        )
        # Use hmac.new for final signature
        signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        # Step 4: Build authorization header
        authorization = (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        return {
            "Authorization": authorization,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": content_hash,
            "Host": host,
        }
