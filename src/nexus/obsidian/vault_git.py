"""Vault Git inspection and the rollback contract (ADR 0002 §18, §20 control 12).

The vault is a **separate** Git repository from the application (§18): nesting it
inside `NVLabsCompany/` would put knowledge into application commits and
application history into knowledge diffs. So this module never assumes the two
share a repository, and it refuses to treat the application's own `.git` as the
vault's — an ancestor repository is reported as *absent*, not as the vault's
history.

**This module does not write.** It reads Git state and reports it. Even
`git init` is deliberately absent: the development vault must not be initialized
by a code path that runs on import or on a health check, and a repository the
operator did not create is not one they will remember to push. Tests build their
own temporary repositories.

## The rollback contract

Three stores are involved in one logical write, and they cannot be one
transaction:

    filesystem   the note bytes
    Git          the version history
    PostgreSQL   obsidian_documents identity and index state

`os.replace` makes the *file* write atomic — a reader sees the old bytes or the
new ones, never a partial file. Nothing makes the three consistent together.
So the order is chosen to make every failure recoverable, and the recovery is
named:

1. **Scan, authorize, check the hash.** All refusals happen here, before
   anything changes. A failure leaves nothing to undo.
2. **Write the file** (`os.replace`). If this fails, nothing changed: the
   temporary file is discarded and the note keeps its previous bytes.
3. **Record in PostgreSQL.** If this fails, the file is newer than the row. The
   row still holds the *previous* `content_hash`, so the next scan sees a hash
   mismatch and marks the note stale — the ordinary "changed outside NEXUS" path.
   Self-healing, no operator action.
4. **Commit to Git.** If this fails, the file and the row agree and the change is
   simply uncommitted: it shows up as a dirty working tree, which is exactly what
   a human editing the vault in Obsidian also produces. Recovery is a commit,
   which the operator or a later pass can make. No data is lost, because the
   bytes are on disk.

Git last, because a commit is the only step that cannot be inferred from the
others. Reversing it — commit before write — would let history claim a change the
filesystem does not have.

**What rollback means here.** `git revert` (control 12) restores note *content*
from history. It does not touch `obsidian_documents`: after a revert the file
hash no longer matches the row, so the next scan marks the note stale and the
indexer re-derives chunks from the reverted content. That is the whole recovery
path, and it works precisely because PostgreSQL holds only derived state plus
identity, never the sole copy of the body (§7).

**Uncommitted local changes are never discarded.** A dirty working tree means a
human is mid-edit. `git revert` is refused in that state rather than run with
`--force`, because the alternative is destroying work that exists nowhere else.
"""

from __future__ import annotations

import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from nexus.obsidian.security import company_vault_root

logger = logging.getLogger(__name__)

# Repository states.
GIT_ABSENT = "absent"
GIT_CLEAN = "clean"
GIT_DIRTY = "dirty"
GIT_UNAVAILABLE = "unavailable"
GIT_ERROR = "error"

