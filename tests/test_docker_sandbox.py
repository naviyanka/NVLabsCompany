"""Tests for DockerSandbox (nexus.evolution.isolated_sandbox.DockerSandbox)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.evolution.isolated_sandbox import DockerSandbox, IsolatedSandbox


class TestDockerSandboxDetection:
    """Tests for Docker detection logic."""

    def test_detects_docker_when_available(self) -> None:
        """Test that Docker is detected when binary is in PATH."""
        with patch("shutil.which", return_value="/usr/bin/docker"):
            sandbox = DockerSandbox()
            assert sandbox.docker_available is True

    def test_detects_docker_not_available(self) -> None:
        """Test that Docker absence is detected."""
        with patch("shutil.which", return_value=None):
            sandbox = DockerSandbox()
            assert sandbox.docker_available is False

    def test_custom_parameters(self) -> None:
        """Test custom initialization parameters."""
        with patch("shutil.which", return_value=None):
            sandbox = DockerSandbox(
                max_memory_mb=1024,
                max_cpus=2.0,
                timeout_seconds=600,
                docker_image="node:18-slim",
            )
            assert sandbox.max_memory_mb == 1024
            assert sandbox.max_cpus == 2.0
            assert sandbox.timeout_seconds == 600
            assert sandbox.docker_image == "node:18-slim"


class TestDockerSandboxFallback:
    """Tests for fallback behavior when Docker is unavailable."""

    async def test_falls_back_to_isolated_sandbox(self) -> None:
        """Test that execution falls back when Docker is unavailable."""
        with patch("shutil.which", return_value=None):
            sandbox = DockerSandbox()
            result = await sandbox.run("print('hello')", language="python")

            assert result["docker_used"] is False
            assert result["exit_code"] == 0
            assert result["timed_out"] is False

    async def test_fallback_returns_stdout(self) -> None:
        """Test that fallback returns some stdout content."""
        with patch("shutil.which", return_value=None):
            sandbox = DockerSandbox()
            result = await sandbox.run("x = 1 + 1", language="python")

            assert result["docker_used"] is False
            assert "stdout" in result


class TestDockerSandboxExecution:
    """Tests for Docker execution with mocked subprocess."""

    async def test_successful_docker_run(self) -> None:
        """Test successful execution in Docker container."""
        with patch("shutil.which", return_value="/usr/bin/docker"):
            sandbox = DockerSandbox()

            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(
                return_value=(b"Hello World\n", b"")
            )
            mock_process.returncode = 0

            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ):
                result = await sandbox.run("print('Hello World')")

                assert result["docker_used"] is True
                assert result["stdout"] == "Hello World\n"
                assert result["stderr"] == ""
                assert result["exit_code"] == 0
                assert result["timed_out"] is False

    async def test_docker_run_with_stderr(self) -> None:
        """Test Docker execution that produces stderr."""
        with patch("shutil.which", return_value="/usr/bin/docker"):
            sandbox = DockerSandbox()

            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(
                return_value=(b"", b"Error: something went wrong\n")
            )
            mock_process.returncode = 1

            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ):
                result = await sandbox.run("invalid code")

                assert result["docker_used"] is True
                assert result["exit_code"] == 1
                assert "Error" in result["stderr"]

    async def test_docker_run_timeout(self) -> None:
        """Test Docker execution that times out."""
        with patch("shutil.which", return_value="/usr/bin/docker"):
            sandbox = DockerSandbox(timeout_seconds=1)

            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(
                side_effect=asyncio.TimeoutError()
            )
            mock_process.kill = MagicMock()
            mock_process.wait = AsyncMock()

            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ):
                result = await sandbox.run("import time; time.sleep(100)")

                assert result["docker_used"] is True
                assert result["timed_out"] is True
                assert result["exit_code"] == -1

    async def test_docker_run_with_env_vars(self) -> None:
        """Test Docker execution with environment variables."""
        with patch("shutil.which", return_value="/usr/bin/docker"):
            sandbox = DockerSandbox()

            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(
                return_value=(b"output\n", b"")
            )
            mock_process.returncode = 0

            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ) as mock_exec:
                result = await sandbox.run(
                    "print('hello')",
                    env={"MY_VAR": "my_value"},
                )

                # Verify env vars were passed
                call_args = mock_exec.call_args[0]
                assert "-e" in call_args
                assert "MY_VAR=my_value" in call_args
                assert result["docker_used"] is True

    async def test_docker_oserror_falls_back(self) -> None:
        """Test that OSError during docker exec triggers fallback."""
        with patch("shutil.which", return_value="/usr/bin/docker"):
            sandbox = DockerSandbox()

            with patch(
                "asyncio.create_subprocess_exec",
                side_effect=OSError("Docker not running"),
            ):
                result = await sandbox.run("print('hello')")

                assert result["docker_used"] is False
                assert sandbox.docker_available is False

    async def test_docker_command_includes_resource_limits(self) -> None:
        """Test that docker command includes memory and CPU limits."""
        with patch("shutil.which", return_value="/usr/bin/docker"):
            sandbox = DockerSandbox(max_memory_mb=256, max_cpus=0.5)

            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(
                return_value=(b"ok\n", b"")
            )
            mock_process.returncode = 0

            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ) as mock_exec:
                await sandbox.run("print('ok')")

                call_args = mock_exec.call_args[0]
                assert "--memory=256m" in call_args
                assert "--cpus=0.5" in call_args
                assert "--network=none" in call_args
                assert "--read-only" in call_args
