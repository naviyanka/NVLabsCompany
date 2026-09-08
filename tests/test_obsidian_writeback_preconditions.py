"""Writeback preconditions for the vault (ADR 0002 §19, §20 controls 7, 9, 12, 13).

Phase 1F-PRE. Nothing here writes to a real vault, and nothing under test writes
to one either — these are the gates a future writer has to clear, tested before
the writer exists so it inherits working controls rather than inventing them.

Every test builds its own temporary vault and, where Git is involved, its own
temporary repository. The development vault at ``Vault/`` is never touched: it is
not the configured root in any test, and the ``vault`` fixture patches the setting
to a ``tmp_path`` directory.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.tool import Tool
from nexus.tools.registry import ToolRegistry
from nexus.obsidian.actor import (
    ACTOR_AGENT,
    ACTOR_OPERATOR,
    ACTOR_SYSTEM,
    ActorError,
    WriteActor,
)
from nexus.obsidian.authorization import (
    WHOLE_VAULT,
    VaultAuthorizationError,
    VaultWriteAuthorizer,
    canonical_vault_path,
    normalize_subtree,
)
from nexus.obsidian.portability import (
    EXCLUDED_DIRECTORIES,
    VaultBundle,
    export_vault_files,
    import_vault_files,
)
from nexus.obsidian.secret_scan import (
    SCAN_CLEAN,
    SCAN_SCANNER_ERROR,
    SCAN_SECRET_DETECTED,
    scan_bytes,
    scan_text,
    shannon_entropy,
)
from nexus.obsidian.security import (
    VaultBoundaryError,
    VaultExtensionError,
    VaultSecurityError,
)
from nexus.obsidian.vault_git import (
    GIT_ABSENT,
    GIT_CLEAN,
    GIT_DIRTY,
    is_repository_root,
    rollback_plan,
    vault_git_status,
)

COMPANY_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
COMPANY_B = uuid.UUID("22222222-2222-2222-2222-222222222222")

# The one vault that must never be touched. Asserted against, not written to.
DEVELOPMENT_VAULT = Path("Vault") / "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def vault(tmp_path):
    """A temporary vault root with company A's directory, and nothing else."""
    root = tmp_path / "vaults"
    (root / str(COMPANY_A)).mkdir(parents=True)
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = str(root)
        mock_settings.obsidian_max_note_bytes = 1_048_576
        yield root


def write_note(root: Path, company: uuid.UUID, rel: str, body: str) -> Path:
    path = root / str(company) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10, check=True)
        return True
    except Exception:  # noqa: BLE001 - absence is the answer
        return False


requires_git = pytest.mark.skipif(not git_available(), reason="git is not installed")


def init_repo(path: Path) -> None:
    """A temporary Git repository with an identity, so commits succeed in CI."""
    for args in (
        ["init", "-q"],
        ["config", "user.email", "tests@example.invalid"],
        ["config", "user.name", "Phase 1F-PRE tests"],
        ["config", "commit.gpgsign", "false"],
    ):
        subprocess.run(["git", *args], cwd=str(path), capture_output=True, check=True)


def commit_all(path: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=str(path), capture_output=True, check=True
    )


# ---------------------------------------------------------------------------
# The development vault stays untouched
# ---------------------------------------------------------------------------


def test_no_module_under_test_can_reach_the_development_vault() -> None:
    """Every path comes from the configured root, which tests always override.

    Checked structurally: no precondition module names the development company or
    a hardcoded vault directory, so none of them can reach it regardless of how a
    test is wired.
    """
    package = Path(__file__).resolve().parents[1] / "src" / "nexus" / "obsidian"
    for name in ("secret_scan", "authorization", "actor", "vault_git", "portability"):
        source = (package / f"{name}.py").read_text(encoding="utf-8")
        # Code only: a module docstring may legitimately name the application
        # repository when explaining why the vault is a separate one (§18).
        body = source.split('"""', 2)[-1]
        assert "00000000-0000-4000-8000-000000000001" not in body
        assert "NVLabsCompany" not in body
        assert "Vault/" not in body


def test_the_development_vault_has_no_git_repository_of_its_own() -> None:
    """Nothing in this phase initializes it, and this catches an accident.

    ``git init`` inside the vault would be hard to notice and hard to undo — the
    repository would look deliberate to whoever found it next.
    """
    repo_root = Path(__file__).resolve().parents[1]
    vault_dir = repo_root / DEVELOPMENT_VAULT
    if vault_dir.is_dir():
        assert not (vault_dir / ".git").exists(), (
            "a test or code path initialized Git inside the development vault"
        )
        assert not (repo_root / "Vault" / ".git").exists()


# ---------------------------------------------------------------------------
# 1. Vault Git: state, independence, rollback contract
# ---------------------------------------------------------------------------