# A Git call on a local repository is milliseconds. This bound exists so a health
# check cannot hang on a wedged index lock.
GIT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class VaultGitStatus:
    """Git state of one company's vault.

    Attributes:
        state: ``absent`` (no repository at the vault root), ``clean``,
            ``dirty`` (uncommitted changes), ``unavailable`` (no git binary), or
            ``error``.
        head: Short commit id of HEAD, empty when there is none — an
            initialized repository with no commits yet is ``clean`` with no head.
        dirty_paths: Vault-relative paths with uncommitted changes, capped.
            Vault-relative deliberately: a status is surfaced to operators, and
            the vault root is host layout.
        detail: A short client-safe explanation.
    """

    state: str
    head: str = ""
    dirty_paths: tuple[str, ...] = field(default_factory=tuple)
    detail: str = ""

    @property
    def versioned(self) -> bool:
        """Whether this vault has usable version history."""
        return self.state in (GIT_CLEAN, GIT_DIRTY)

    @property
    def revert_available(self) -> bool:
        """Whether a revert-based rollback could run right now.

        A dirty tree is excluded: reverting over uncommitted human edits would
        destroy work that exists in no other store.
        """
        return self.state == GIT_CLEAN and bool(self.head)


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one git command in ``repo``, without a shell.

    Arguments are passed as a list, so a path containing a space or a quote is
    an argument rather than shell syntax.
    """
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, no user-built string
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )


def is_repository_root(path: Path) -> bool:
    """Whether ``path`` itself is a Git repository root.

    Deliberately not "is inside a repository": the application repository is an
    ancestor of the development vault, and `git rev-parse` from inside the vault
    would happily report *that* repository. Treating it as the vault's history
    would put knowledge commits into application history, which §18 exists to
    prevent. A `.git` file is accepted alongside a directory, so a worktree or a
    submodule checkout counts.
    """
    entry = path / ".git"
    return entry.is_dir() or entry.is_file()


def vault_git_status(company_id: uuid.UUID) -> VaultGitStatus:
    """Report the Git state of one company's vault.

    Read-only. Never initializes a repository: a vault the operator did not put
    under version control is reported as ``absent`` so the condition is visible,
    rather than silently fixed with a repository nobody knows to push.

    Args:
        company_id: The company whose vault to inspect.

    Returns:
        A :class:`VaultGitStatus`. Never raises for a missing vault, a missing
        repository or a missing git binary — each is a state, not an error.
    """
    try:
        root = company_vault_root(company_id)
    except Exception as exc:  # noqa: BLE001 - an unconfigured vault is a state
        return VaultGitStatus(
            state=GIT_ABSENT, detail=f"Vault root unavailable: {type(exc).__name__}"
        )

    if not root.is_dir():
        return VaultGitStatus(state=GIT_ABSENT, detail="No vault directory for this company.")
    if not is_repository_root(root):
        return VaultGitStatus(
            state=GIT_ABSENT,
            detail="The vault is not a Git repository, so it has no version history.",
        )

    try:
        status = _run_git(root, "status", "--porcelain")
        if status.returncode != 0:
            return VaultGitStatus(state=GIT_ERROR, detail="git status failed.")

        head = _run_git(root, "rev-parse", "--short", "HEAD")
        # A fresh repository with no commits exits non-zero here, which is not an
        # error: it has no head yet.
        head_id = head.stdout.strip() if head.returncode == 0 else ""

        lines = [line for line in status.stdout.splitlines() if line.strip()]
        # Porcelain v1 is "XY path"; a rename is "XY old -> new" and the new name
        # is the one that exists now.
        dirty = tuple(
            line[3:].split(" -> ")[-1].strip().strip('"').replace("\\", "/")
            for line in lines[:50]
        )
        if dirty:
            return VaultGitStatus(
                state=GIT_DIRTY,
                head=head_id,
                dirty_paths=dirty,
                detail="The vault has uncommitted changes.",
            )
        return VaultGitStatus(state=GIT_CLEAN, head=head_id)
    except FileNotFoundError:
        return VaultGitStatus(
            state=GIT_UNAVAILABLE, detail="git is not installed on this host."
        )
    except subprocess.TimeoutExpired:
        return VaultGitStatus(state=GIT_ERROR, detail="git did not respond in time.")
    except Exception as exc:  # noqa: BLE001 - a status probe must not raise
        logger.exception("Vault Git status failed for company %s", company_id)
        return VaultGitStatus(state=GIT_ERROR, detail=f"git failed: {type(exc).__name__}")


def rollback_plan(status: VaultGitStatus) -> str:
    """The recovery a given Git state supports, as an operator-facing sentence.

    Kept next to the status it describes so the rollback story cannot drift from
    what the repository can actually do.
    """
    if status.state == GIT_ABSENT:
        return (
            "No version history: content rollback is unavailable until the vault is "
            "a Git repository. Initialize and commit it before enabling writes."
        )
    if status.state == GIT_UNAVAILABLE:
        return "git is not installed, so rollback cannot be performed on this host."
    if status.state == GIT_ERROR:
        return "Git state could not be determined, so no rollback should be attempted."
    if status.state == GIT_DIRTY:
        return (
            "Uncommitted changes are present. Commit or stash them first — a revert "
            "now would discard edits that exist nowhere else."
        )
    if not status.head:
        return (
            "The repository has no commits yet, so there is nothing to revert to. "
            "Make an initial commit before enabling writes."
        )
    return (
        "Revert the offending commit in the vault repository. The next scan sees the "
        "restored content as a hash change and reindexes it; obsidian_documents needs "
        "no manual repair."
    )
