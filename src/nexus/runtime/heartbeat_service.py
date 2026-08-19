"""Heartbeat Service - rich lifecycle management for heartbeat runs."""

import uuid
from datetime import datetime, timezone

from nexus.models.heartbeat_run import HeartbeatRun


class HeartbeatService:
    """In-memory service for creating, updating, and querying heartbeat runs.

    Maintains an in-memory store of HeartbeatRun instances. In production,
    this would be backed by a database, but the interface remains the same.
    """

    def __init__(self) -> None:
        """Initialize with empty in-memory storage."""
        self._runs: dict[uuid.UUID, HeartbeatRun] = {}

    def create_run(
        self,
        agent_id: uuid.UUID,
        process_pid: int | None = None,
        invocation_source: str = "on_demand",
        session_id_before: str | None = None,
        context_snapshot: dict | None = None,
    ) -> HeartbeatRun:
        """Create a new heartbeat run.

        Args:
            agent_id: The agent this run belongs to.
            process_pid: OS process ID, if available.
            invocation_source: How the run was triggered.
            session_id_before: Session ID at the start of the run.
            context_snapshot: Optional JSON-serializable context data.

        Returns:
            The newly created HeartbeatRun.
        """
        run = HeartbeatRun(
            agent_id=agent_id,
            process_pid=process_pid,
            invocation_source=invocation_source,
            session_id_before=session_id_before,
            context_snapshot=context_snapshot,
        )
        self._runs[run.id] = run
        return run

    def update_liveness(self, run_id: uuid.UUID, liveness_state: str) -> HeartbeatRun | None:
        """Update the liveness state of a run.

        Args:
            run_id: The run to update.
            liveness_state: New liveness state value.

        Returns:
            The updated HeartbeatRun, or None if not found.
        """
        run = self._runs.get(run_id)
        if run is None:
            return None
        run.liveness_state = liveness_state
        return run

    def record_output(
        self,
        run_id: uuid.UUID,
        stdout_excerpt: str | None = None,
        stderr_excerpt: str | None = None,
    ) -> HeartbeatRun | None:
        """Record output excerpts for a run.

        Truncates stdout_excerpt and stderr_excerpt to 2000 characters.
        Updates last_output_at timestamp.

        Args:
            run_id: The run to update.
            stdout_excerpt: Standard output excerpt (truncated to 2000 chars).
            stderr_excerpt: Standard error excerpt (truncated to 2000 chars).

        Returns:
            The updated HeartbeatRun, or None if not found.
        """
        run = self._runs.get(run_id)
        if run is None:
            return None
        if stdout_excerpt is not None:
            run.stdout_excerpt = stdout_excerpt[:2000]
        if stderr_excerpt is not None:
            run.stderr_excerpt = stderr_excerpt[:2000]
        run.last_output_at = datetime.now(timezone.utc)
        return run

    def finish_run(
        self,
        run_id: uuid.UUID,
        exit_code: int | None = None,
        signal: str | None = None,
        session_id_after: str | None = None,
    ) -> HeartbeatRun | None:
        """Mark a run as finished.

        Sets finished_at timestamp. If exit_code is non-zero or signal is set,
        marks liveness_state as confirmed_dead.

        Args:
            run_id: The run to finish.
            exit_code: Process exit code.
            signal: Signal that terminated the process.
            session_id_after: Session ID after the run completed.

        Returns:
            The updated HeartbeatRun, or None if not found.
        """
        run = self._runs.get(run_id)
        if run is None:
            return None
        run.exit_code = exit_code
        run.signal = signal
        run.session_id_after = session_id_after
        run.finished_at = datetime.now(timezone.utc)
        if (exit_code is not None and exit_code != 0) or signal is not None:
            run.liveness_state = "confirmed_dead"
        return run

    def get_active_runs(self, agent_id: uuid.UUID) -> list[HeartbeatRun]:
        """Get all active (unfinished) runs for an agent.

        Args:
            agent_id: The agent to filter by.

        Returns:
            List of HeartbeatRun instances where finished_at is None.
        """
        return [
            run
            for run in self._runs.values()
            if run.agent_id == agent_id and run.finished_at is None
        ]

    def get_latest_run(self, agent_id: uuid.UUID) -> HeartbeatRun | None:
        """Get the most recent run for an agent by started_at.

        Args:
            agent_id: The agent to look up.

        Returns:
            The most recent HeartbeatRun, or None if no runs exist for this agent.
        """
        agent_runs = [run for run in self._runs.values() if run.agent_id == agent_id]
        if not agent_runs:
            return None
        return max(agent_runs, key=lambda r: r.started_at)

    def increment_continuation(self, run_id: uuid.UUID) -> HeartbeatRun | None:
        """Increment the continuation attempt counter for a run.

        Args:
            run_id: The run to update.

        Returns:
            The updated HeartbeatRun, or None if not found.
        """
        run = self._runs.get(run_id)
        if run is None:
            return None
        run.continuation_attempt += 1
        return run

    def detect_stale(self, threshold_seconds: int = 60) -> list[HeartbeatRun]:
        """Detect active runs that have gone stale.

        A run is stale if its last_output_at (or started_at if no output yet)
        is older than threshold_seconds ago.

        Args:
            threshold_seconds: Number of seconds without activity before
                a run is considered stale.

        Returns:
            List of stale HeartbeatRun instances.
        """
        now = datetime.now(timezone.utc)
        stale: list[HeartbeatRun] = []
        for run in self._runs.values():
            if run.finished_at is not None:
                continue
            reference_time = run.last_output_at if run.last_output_at is not None else run.started_at
            elapsed = (now - reference_time).total_seconds()
            if elapsed > threshold_seconds:
                stale.append(run)
        return stale