class TestVaultGit:
    """Git state is read and reported; it is never created."""

    async def test_a_vault_without_a_repository_is_absent_not_an_error(self, vault) -> None:
        """An unversioned vault is a state to report, not a failure to raise."""
        status = vault_git_status(COMPANY_A)
        assert status.state == GIT_ABSENT
        assert status.versioned is False
        assert status.revert_available is False

    async def test_a_company_without_a_vault_directory_is_absent(self, vault) -> None:
        assert vault_git_status(COMPANY_B).state == GIT_ABSENT

    async def test_an_ancestor_repository_is_not_the_vaults_history(self, tmp_path) -> None:
        """ADR §18: the application repo and the vault repo are different repos.

        A vault nested under a repository must not borrow that repository's
        history — knowledge commits would land in application history. This is the
        reason the check is "is this a repository root", not "is this inside one".
        """
        outer = tmp_path / "app"
        outer.mkdir()
        if git_available():
            init_repo(outer)
        else:
            (outer / ".git").mkdir()

        vault_root = outer / "vaults"
        (vault_root / str(COMPANY_A)).mkdir(parents=True)
        with patch("nexus.obsidian.security.settings") as mock_settings:
            mock_settings.obsidian_vault_root = str(vault_root)
            mock_settings.obsidian_max_note_bytes = 1_048_576
            assert vault_git_status(COMPANY_A).state == GIT_ABSENT
        assert is_repository_root(vault_root / str(COMPANY_A)) is False

    @requires_git
    async def test_a_temporary_vault_can_be_versioned_and_reads_clean(self, vault) -> None:
        company_root = vault / str(COMPANY_A)
        write_note(vault, COMPANY_A, "A.md", "# A\n\nBody.\n")
        init_repo(company_root)
        commit_all(company_root, "initial")

        status = vault_git_status(COMPANY_A)
        assert status.state == GIT_CLEAN
        assert status.head, "a committed repository reported no HEAD"
        assert status.versioned is True
        assert status.revert_available is True

    @requires_git
    async def test_an_uncommitted_change_reads_dirty_with_relative_paths(self, vault) -> None:
        """Dirty means a human is mid-edit, and paths stay vault-relative."""
        company_root = vault / str(COMPANY_A)
        write_note(vault, COMPANY_A, "A.md", "# A\n")
        init_repo(company_root)
        commit_all(company_root, "initial")
        write_note(vault, COMPANY_A, "B.md", "# B\n")

        status = vault_git_status(COMPANY_A)
        assert status.state == GIT_DIRTY
        assert "B.md" in status.dirty_paths
        for path in status.dirty_paths:
            assert str(vault) not in path
            assert not path.startswith("/")

    @requires_git
    async def test_a_dirty_tree_refuses_rollback(self, vault) -> None:
        """Reverting over uncommitted edits would destroy unique work."""
        company_root = vault / str(COMPANY_A)
        write_note(vault, COMPANY_A, "A.md", "# A\n")
        init_repo(company_root)
        commit_all(company_root, "initial")
        write_note(vault, COMPANY_A, "A.md", "# A edited by a human\n")

        status = vault_git_status(COMPANY_A)
        assert status.revert_available is False
        assert "Commit or stash" in rollback_plan(status)

    @requires_git
    async def test_an_initialized_repository_with_no_commits_has_nothing_to_revert(
        self, vault
    ) -> None:
        init_repo(vault / str(COMPANY_A))
        status = vault_git_status(COMPANY_A)
        assert status.head == ""
        assert status.revert_available is False
        assert "no commits" in rollback_plan(status)

    @requires_git
    async def test_content_rollback_restores_the_file_not_the_database(self, vault) -> None:
        """The rollback contract, demonstrated: revert restores bytes.

        ``obsidian_documents`` is untouched by a revert, which is exactly why the
        recovery works — the row holds derived state, so the next scan sees a hash
        change and reindexes. PostgreSQL never holds the only copy of a body.
        """
        company_root = vault / str(COMPANY_A)
        note = write_note(vault, COMPANY_A, "A.md", "original body\n")
        init_repo(company_root)
        commit_all(company_root, "initial")

        note.write_text("body a write replaced\n", encoding="utf-8")
        commit_all(company_root, "the write to be rolled back")
        assert note.read_text(encoding="utf-8") == "body a write replaced\n"

        subprocess.run(
            ["git", "revert", "--no-edit", "HEAD"],
            cwd=str(company_root),
            capture_output=True,
            check=True,
        )
        assert note.read_text(encoding="utf-8") == "original body\n"

    async def test_the_module_never_initializes_a_repository(self) -> None:
        """No code path may create a repository the operator did not ask for."""
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "nexus"
            / "obsidian"
            / "vault_git.py"
        ).read_text(encoding="utf-8")
        for forbidden in ('"init"', "'init'", '"commit"', '"revert"', '"add"'):
            assert forbidden not in source, f"vault_git.py can run git {forbidden}"

    async def test_git_absence_on_the_host_is_reported_not_raised(self, vault) -> None:
        write_note(vault, COMPANY_A, "A.md", "# A\n")
        (vault / str(COMPANY_A) / ".git").mkdir()
        with patch(
            "nexus.obsidian.vault_git._run_git", side_effect=FileNotFoundError("no git")
        ):
            status = vault_git_status(COMPANY_A)
        assert status.state == "unavailable"
        assert "git is not installed" in rollback_plan(status)


# ---------------------------------------------------------------------------
# 2. Portability
# ---------------------------------------------------------------------------


