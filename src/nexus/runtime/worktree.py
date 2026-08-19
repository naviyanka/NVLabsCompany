"""Worktree Isolation - git worktree management for parallel agent execution.

Manages git worktrees to provide file-system isolation between concurrently
executing agents. Each agent gets its own worktree with a dedicated branch,
preventing file conflicts during parallel operations.

Supports creation, merging, syncing, change detection, removal, and revert
operations against git worktrees using async subprocess calls.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class MergeResult:
    """Result of merging a worktree branch into the main repository.

    Attributes:
        success: Whether the merge completed without conflicts.
        conflicts: List of file paths that had merge conflicts.
        merge_commit: The merge commit hash if successful, None otherwise.
    """

    success: bool
    conflicts: list[str]
    merge_commit: str | None


@dataclass
class WorktreeInfo:
    """Information about a created worktree.

    Attributes:
        worktree_path: Absolute path to the worktree directory.
        branch: Name of the branch associated with this worktree.
        agent_id: UUID of the agent that owns this worktree.
        agent_name: Human-readable name of the owning agent.
        created_at: Timestamp when the worktree was created.
    """

    worktree_path: str
    branch: str
    agent_id: uuid.UUID
    agent_name: str
    created_at: datetime


class WorktreeManager:
    """Manages git worktrees for agent isolation using subprocess calls to git.

    Provides async methods for creating, merging, syncing, inspecting, removing,
    and reverting worktrees. Each worktree gets a branch named using the pattern
    agent/<agent_name>-<short_id> and is placed in a sibling directory to the
    repository root.
    """

    def __init__(self) -> None:
        """Initialize the WorktreeManager."""

    async def create_worktree(
        self, repo_path: str, agent_id: uuid.UUID, agent_name: str
    ) -> WorktreeInfo:
        """Create a new git worktree for an agent.

        Creates a branch named agent/<agent_name>-<short_id> and a worktree
        at <repo_path>/../worktrees/<agent_name>-<short_id>.

        Args:
            repo_path: Path to the main git repository.
            agent_id: UUID of the agent requesting the worktree.
            agent_name: Human-readable name of the agent.

        Returns:
            WorktreeInfo describing the created worktree.

        Raises:
            RuntimeError: If the git worktree creation fails.
        """
        short_id = str(agent_id)[:8]
        branch = f"agent/{agent_name}-{short_id}"
        worktree_dir = str(
            Path(repo_path).parent / "worktrees" / f"{agent_name}-{short_id}"
        )

        # Create branch from current HEAD
        await self._run_git(repo_path, "branch", branch)

        # Create worktree
        await self._run_git(repo_path, "worktree", "add", worktree_dir, branch)

        return WorktreeInfo(
            worktree_path=worktree_dir,
            branch=branch,
            agent_id=agent_id,
            agent_name=agent_name,
            created_at=datetime.now(timezone.utc),
        )

    async def merge_worktree(
        self, repo_path: str, worktree_path: str, branch: str
    ) -> MergeResult:
        """Merge a worktree branch into the current branch of repo_path.

        Attempts a git merge and returns the result. If there are conflicts,
        the merge is aborted and the conflict file list is returned.

        Args:
            repo_path: Path to the main git repository.
            worktree_path: Path to the worktree directory (unused but kept
                for API consistency).
            branch: Name of the branch to merge.

        Returns:
            MergeResult indicating success or listing conflicts.
        """
        returncode, stdout, stderr = await self._run_git_raw(
            repo_path, "merge", branch, "--no-edit"
        )

        if returncode == 0:
            # Get the merge commit hash
            _, commit_hash, _ = await self._run_git_raw(
                repo_path, "rev-parse", "HEAD"
            )
            return MergeResult(
                success=True,
                conflicts=[],
                merge_commit=commit_hash.strip(),
            )

        # Merge failed - check for conflicts
        _, status_output, _ = await self._run_git_raw(
            repo_path, "diff", "--name-only", "--diff-filter=U"
        )
        conflicts = [
            line.strip()
            for line in status_output.strip().splitlines()
            if line.strip()
        ]

        # Abort the failed merge
        await self._run_git_raw(repo_path, "merge", "--abort")

        return MergeResult(
            success=False,
            conflicts=conflicts,
            merge_commit=None,
        )

    async def sync_worktree_to_main(
        self, repo_path: str, worktree_path: str, main_branch: str = "main"
    ) -> None:
        """Pull latest main branch changes into the worktree branch via merge.

        Fetches the latest state of the main branch and merges it into the
        worktree's current branch.

        Args:
            repo_path: Path to the main git repository (used to reference
                the main branch).
            worktree_path: Path to the worktree directory.
            main_branch: Name of the main branch to sync from.

        Raises:
            RuntimeError: If the merge fails.
        """
        await self._run_git(worktree_path, "merge", main_branch)

    async def has_pending_changes(
        self, repo_path: str, worktree_path: str
    ) -> bool:
        """Check if the worktree has uncommitted or unmerged work.

        Uses git status to detect modified, added, or untracked files.

        Args:
            repo_path: Path to the main git repository (unused but kept
                for API consistency).
            worktree_path: Path to the worktree directory to check.

        Returns:
            True if there are pending changes, False otherwise.
        """
        _, stdout, _ = await self._run_git_raw(
            worktree_path, "status", "--porcelain"
        )
        return bool(stdout.strip())

    async def remove_worktree(
        self, worktree_path: str, branch: str, repo_path: str
    ) -> bool:
        """Remove a worktree and delete its associated branch.

        Args:
            worktree_path: Path to the worktree directory to remove.
            branch: Name of the branch to delete.
            repo_path: Path to the main git repository.

        Returns:
            True if removal was successful, False otherwise.
        """
        # Remove the worktree
        returncode, _, _ = await self._run_git_raw(
            repo_path, "worktree", "remove", worktree_path, "--force"
        )
        if returncode != 0:
            return False

        # Delete the branch
        returncode, _, _ = await self._run_git_raw(
            repo_path, "branch", "-D", branch
        )
        return returncode == 0

    async def revert_worktree_commit(
        self, repo_path: str, worktree_path: str
    ) -> bool:
        """Revert the last commit in the worktree.

        Args:
            repo_path: Path to the main git repository (unused but kept
                for API consistency).
            worktree_path: Path to the worktree directory.

        Returns:
            True if the revert was successful, False otherwise.
        """
        returncode, _, _ = await self._run_git_raw(
            worktree_path, "revert", "HEAD", "--no-edit"
        )
        return returncode == 0

    async def _run_git(self, cwd: str, *args: str) -> str:
        """Run a git command and return stdout, raising on failure.

        Args:
            cwd: Working directory for the git command.
            *args: Git subcommand and arguments.

        Returns:
            The stdout output of the command.

        Raises:
            RuntimeError: If the command exits with a non-zero status.
        """
        returncode, stdout, stderr = await self._run_git_raw(cwd, *args)
        if returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed (rc={returncode}): {stderr}"
            )
        return stdout

    async def _run_git_raw(
        self, cwd: str, *args: str
    ) -> tuple[int, str, str]:
        """Run a git command and return (returncode, stdout, stderr).

        Args:
            cwd: Working directory for the git command.
            *args: Git subcommand and arguments.

        Returns:
            Tuple of (return_code, stdout_text, stderr_text).
        """
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout_bytes.decode(),
            stderr_bytes.decode(),
        )
