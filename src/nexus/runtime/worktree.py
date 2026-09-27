"""Worktree Isolation - git worktree management for parallel agent execution.

Manages git worktrees to provide file-system isolation between concurrently
executing agents. Each agent gets its own worktree with a dedicated branch,
preventing file conflicts during parallel operations.

Supports creation, merging, syncing, change detection, removal, and revert
operations. Every git call goes through ``nexus.runtime.git_runner``.

Deprecated: no server path uses this module. Agent worktrees are owned by
``nexus.services.worktree_service.WorktreeService`` (tenant-scoped, audited,
approval-gated). It is kept only for its existing tests and the public
``nexus.runtime`` export; do not add new callers.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nexus.runtime.git_runner import GitError, GitRunner


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
    """Manages git worktrees for agent isolation.

    Provides async methods for creating, merging, syncing, inspecting, removing,
    and reverting worktrees. Each worktree gets a branch named using the pattern
    agent/<agent_name>-<short_id> and is placed in a sibling directory to the
    repository root. Git failures raise ``GitError``, a ``RuntimeError``.
    """

    def __init__(self) -> None:
        """Initialize the WorktreeManager."""

    @staticmethod
    def _slug(agent_name: str) -> str:
        """Reduce an agent name to characters safe in a branch and directory name."""
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", agent_name)
        slug = re.sub(r"\.{2,}", ".", slug).strip(".-")
        return slug[:64] or "agent"

    async def create_worktree(
        self, repo_path: str, agent_id: uuid.UUID, agent_name: str
    ) -> WorktreeInfo:
        """Create a new git worktree for an agent.

        Creates a branch named agent/<slug>-<short_id> and a worktree at
        <repo_path>/../worktrees/<slug>-<short_id>, where <slug> is the agent
        name reduced to letters, digits, '.', '_' and '-'.

        Raises:
            GitError: If the branch or worktree cannot be created.
        """
        short_id = str(agent_id)[:8]
        name = f"{self._slug(agent_name)}-{short_id}"
        branch = f"agent/{name}"
        repo = Path(repo_path).absolute()
        worktree_dir = repo.parent / "worktrees" / name
        runner = GitRunner(repo)

        await runner.create_branch(branch)
        try:
            await runner.add_worktree(worktree_dir, branch)
        except GitError:
            # Clean up the orphaned branch before re-raising
            try:
                await runner.delete_branch(branch, force=True)
            except GitError:
                pass
            raise

        return WorktreeInfo(
            worktree_path=str(worktree_dir),
            branch=branch,
            agent_id=agent_id,
            agent_name=agent_name,
            created_at=datetime.now(timezone.utc),
        )

    async def merge_worktree(
        self, repo_path: str, worktree_path: str, branch: str
    ) -> MergeResult:
        """Merge a worktree branch into the checked-out branch of repo_path.

        The merge is computed with merge-tree and commit-tree, so a conflict
        leaves the main checkout untouched. A clean merge is then applied with
        a fast-forward, which refuses rather than overwrite local edits.

        This is the legacy CLI auto-merge path. It still moves the main
        checkout; server-side merges should use ``GitRunner.merge_into``.
        """
        # ponytail: legacy path kept for CLIAdapter; replace once worktree merges go through the service.
        try:
            runner = GitRunner(Path(repo_path).absolute())
            head = await runner.resolve_commit("HEAD")
            source = await runner.resolve_commit(branch)
            if await runner.is_ancestor(source, head):
                return MergeResult(success=True, conflicts=[], merge_commit=head)
            merged = await runner.merge_tree(head, source)
            if not merged.clean:
                return MergeResult(success=False, conflicts=merged.conflicts, merge_commit=None)
            commit = await runner.commit_tree(
                merged.tree, [head, source], f"Merge branch '{branch}'"
            )
            await runner.fast_forward(commit)
        except GitError:
            return MergeResult(success=False, conflicts=[], merge_commit=None)
        return MergeResult(success=True, conflicts=[], merge_commit=commit)

    async def sync_worktree_to_main(
        self, repo_path: str, worktree_path: str, main_branch: str = "main"
    ) -> None:
        """Merge the latest main branch into the worktree's branch.

        Raises:
            GitError: If the merge fails; a conflicted merge is aborted first.
        """
        await GitRunner(Path(worktree_path).absolute()).merge(main_branch)

    async def has_pending_changes(
        self, repo_path: str, worktree_path: str
    ) -> bool:
        """Check if the worktree has modified, staged or untracked files."""
        status = await GitRunner(Path(worktree_path).absolute()).status_porcelain()
        return bool(status.strip())

    async def commit_all(self, worktree_path: str, message: str) -> str:
        """Stage everything in the worktree and commit it; returns the commit SHA."""
        runner = GitRunner(Path(worktree_path).absolute())
        await runner.stage_all()
        return await runner.commit(message)

    async def remove_worktree(
        self, worktree_path: str, branch: str, repo_path: str
    ) -> bool:
        """Remove a worktree and delete its associated branch.

        Returns:
            True if both steps succeeded, False otherwise.
        """
        try:
            runner = GitRunner(Path(repo_path).absolute())
            await runner.remove_worktree(Path(worktree_path).absolute(), force=True)
            await runner.delete_branch(branch, force=True)
        except GitError:
            return False
        return True

    async def revert_worktree_commit(
        self, repo_path: str, worktree_path: str
    ) -> bool:
        """Revert the last commit in the worktree; False if it cannot apply cleanly."""
        try:
            await GitRunner(Path(worktree_path).absolute()).revert_head()
        except GitError:
            return False
        return True