class TestVaultPortability:
    """Note files travel with a company export, and land back safely."""

    async def test_notes_export_as_vault_relative_text(self, vault) -> None:
        write_note(vault, COMPANY_A, "Knowledge/A.md", "# A\n\nBody.\n")
        write_note(vault, COMPANY_A, "B.md", "# B\n")

        bundle = export_vault_files(COMPANY_A)
        assert set(bundle.files) == {"Knowledge/A.md", "B.md"}
        assert bundle.complete is True
        assert bundle.files["Knowledge/A.md"] == "# A\n\nBody.\n"

    async def test_no_host_path_appears_in_an_export(self, vault) -> None:
        import json

        write_note(vault, COMPANY_A, "A.md", "# A\n")
        serialized = json.dumps(export_vault_files(COMPANY_A).to_dict())
        assert str(vault) not in serialized
        assert "C:\\" not in serialized
        for path in export_vault_files(COMPANY_A).to_dict()["files"]:  # type: ignore[index]
            assert not Path(path).is_absolute()

    async def test_another_companys_notes_are_not_exported(self, vault) -> None:
        write_note(vault, COMPANY_A, "Mine.md", "# Mine\n")
        write_note(vault, COMPANY_B, "Theirs.md", "# Theirs\n")

        assert set(export_vault_files(COMPANY_A).files) == {"Mine.md"}
        assert set(export_vault_files(COMPANY_B).files) == {"Theirs.md"}

    async def test_editor_configuration_and_git_metadata_are_excluded(self, vault) -> None:
        """``.obsidian/`` is per-machine editor state, ``.git/`` is history."""
        write_note(vault, COMPANY_A, "A.md", "# A\n")
        write_note(vault, COMPANY_A, ".obsidian/workspace.json", "{}")
        write_note(vault, COMPANY_A, ".obsidian/plugins/x/main.js", "// plugin")
        write_note(vault, COMPANY_A, ".git/config", "[core]\n")

        bundle = export_vault_files(COMPANY_A)
        assert set(bundle.files) == {"A.md"}
        assert not any(
            excluded in path for path in bundle.files for excluded in EXCLUDED_DIRECTORIES
        )
        # Excluded by policy, so not reported as a skipped note either.
        assert not any(".obsidian" in path for path in bundle.skipped)

    async def test_non_markdown_files_are_skipped_and_declared(self, vault) -> None:
        write_note(vault, COMPANY_A, "A.md", "# A\n")
        (vault / str(COMPANY_A) / "diagram.png").write_bytes(b"\x89PNG\r\n")

        bundle = export_vault_files(COMPANY_A)
        assert set(bundle.files) == {"A.md"}
        assert "diagram.png" in bundle.skipped
        assert bundle.complete is False, "a partial export claimed to be complete"

    async def test_an_oversized_note_is_skipped_rather_than_read(self, vault) -> None:
        write_note(vault, COMPANY_A, "Big.md", "x" * 200)
        with patch("nexus.obsidian.portability.settings") as mock_settings:
            mock_settings.obsidian_max_note_bytes = 100
            bundle = export_vault_files(COMPANY_A)
        assert bundle.files == {}
        assert bundle.skipped["Big.md"] == "over the note size limit"

    async def test_a_symlink_is_not_followed(self, vault, tmp_path) -> None:
        """An export must not be the thing that reads outside the vault."""
        outside = tmp_path / "outside.md"
        outside.write_text("# Secret outside the vault\n", encoding="utf-8")
        link = vault / str(COMPANY_A) / "Escape.md"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("this host does not permit symlink creation")

        bundle = export_vault_files(COMPANY_A)
        assert "Escape.md" not in bundle.files
        assert bundle.skipped.get("Escape.md") == "symlink"
        assert "Secret outside" not in "".join(bundle.files.values())

    async def test_a_company_with_no_vault_exports_an_empty_complete_bundle(self, vault) -> None:
        """Nothing was omitted, because there was nothing there."""
        bundle = export_vault_files(COMPANY_B)
        assert bundle.files == {}
        assert bundle.complete is True

    async def test_import_restores_notes_into_the_destination_vault(self, vault) -> None:
        bundle = VaultBundle(files={"Knowledge/A.md": "# A\n\nRestored.\n"})
        outcomes = import_vault_files(COMPANY_B, bundle)

        assert outcomes == {"Knowledge/A.md": "restored"}
        landed = vault / str(COMPANY_B) / "Knowledge" / "A.md"
        assert landed.read_text(encoding="utf-8") == "# A\n\nRestored.\n"

    async def test_import_leaves_no_temporary_file_behind(self, vault) -> None:
        import_vault_files(COMPANY_A, VaultBundle(files={"A.md": "# A\n"}))
        assert list((vault / str(COMPANY_A)).glob("*.tmp")) == []

    async def test_import_does_not_overwrite_an_existing_note_by_default(self, vault) -> None:
        """After the write phase a note may exist nowhere else."""
        write_note(vault, COMPANY_A, "A.md", "# Original\n")
        outcomes = import_vault_files(COMPANY_A, VaultBundle(files={"A.md": "# Archive\n"}))

        assert outcomes == {"A.md": "exists"}
        assert (vault / str(COMPANY_A) / "A.md").read_text(encoding="utf-8") == "# Original\n"

    async def test_overwrite_is_opt_in(self, vault) -> None:
        write_note(vault, COMPANY_A, "A.md", "# Original\n")
        import_vault_files(COMPANY_A, VaultBundle(files={"A.md": "# Archive\n"}), overwrite=True)
        assert (vault / str(COMPANY_A) / "A.md").read_text(encoding="utf-8") == "# Archive\n"

    @pytest.mark.parametrize(
        "hostile_path",
        [
            "../escape.md",
            "../../escape.md",
            "Knowledge/../../escape.md",
            "/etc/passwd.md",
            "C:/Windows/evil.md",
            "C:\\Windows\\evil.md",
            "//host/share/evil.md",
            "\\\\host\\share\\evil.md",
            "notes.txt",
            ".obsidian/workspace.json",
            ".git/config",
        ],
    )
    async def test_a_hostile_archive_path_is_refused(self, vault, hostile_path) -> None:
        """An archive is untrusted input, re-validated on the way in."""
        before = sorted(p.name for p in (vault / str(COMPANY_A)).rglob("*"))
        outcomes = import_vault_files(COMPANY_A, VaultBundle(files={hostile_path: "evil"}))

        assert outcomes[hostile_path].startswith("refused"), outcomes
        assert sorted(p.name for p in (vault / str(COMPANY_A)).rglob("*")) == before
        assert not (vault.parent / "escape.md").exists()
        assert not (vault / "escape.md").exists()

    async def test_an_import_cannot_reach_another_companys_vault(self, vault) -> None:
        write_note(vault, COMPANY_A, "Mine.md", "# Mine\n")
        import_vault_files(COMPANY_B, VaultBundle(files={"Theirs.md": "# Theirs\n"}))

        assert (vault / str(COMPANY_B) / "Theirs.md").exists()
        assert not (vault / str(COMPANY_A) / "Theirs.md").exists()
        assert (vault / str(COMPANY_A) / "Mine.md").read_text(encoding="utf-8") == "# Mine\n"

    async def test_a_symlinked_parent_directory_is_refused_on_import(self, vault, tmp_path) -> None:
        """A joined path can look contained while the parent points elsewhere."""
        outside = tmp_path / "outside"
        outside.mkdir()
        link = vault / str(COMPANY_A) / "Linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("this host does not permit symlink creation")

        outcomes = import_vault_files(COMPANY_A, VaultBundle(files={"Linked/A.md": "# A\n"}))
        assert outcomes["Linked/A.md"].startswith("refused")
        assert not (outside / "A.md").exists()

    async def test_a_round_trip_preserves_note_content(self, vault) -> None:
        write_note(vault, COMPANY_A, "Knowledge/A.md", "# A\n\nBody with [[B]].\n")
        write_note(vault, COMPANY_A, "B.md", "# B\n")

        bundle = VaultBundle.from_dict(export_vault_files(COMPANY_A).to_dict())
        import_vault_files(COMPANY_B, bundle)

        for relative, text in bundle.files.items():
            assert (vault / str(COMPANY_B) / relative).read_text(encoding="utf-8") == text

    async def test_an_archive_without_a_vault_section_is_incomplete_not_an_error(self) -> None:
        """An archive from before vault export existed may still have had notes."""
        bundle = VaultBundle.from_dict(None)
        assert bundle.files == {}
        assert bundle.complete is False


