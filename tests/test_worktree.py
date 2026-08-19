"""Tests for WorktreeManager - git worktree isolation for parallel agents."""

import asyncio
import uuid
from pathlib import Path

import pytest

from nexus.runtime.worktree import MergeResult, WorktreeInfo, WorktreeManager


async def _run_git(cwd: str, *args: str) -> str:
    """Helper to run git commands in tests."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {stderr.decode()}"
    return stdout.decode()


async def _init_repo(path: Path) -> str:
    """Create a git repo with an initial commit and return its path as string."""
    repo = str(path / "repo")
    Path(repo).mkdir()
    await _run_git(repo, "init")
    await _run_git(repo, "config", "user.email", "test@test.com")
    await _run_git(repo, "config", "user.name", "Test")
    # Create initial commit
    readme = Path(repo) / "README.md"
    readme.write_text("# Test Repo\n")
    await _run_git(repo, "add", "README.md")
    await _run_git(repo, "commit", "-m", "Initial commit")
    # Rename branch to main for consistency
    await _run_git(repo, "branch", "-M", "main")
    return repo


class TestCreateWorktree:
    """Tests for WorktreeManager.create_worktree."""

    @pytest.mark.asyncio
    async def test_creates_branch_and_directory(self, tmp_path: Path) -> None:
        """create_worktree creates a git worktree with proper branch naming."""
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")

        info = await manager.create_worktree(repo, agent_id, "coder")

        assert isinstance(info, WorktreeInfo)
        assert info.branch == "agent/coder-12345678"
        assert info.agent_id == agent_id
        assert info.agent_name == "coder"
        assert Path(info.worktree_path).exists()
        # The worktree should have the same files as the repo
        assert (Path(info.worktree_path) / "README.md").exists()

    @pytest.mark.asyncio
    async def test_branch_exists_in_repo(self, tmp_path: Path) -> None:
        """The created branch is visible from the main repo."""
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.UUID("abcdef01-1234-1234-1234-123456789abc")

        info = await manager.create_worktree(repo, agent_id, "planner")

        branches = await _run_git(repo, "branch", "--list")
        assert "agent/planner-abcdef01" in branches

    @pytest.mark.asyncio
    async def test_worktree_path_follows_convention(self, tmp_path: Path) -> None:
        """Worktree is created at repo_path/../worktrees/<agent_name>-<short_id>."""
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.UUID("99887766-5544-3322-1100-aabbccddeeff")

        info = await manager.create_worktree(repo, agent_id, "reviewer")

        expected_path = str(tmp_path / "worktrees" / "reviewer-99887766")
        assert info.worktree_path == expected_path

    @pytest.mark.asyncio
    async def test_branch_cleaned_up_on_worktree_failure(
        self, tmp_path: Path
    ) -> None:
        """Branch is deleted if git worktree add fails after branch creation."""
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")

        # Create a file at the worktree path to cause git worktree add to fail
        worktree_dir = tmp_path / "worktrees" / "blocker-12345678"
        worktree_dir.mkdir(parents=True)
        (worktree_dir / "blocker.txt").write_text("occupying path\n")

        with pytest.raises(RuntimeError):
            await manager.create_worktree(repo, agent_id, "blocker")

        # The orphaned branch should have been cleaned up
        branches = await _run_git(repo, "branch", "--list")
        assert "agent/blocker-12345678" not in branches


class TestMergeWorktree:
    """Tests for WorktreeManager.merge_worktree."""

    @pytest.mark.asyncio
    async def test_clean_merge_returns_success(self, tmp_path: Path) -> None:
        """merge_worktree returns MergeResult with success=True on clean merge."""
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.uuid4()

        info = await manager.create_worktree(repo, agent_id, "dev")

        # Make a commit in the worktree
        new_file = Path(info.worktree_path) / "feature.py"
        new_file.write_text("print('hello')\n")
        await _run_git(info.worktree_path, "add", "feature.py")
        await _run_git(info.worktree_path, "commit", "-m", "Add feature")

        result = await manager.merge_worktree(repo, info.worktree_path, info.branch)

        assert isinstance(result, MergeResult)
        assert result.success is True
        assert result.conflicts == []
        assert result.merge_commit is not None
        # The merged file should exist in the main repo
        assert (Path(repo) / "feature.py").exists()

    @pytest.mark.asyncio
    async def test_conflict_returns_conflict_info(self, tmp_path: Path) -> None:
        """merge_worktree returns MergeResult with conflicts list on conflict."""
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.uuid4()

        info = await manager.create_worktree(repo, agent_id, "dev")

        # Make conflicting changes in the main repo
        conflict_file = Path(repo) / "README.md"
        conflict_file.write_text("# Modified in main\n")
        await _run_git(repo, "add", "README.md")
        await _run_git(repo, "commit", "-m", "Main change")

        # Make conflicting changes in the worktree
        wt_file = Path(info.worktree_path) / "README.md"
        wt_file.write_text("# Modified in worktree\n")
        await _run_git(info.worktree_path, "add", "README.md")
        await _run_git(info.worktree_path, "commit", "-m", "Worktree change")

        result = await manager.merge_worktree(repo, info.worktree_path, info.branch)

        assert result.success is False
        assert "README.md" in result.conflicts
        assert result.merge_commit is None


class TestHasPendingChanges:
    """Tests for WorktreeManager.has_pending_changes."""

    @pytest.mark.asyncio
    async def test_detects_uncommitted_files(self, tmp_path: Path) -> None:
        """has_pending_changes detects uncommitted modifications."""
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.uuid4()

        info = await manager.create_worktree(repo, agent_id, "writer")

        # Initially no changes
        assert await manager.has_pending_changes(repo, info.worktree_path) is False

        # Add an untracked file
        new_file = Path(info.worktree_path) / "draft.txt"
        new_file.write_text("work in progress\n")

        assert await manager.has_pending_changes(repo, info.worktree_path) is True

    @pytest.mark.asyncio
    async def test_detects_staged_changes(self, tmp_path: Path) -> None:
        """has_pending_changes detects staged but uncommitted files."""
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.uuid4()

        info = await manager.create_worktree(repo, agent_id, "stager")

        # Stage a modification
        readme = Path(info.worktree_path) / "README.md"
        readme.write_text("# Staged edit\n")
        await _run_git(info.worktree_path, "add", "README.md")

        assert await manager.has_pending_changes(repo, info.worktree_path) is True

    @pytest.mark.asyncio
    async def test_clean_worktree_no_changes(self, tmp_path: Path) -> None:
        """has_pending_changes returns False for a clean worktree."""
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.uuid4()

        info = await manager.create_worktree(repo, agent_id, "clean")

        assert await manager.has_pending_changes(repo, info.worktree_path) is False


class TestRemoveWorktree:
    """Tests for WorktreeManager.remove_worktree."""

    @pytest.mark.asyncio
    async def test_removes_directory_and_branch(self, tmp_path: Path) -> None:
        """remove_worktree deletes the worktree directory and branch."""
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.uuid4()

        info = await manager.create_worktree(repo, agent_id, "temp")
        assert Path(info.worktree_path).exists()

        result = await manager.remove_worktree(
            info.worktree_path, info.branch, repo
        )

        assert result is True
        assert not Path(info.worktree_path).exists()
        # Branch should also be gone
        branches = await _run_git(repo, "branch", "--list")
        assert info.branch not in branches


class TestRevertWorktreeCommit:
    """Tests for WorktreeManager.revert_worktree_commit."""

    @pytest.mark.asyncio
    async def test_undoes_last_commit(self, tmp_path: Path) -> None:
        """revert_worktree_commit undoes the last commit."""
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.uuid4()

        info = await manager.create_worktree(repo, agent_id, "reverter")

        # Make a commit in the worktree
        new_file = Path(info.worktree_path) / "oops.txt"
        new_file.write_text("mistake\n")
        await _run_git(info.worktree_path, "add", "oops.txt")
        await _run_git(info.worktree_path, "commit", "-m", "Bad commit")
        assert new_file.exists()

        result = await manager.revert_worktree_commit(repo, info.worktree_path)

        assert result is True
        # The file should be removed by the revert
        assert not new_file.exists()


class TestSyncWorktreeToMain:
    """Tests for WorktreeManager.sync_worktree_to_main."""

    @pytest.mark.asyncio
    async def test_pulls_new_commits_from_main(self, tmp_path: Path) -> None:
        """sync_worktree_to_main brings main branch changes into worktree."""
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.uuid4()

        info = await manager.create_worktree(repo, agent_id, "syncer")

        # Add a new commit to main in the repo
        new_file = Path(repo) / "from_main.txt"
        new_file.write_text("new content from main\n")
        await _run_git(repo, "add", "from_main.txt")
        await _run_git(repo, "commit", "-m", "Main update")

        # The file should not be in worktree yet
        assert not (Path(info.worktree_path) / "from_main.txt").exists()

        await manager.sync_worktree_to_main(repo, info.worktree_path, "main")

        # Now the file should be present
        assert (Path(info.worktree_path) / "from_main.txt").exists()


class TestEdgeCases:
    """Edge-case tests for WorktreeManager error handling paths."""

    @pytest.mark.asyncio
    async def test_revert_nothing_to_revert_returns_false(
        self, tmp_path: Path
    ) -> None:
        """revert_worktree_commit returns False when revert cannot apply cleanly.

        When the worktree has uncommitted changes that conflict with the revert
        operation, git revert HEAD fails and the method should return False.
        """
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.uuid4()

        info = await manager.create_worktree(repo, agent_id, "noop")

        # Make a commit that modifies README.md
        readme = Path(info.worktree_path) / "README.md"
        readme.write_text("committed change\n")
        await _run_git(info.worktree_path, "add", "README.md")
        await _run_git(info.worktree_path, "commit", "-m", "Modify readme")

        # Now leave a dirty working tree that conflicts with the revert
        readme.write_text("dirty conflicting content\n")

        # Revert should fail because of the conflicting uncommitted change
        result = await manager.revert_worktree_commit(repo, info.worktree_path)

        assert result is False

    @pytest.mark.asyncio
    async def test_remove_already_removed_returns_false(
        self, tmp_path: Path
    ) -> None:
        """remove_worktree returns False when the worktree is already gone.

        If the worktree directory has been removed and git has pruned the
        reference, git worktree remove will fail and the method returns False.
        """
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.uuid4()

        info = await manager.create_worktree(repo, agent_id, "ephemeral")
        assert Path(info.worktree_path).exists()

        # Manually remove the worktree directory and prune git's reference
        import shutil

        shutil.rmtree(info.worktree_path)
        await _run_git(repo, "worktree", "prune")

        result = await manager.remove_worktree(
            info.worktree_path, info.branch, repo
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_multiple_worktrees_independent(
        self, tmp_path: Path
    ) -> None:
        """Two worktrees from the same repo are independent of each other.

        Changes made in one worktree must not appear in the other.
        """
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_a = uuid.uuid4()
        agent_b = uuid.uuid4()

        info_a = await manager.create_worktree(repo, agent_a, "alpha")
        info_b = await manager.create_worktree(repo, agent_b, "beta")

        # Make a change in worktree A
        file_a = Path(info_a.worktree_path) / "alpha_only.txt"
        file_a.write_text("alpha content\n")
        await _run_git(info_a.worktree_path, "add", "alpha_only.txt")
        await _run_git(info_a.worktree_path, "commit", "-m", "Alpha commit")

        # Make a different change in worktree B
        file_b = Path(info_b.worktree_path) / "beta_only.txt"
        file_b.write_text("beta content\n")
        await _run_git(info_b.worktree_path, "add", "beta_only.txt")
        await _run_git(info_b.worktree_path, "commit", "-m", "Beta commit")

        # Verify isolation: A does not have B's file and vice versa
        assert (Path(info_a.worktree_path) / "alpha_only.txt").exists()
        assert not (Path(info_a.worktree_path) / "beta_only.txt").exists()
        assert (Path(info_b.worktree_path) / "beta_only.txt").exists()
        assert not (Path(info_b.worktree_path) / "alpha_only.txt").exists()

    @pytest.mark.asyncio
    async def test_create_worktree_duplicate_branch_fails(
        self, tmp_path: Path
    ) -> None:
        """Creating a worktree with a duplicate branch name raises RuntimeError.

        If a worktree already exists for the same agent_id and agent_name,
        attempting to create another one with the same parameters should fail
        because the branch already exists.
        """
        repo = await _init_repo(tmp_path)
        manager = WorktreeManager()
        agent_id = uuid.UUID("deadbeef-1234-1234-1234-123456789abc")

        await manager.create_worktree(repo, agent_id, "duper")

        with pytest.raises(RuntimeError):
            await manager.create_worktree(repo, agent_id, "duper")