@pytest_asyncio.fixture
async def auth_db(tmp_path):
    import nexus.models  # noqa: F401

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    company = Company(id=COMPANY_A, name="Test Co")
    agent_ids = [uuid.uuid4() for _ in range(3)]
    async with factory() as db:
        db.add(company)
        db.add_all(
            Agent(id=agent_id, company_id=COMPANY_A, name=str(agent_id), role="tester")
            for agent_id in agent_ids
        )
        db.add_all(
            Tool(id=tool_id, company_id=COMPANY_A, name=str(tool_id), tool_type="function")
            for tool_id in (TEST_TOOL_ID, TEST_OTHER_TOOL_ID)
        )
        await db.commit()
    yield factory, agent_ids
    await engine.dispose()


TEST_TOOL_ID = uuid.uuid4()
TEST_OTHER_TOOL_ID = uuid.uuid4()


@pytest.mark.asyncio
class TestPortabilityServiceIntegration:
    """The export archive itself carries the vault, and says whether it is whole."""

    @staticmethod
    async def _service(tmp_path):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlmodel import SQLModel
        from sqlmodel.ext.asyncio.session import AsyncSession

        import nexus.models  # noqa: F401
        from nexus.models.company import Company
        from nexus.services.portability_service import CompanyPortabilityService

        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'port.db'}")
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            db.add(Company(id=COMPANY_A, name="Test Co"))
            await db.commit()
        return engine, factory, CompanyPortabilityService

    async def test_the_archive_carries_the_vault_and_declares_completeness(
        self, vault, tmp_path
    ) -> None:
        engine, factory, Service = await self._service(tmp_path)
        try:
            write_note(vault, COMPANY_A, "Knowledge/A.md", "# A\n\nBody.\n")
            async with factory() as db:
                archive = await Service(db).export_company(COMPANY_A)

            assert archive["vault"]["files"] == {"Knowledge/A.md": "# A\n\nBody.\n"}
            assert archive["manifest"]["vault_complete"] is True
            assert archive["manifest"]["vault_file_count"] == 1
        finally:
            await engine.dispose()

    async def test_a_partial_vault_export_is_declared_in_the_manifest(
        self, vault, tmp_path
    ) -> None:
        """§19 forbids silence: an incomplete export has to say so."""
        engine, factory, Service = await self._service(tmp_path)
        try:
            write_note(vault, COMPANY_A, "A.md", "# A\n")
            (vault / str(COMPANY_A) / "image.png").write_bytes(b"\x89PNG")
            async with factory() as db:
                archive = await Service(db).export_company(COMPANY_A)

            assert archive["manifest"]["vault_complete"] is False
            assert "partial" in archive["manifest"]["vault_detail"]
        finally:
            await engine.dispose()

    async def test_import_does_not_touch_the_filesystem_unless_asked(
        self, vault, tmp_path
    ) -> None:
        """Importing rows must not become a filesystem side effect by default."""
        engine, factory, Service = await self._service(tmp_path)
        try:
            write_note(vault, COMPANY_A, "A.md", "# A\n")
            async with factory() as db:
                archive = await Service(db).export_company(COMPANY_A)
            async with factory() as db:
                new_id = await Service(db).import_company(archive, new_name="Copy")

            assert not (vault / str(new_id)).exists()
        finally:
            await engine.dispose()

    async def test_import_restores_the_vault_when_asked(self, vault, tmp_path) -> None:
        engine, factory, Service = await self._service(tmp_path)
        try:
            write_note(vault, COMPANY_A, "Knowledge/A.md", "# A\n\nBody.\n")
            async with factory() as db:
                archive = await Service(db).export_company(COMPANY_A)
            async with factory() as db:
                new_id = await Service(db).import_company(
                    archive, new_name="Copy", restore_vault=True
                )

            restored = vault / str(new_id) / "Knowledge" / "A.md"
            assert restored.read_text(encoding="utf-8") == "# A\n\nBody.\n"
            # The source company is untouched by its own export being restored.
            assert (vault / str(COMPANY_A) / "Knowledge" / "A.md").exists()
        finally:
            await engine.dispose()


# ---------------------------------------------------------------------------
# 3. Secret scanner
# ---------------------------------------------------------------------------


class TestSecretScanner:
    """Fail closed: only a clean scan permits a write.

    Every fixture below is obviously fake — a structurally valid shape with
    nonsense payload — because a test file is a Git-tracked file, which is the
    exact hazard this scanner exists to prevent.
    """

    async def test_ordinary_prose_is_clean(self) -> None:
        result = scan_text(
            "# Runbook\n\nRotate credentials quarterly. See [[Security]].\n"
            "The token lives in the secret manager, not in this note.\n"
        )
        assert result.outcome == SCAN_CLEAN
        assert result.allowed is True

    @pytest.mark.parametrize(
        ("label", "content"),
        [
            ("openai key", "key: sk-" + "A1b2C3d4E5f6G7h8I9j0KLMN"),
            ("anthropic key", "key: sk-ant-" + "api03-FAKEFAKEFAKEFAKEFAKE00"),
            ("aws access key id", "aws_key = AKIAFAKEFAKEFAKEFAKE"),
            ("github token", "token: ghp_" + "0123456789abcdefghijklmnopqrstuvwxyzA"),
            ("google api key", "google: AIza" + "SyFAKE0123456789abcdefghijklmnopqrs"),
            ("slack token", "slack: xoxb-000000000000-FAKEFAKEFAKE"),
            ("stripe key", "stripe: sk_live_" + "FAKEFAKEFAKEFAKEFAKE00"),
            (
                "private key block",
                "-----BEGIN RSA PRIVATE KEY-----\nnot a real key\n-----END RSA PRIVATE KEY-----",
            ),
            ("bearer token", 'Authorization: Bearer FAKEFAKEFAKEFAKEFAKE00'),
            ("database url", "DATABASE_URL=postgresql://user:hunter2pass@db.internal:5432/app"),
            ("password assignment", "password: correct-horse-battery"),
            ("client secret", "client_secret = abcdefghijklmnop"),
        ],
    )
    async def test_a_credential_shape_refuses_the_write(self, label, content) -> None:
        result = scan_text(f"# Note\n\n{content}\n")
        assert result.outcome == SCAN_SECRET_DETECTED, f"{label} was not detected"
        assert result.allowed is False

    async def test_a_finding_names_the_rule_and_line_not_the_secret(self) -> None:
        """A result is logged and returned, so it must not carry the credential."""
        secret = "sk-" + "Z9y8X7w6V5u4T3s2R1q0PONM"
        result = scan_text(f"# Note\n\nkey: {secret}\n")
        assert result.outcome == SCAN_SECRET_DETECTED
        rendered = " ".join(result.findings) + result.detail
        assert secret not in rendered
        assert "line 3" in rendered

    async def test_a_high_entropy_assigned_value_is_detected(self) -> None:
        """The generic rule: a bespoke token with no recognisable prefix."""
        result = scan_text("internal_handle: 7Gx2Qw9Lz4Rv8Tn1Bk6Yc3Mj5Hd0Pf\n")
        assert result.outcome == SCAN_SECRET_DETECTED

    @pytest.mark.parametrize(
        "benign",
        [
            "nexus_id: 11111111-1111-1111-1111-111111111111",
            "indexed_at: 2026-08-30T12:00:00Z",
            "content_hash: 9f2b7c1d4e5a6b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c",
        ],
    )
    async def test_structural_values_are_not_secrets(self, benign) -> None:
        """A note's own frontmatter must not make it unwritable."""
        assert scan_text(f"---\n{benign}\n---\n\n# Note\n").outcome == SCAN_CLEAN

    async def test_a_documented_false_positive(self) -> None:
        """Documented, not hidden: a long random-looking assigned value matches.

        The entropy rule cannot tell a base64 diagram from a token, and on a write
        path the safe direction of error is to refuse. The author rephrases; a real
        credential does not reach history.
        """
        result = scan_text(
            "diagram_data: iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk\n"
        )
        assert result.outcome == SCAN_SECRET_DETECTED

    async def test_scan_bytes_refuses_undecodable_content(self) -> None:
        """A note is UTF-8 Markdown; bytes that are not cannot be scanned."""
        result = scan_bytes(b"\xff\xfe\x00binary")
        assert result.outcome == SCAN_SCANNER_ERROR
        assert result.allowed is False

    async def test_oversized_content_refuses_rather_than_scanning(self) -> None:
        from nexus.obsidian.secret_scan import MAX_SCAN_BYTES

        result = scan_text("x" * (MAX_SCAN_BYTES + 1))
        assert result.outcome == SCAN_SCANNER_ERROR
        assert result.allowed is False

    async def test_a_scanner_crash_fails_closed(self) -> None:
        """"We could not check" is not "there is nothing there"."""
        with patch(
            "nexus.obsidian.secret_scan.shannon_entropy",
            side_effect=RuntimeError("scanner bug"),
        ):
            result = scan_text("handle: zzzQQQwwwEEErrrTTTyyyUUUiii\n")
        assert result.outcome == SCAN_SCANNER_ERROR
        assert result.allowed is False

    async def test_clean_bytes_pass(self) -> None:
        assert scan_bytes("# Note\n\nOrdinary prose.\n".encode()).outcome == SCAN_CLEAN

    async def test_entropy_separates_identifiers_from_random_material(self) -> None:
        """The rule that makes the threshold usable, and its real margin.

        Ordinary word-shaped values sit just under 4.0 bits/char; random tokens
        sit near 5. The margin is not large — which is why the entropy rule runs
        only on assignment-shaped values above a length floor, and why a false
        positive is a documented outcome rather than a claim it cannot happen.
        """
        assert shannon_entropy("deployment-configuration-notes") < 4.0
        assert shannon_entropy("quarterly_planning_document") < 4.0
        assert shannon_entropy("7Gx2Qw9Lz4Rv8Tn1Bk6Yc3Mj5Hd0Pf") >= 4.0

    async def test_only_a_clean_result_is_allowed(self) -> None:
        """The three-way outcome collapses to one permission bit, one way."""
        from nexus.obsidian.secret_scan import SecretScanResult

        assert SecretScanResult(outcome=SCAN_CLEAN).allowed is True
        assert SecretScanResult(outcome=SCAN_SECRET_DETECTED).allowed is False
        assert SecretScanResult(outcome=SCAN_SCANNER_ERROR).allowed is False

    async def test_nothing_is_redacted(self) -> None:
        """The scanner refuses; it never returns rewritten content to write."""
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "nexus"
            / "obsidian"
            / "secret_scan.py"
        ).read_text(encoding="utf-8")
        assert "REDACTED" not in source
        assert ".sub(" not in source.split('"""', 2)[-1], "the scanner rewrites content"


# ---------------------------------------------------------------------------
# 4. Per-agent, per-path authorization
# ---------------------------------------------------------------------------


class TestSubtreeNormalization:
    """A grant is operator-authored input, checked as strictly as a note path."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Projects", "Projects"),
            ("Projects/", "Projects"),
            ("/Projects", None),
            ("Projects\\Sub", "Projects/Sub"),
            ("./Projects", "Projects"),
            ("*", WHOLE_VAULT),
            ("", WHOLE_VAULT),
        ],
    )
    async def test_normalization(self, raw, expected) -> None:
        if expected is None:
            with pytest.raises(VaultBoundaryError):
                normalize_subtree(raw)
        else:
            assert normalize_subtree(raw) == expected

    @pytest.mark.parametrize(
        "hostile",
        ["../Secrets", "Projects/../../Secrets", "/etc", "C:/Windows", "C:\\Windows", "//host/share"],
    )
    async def test_a_grant_cannot_name_anything_outside_the_vault(self, hostile) -> None:
        with pytest.raises(VaultBoundaryError):
            normalize_subtree(hostile)


@pytest.mark.asyncio
class TestVaultWriteAuthorization:
    """The chain: company, agent, tool, subtree — on the canonical path."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, auth_db):
        factory, agents = auth_db
        self.agent_a, self.agent_b, self.agent_c = agents
        self.tool = TEST_TOOL_ID
        self.other_tool = TEST_OTHER_TOOL_ID
        self.registry = ToolRegistry(factory)
        self.auth = VaultWriteAuthorizer(self.registry, factory)
        await self.registry.grant_access(COMPANY_A, self.agent_a, self.tool)
        await self.registry.grant_access(COMPANY_A, self.agent_b, self.tool)
        await self.auth.grant_async(COMPANY_A, self.agent_a, self.tool, "Projects")
        await self.auth.grant_async(
            COMPANY_A, self.agent_b, self.tool, f"Agents/{self.agent_a}"
        )

    async def test_an_authorized_path_returns_its_canonical_form(self, vault) -> None:
        canonical = await self.auth.authorize_async(
            COMPANY_A, self.agent_a, self.tool, "Projects/Plan.md"
        )
        assert canonical == "Projects/Plan.md"

    async def test_a_nested_path_inside_the_subtree_is_authorized(self, vault) -> None:
        assert (
            await self.auth.authorize_async(COMPANY_A, self.agent_a, self.tool, "Projects/Q3/Plan.md")
            == "Projects/Q3/Plan.md"
        )

    async def test_a_sibling_subtree_is_refused(self, vault) -> None:
        with pytest.raises(VaultAuthorizationError):
            await self.auth.authorize_async(COMPANY_A, self.agent_a, self.tool, "Secrets/Keys.md")

    async def test_a_prefix_lookalike_directory_is_refused(self, vault) -> None:
        """``Projects`` must not authorize ``ProjectsSecret`` — segment-wise, not string-wise."""
        with pytest.raises(VaultAuthorizationError):
            await self.auth.authorize_async(COMPANY_A, self.agent_a, self.tool, "ProjectsSecret/K.md")

    async def test_the_subtree_root_itself_is_not_a_writable_note(self, vault) -> None:
        with pytest.raises(VaultSecurityError):
            await self.auth.authorize_async(COMPANY_A, self.agent_a, self.tool, "Projects")

    async def test_traversal_out_of_the_subtree_is_refused_on_the_canonical_path(
        self, vault
    ) -> None:
        """The confused-deputy case: a path that *starts* inside the grant.

        Compared as text, ``Projects/../Secrets/Keys.md`` passes a ``Projects``
        prefix check. Canonicalized first, it is ``Secrets/Keys.md`` and refused.
        """
        with pytest.raises(VaultAuthorizationError):
            await self.auth.authorize_async(
                COMPANY_A, self.agent_a, self.tool, "Projects/../Secrets/Keys.md"
            )

    @pytest.mark.parametrize(
        "hostile",
        [
            "../outside.md",
            "../../outside.md",
            "Projects/../../outside.md",
            "/etc/passwd.md",
            "C:/Windows/evil.md",
            "C:\\Windows\\evil.md",
            "//host/share/evil.md",
            "\\\\host\\share\\evil.md",
        ],
    )
    async def test_a_path_outside_the_vault_is_refused_by_the_validator(
        self, vault, hostile
    ) -> None:
        with pytest.raises(VaultSecurityError):
            await self.auth.authorize_async(COMPANY_A, self.agent_a, self.tool, hostile)

    async def test_a_non_markdown_path_is_refused(self, vault) -> None:
        with pytest.raises(VaultExtensionError):
            await self.auth.authorize_async(COMPANY_A, self.agent_a, self.tool, "Projects/notes.txt")

    async def test_a_symlink_escape_is_refused(self, vault, tmp_path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        link = vault / str(COMPANY_A) / "Projects"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("this host does not permit symlink creation")

        with pytest.raises(VaultSecurityError):
            await self.auth.authorize_async(COMPANY_A, self.agent_a, self.tool, "Projects/Plan.md")

    async def test_case_variation_follows_the_filesystem(self, vault) -> None:
        """On Windows ``projects/plan.md`` and ``Projects/Plan.md`` are one file.

        Refusing the lowercase form there would deny a write the OS considers
        granted; on a case-sensitive filesystem they are different paths and the
        refusal is correct. Either way the answer matches what the filesystem does.
        """
        import os

        lowercase_is_same_file = os.path.normcase("Projects") == os.path.normcase("projects")
        if lowercase_is_same_file:
            assert (
                await self.auth.authorize_async(COMPANY_A, self.agent_a, self.tool, "projects/plan.md")
                == "projects/plan.md"
            )
        else:
            with pytest.raises(VaultAuthorizationError):
                await self.auth.authorize_async(COMPANY_A, self.agent_a, self.tool, "projects/plan.md")

    async def test_an_agent_with_no_tool_access_is_refused(self, vault) -> None:
        await self.auth.grant_async(COMPANY_A, self.agent_c, self.tool, "Projects")
        with pytest.raises(VaultAuthorizationError):
            await self.auth.authorize_async(COMPANY_A, self.agent_c, self.tool, "Projects/Plan.md")

    async def test_an_agent_with_no_path_grant_is_refused(self, vault) -> None:
        await self.registry.grant_access(COMPANY_A, self.agent_c, self.tool)
        with pytest.raises(VaultAuthorizationError):
            await self.auth.authorize_async(COMPANY_A, self.agent_c, self.tool, "Projects/Plan.md")

    async def test_a_grant_is_scoped_to_one_tool(self, vault) -> None:
        await self.registry.grant_access(COMPANY_A, self.agent_a, self.other_tool)
        with pytest.raises(VaultAuthorizationError):
            await self.auth.authorize_async(COMPANY_A, self.agent_a, self.other_tool, "Projects/Plan.md")

    async def test_a_grant_is_scoped_to_one_company(self, vault) -> None:
        """A grant in company A must not authorize a write in company B."""
        with pytest.raises(VaultAuthorizationError):
            await self.auth.authorize_async(COMPANY_B, self.agent_a, self.tool, "Projects/Plan.md")

    async def test_agents_do_not_inherit_each_others_subtrees(self, vault) -> None:
        assert await self.auth.authorize_async(
            COMPANY_A, self.agent_b, self.tool, f"Agents/{self.agent_a}/Note.md"
        )
        with pytest.raises(VaultAuthorizationError):
            await self.auth.authorize_async(COMPANY_A, self.agent_b, self.tool, "Projects/Plan.md")

    async def test_a_whole_vault_grant_covers_any_valid_note(self, vault) -> None:
        await self.auth.grant_async(COMPANY_A, self.agent_a, self.tool, WHOLE_VAULT)
        assert await self.auth.authorize_async(COMPANY_A, self.agent_a, self.tool, "Anywhere.md")

    async def test_revoking_a_subtree_removes_only_that_authority(self, vault) -> None:
        await self.auth.grant_async(COMPANY_A, self.agent_a, self.tool, "Drafts")
        await self.auth.revoke_async(COMPANY_A, self.agent_a, self.tool, "Projects")

        assert await self.auth.authorize_async(COMPANY_A, self.agent_a, self.tool, "Drafts/D.md")
        with pytest.raises(VaultAuthorizationError):
            await self.auth.authorize_async(COMPANY_A, self.agent_a, self.tool, "Projects/Plan.md")

    async def test_revoking_everything_leaves_no_authority(self, vault) -> None:
        await self.auth.revoke_async(COMPANY_A, self.agent_a, self.tool)
        assert await self.auth.subtrees_async(COMPANY_A, self.agent_a, self.tool) == frozenset()
        with pytest.raises(VaultAuthorizationError):
            await self.auth.authorize_async(COMPANY_A, self.agent_a, self.tool, "Projects/Plan.md")

    async def test_without_a_registry_every_agent_write_is_refused(self, vault) -> None:
        """A path check must never stand in for an access check."""
        auth = VaultWriteAuthorizer(registry=None, session_factory=self.auth._session_factory)
        await auth.grant_async(COMPANY_A, self.agent_a, self.tool, WHOLE_VAULT)
        with pytest.raises(VaultAuthorizationError):
            await auth.authorize_async(COMPANY_A, self.agent_a, self.tool, "Any.md")

    async def test_authorization_never_touches_the_filesystem(self, vault) -> None:
        """A decision is not a write: nothing is created by authorizing."""
        before = sorted(p.name for p in (vault / str(COMPANY_A)).rglob("*"))
        await self.auth.authorize_async(COMPANY_A, self.agent_a, self.tool, "Projects/Plan.md")
        assert sorted(p.name for p in (vault / str(COMPANY_A)).rglob("*")) == before


@pytest.mark.asyncio
class TestActorAuthorization:
    """System and operator writes get the path half, not the tool half."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, auth_db):
        factory, agents = auth_db
        self.agent = agents[0]
        self.tool = TEST_TOOL_ID
        self.registry = ToolRegistry(factory)
        self.auth = VaultWriteAuthorizer(self.registry, factory)

    async def test_a_system_actor_needs_no_grant_but_still_obeys_the_boundary(
        self, vault
    ) -> None:
        """The §17 stamping path is a system operation, not an agent capability."""
        actor = WriteActor.system("nexus_id stamping")
        assert (
            await self.auth.authorize_actor_async(COMPANY_A, actor, "Knowledge/A.md")
            == "Knowledge/A.md"
        )
        with pytest.raises(VaultSecurityError):
            await self.auth.authorize_actor_async(COMPANY_A, actor, "../escape.md")

    async def test_an_operator_actor_behaves_the_same(self, vault) -> None:
        actor = WriteActor.operator(uuid.uuid4())
        assert await self.auth.authorize_actor_async(COMPANY_A, actor, "A.md") == "A.md"

    async def test_an_agent_actor_goes_through_the_full_chain(self, vault) -> None:
        actor = WriteActor.agent(self.agent)
        with pytest.raises(VaultAuthorizationError):
            await self.auth.authorize_actor_async(COMPANY_A, actor, "Projects/P.md", self.tool)

        await self.registry.grant_access(COMPANY_A, self.agent, self.tool)
        await self.auth.grant_async(COMPANY_A, self.agent, self.tool, "Projects")
        assert (
            await self.auth.authorize_actor_async(COMPANY_A, actor, "Projects/P.md", self.tool)
            == "Projects/P.md"
        )

    async def test_an_agent_actor_without_a_tool_is_refused(self, vault) -> None:
        with pytest.raises(VaultAuthorizationError):
            await self.auth.authorize_actor_async(COMPANY_A, WriteActor.agent(self.agent), "A.md")


# ---------------------------------------------------------------------------
# 5. Audit identity
# ---------------------------------------------------------------------------


class TestWriteActor:
    """Attribution without inventing an agent to satisfy a foreign key."""

    async def test_an_agent_actor_carries_its_agent(self) -> None:
        agent_id = uuid.uuid4()
        actor = WriteActor.agent(agent_id)
        assert actor.kind == ACTOR_AGENT
        assert actor.is_agent is True
        assert actor.audit_fields()["actor_agent_id"] == str(agent_id)

    async def test_a_system_actor_has_no_agent_and_needs_a_reason(self) -> None:
        actor = WriteActor.system("nexus_id stamping")
        assert actor.kind == ACTOR_SYSTEM
        assert actor.agent_id is None
        assert actor.is_agent is False
        assert actor.audit_fields()["actor_reason"] == "nexus_id stamping"

    async def test_an_operator_actor_carries_the_human(self) -> None:
        user_id = uuid.uuid4()
        actor = WriteActor.operator(user_id)
        assert actor.kind == ACTOR_OPERATOR
        assert actor.agent_id is None
        assert actor.audit_fields()["actor_user_id"] == str(user_id)

    async def test_a_system_write_cannot_be_attributed_to_an_agent(self) -> None:
        """The whole reason the abstraction exists."""
        with pytest.raises(ActorError):
            WriteActor(kind=ACTOR_SYSTEM, agent_id=uuid.uuid4(), reason="stamping")

    async def test_an_agent_actor_without_an_agent_is_rejected(self) -> None:
        with pytest.raises(ActorError):
            WriteActor(kind=ACTOR_AGENT)

    async def test_a_system_actor_without_a_reason_is_rejected(self) -> None:
        """"The system did it" is the answer that makes an audit useless."""
        with pytest.raises(ActorError):
            WriteActor(kind=ACTOR_SYSTEM)

    async def test_an_unknown_kind_is_rejected(self) -> None:
        with pytest.raises(ActorError):
            WriteActor(kind="daemon")

    async def test_there_is_no_default_actor(self) -> None:
        """A write is never anonymous: the kind has to be stated."""
        with pytest.raises(TypeError):
            WriteActor()  # type: ignore[call-arg]

    async def test_no_fake_agent_row_is_introduced(self) -> None:
        """A system actor must not be backed by a row in ``agents``."""
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "nexus"
            / "obsidian"
            / "actor.py"
        ).read_text(encoding="utf-8")
        assert "Agent(" not in source
        assert "agents" not in source.split('"""', 2)[-1]

    async def test_audit_fields_carry_no_path_or_content(self) -> None:
        actor = WriteActor.system("stamping Knowledge/Secret Plan.md")
        fields = actor.audit_fields()
        # A reason is author-supplied, so it is truncated but not parsed; what
        # matters is that no field is derived from a filesystem location.
        assert set(fields) <= {
            "actor_kind",
            "actor_agent_id",
            "actor_user_id",
            "actor_reason",
        }
        assert "C:\\" not in " ".join(fields.values())

    async def test_a_long_reason_is_truncated(self) -> None:
        actor = WriteActor.system("x" * 500)
        assert len(actor.audit_fields()["actor_reason"]) == 200

    async def test_each_kind_describes_itself(self) -> None:
        assert "agent" in WriteActor.agent(uuid.uuid4()).describe()
        assert "system" in WriteActor.system("stamping").describe()
        assert WriteActor.operator().describe() == "operator"


# ---------------------------------------------------------------------------
# 8. Precondition modules remain write-free
# ---------------------------------------------------------------------------


def test_no_precondition_module_writes_to_a_note() -> None:
    """A gate must not be able to perform the thing it gates.

    ``portability.py`` is the one exception, and deliberately: restoring an
    archive is a file write by definition. It is excluded here and covered by its
    own boundary tests above.
    """
    package = Path(__file__).resolve().parents[1] / "src" / "nexus" / "obsidian"
    for name in ("secret_scan", "authorization", "actor", "vault_git"):
        source = (package / f"{name}.py").read_text(encoding="utf-8")
        body = source.split('"""', 2)[-1]
        for forbidden in ("write_text(", "write_bytes(", "os.replace(", "open("):
            assert forbidden not in body, f"{name}.py can write: {forbidden}"


def test_the_read_only_indexer_path_is_unchanged() -> None:
    """Nothing in this phase gave the existing pipeline a write surface."""
    package = Path(__file__).resolve().parents[1] / "src" / "nexus" / "obsidian"
    for name in ("indexer", "scanner", "provider", "frontmatter", "security", "wikilinks"):
        source = (package / f"{name}.py").read_text(encoding="utf-8")
        for forbidden in ("write_text(", "write_bytes(", "os.replace("):
            assert forbidden not in source, f"{name}.py gained a write call"
