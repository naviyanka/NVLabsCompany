"""Tests for the read-only Obsidian vault surface (ADR 0002 Phase 1).

Covers the six §20 security controls, frontmatter extraction, the read-only
provider, and the §21 embedding-dimension gate. The security tests are the point
of this file: nothing else in NEXUS validates filesystem paths, and this module
is the only sanctioned way to reach a vault file.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from nexus.obsidian import (
    EmbeddingPolicyError,
    ObsidianReader,
    VaultBoundaryError,
    VaultConfigurationError,
    VaultExtensionError,
    VaultFileTooLargeError,
    VaultNotConfiguredError,
    company_vault_root,
    content_hash,
    is_allowed_extension,
    parse_note,
    resolve_note_path,
    validate_embedding_policy,
    validate_vault_root,
)

COMPANY_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
COMPANY_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def vault(tmp_path: Path):
    """Configure a vault root under tmp_path with one company vault created."""
    root = tmp_path / "vaults"
    (root / str(COMPANY_A) / "Knowledge").mkdir(parents=True)
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = str(root)
        mock_settings.obsidian_max_note_bytes = 1_048_576
        yield root, mock_settings


# ---------------------------------------------------------------------------
# §20 control 6 — tenant isolation
# ---------------------------------------------------------------------------


def test_company_root_is_derived_from_company_id(vault) -> None:
    """Each company's root is its own subtree, not a caller-supplied path."""
    root, _ = vault
    assert company_vault_root(COMPANY_A) == (root / str(COMPANY_A)).resolve()
    assert company_vault_root(COMPANY_A) != company_vault_root(COMPANY_B)


def test_cross_tenant_path_is_refused(vault) -> None:
    """A path climbing into another company's vault is refused, not served."""
    root, _ = vault
    (root / str(COMPANY_B)).mkdir(parents=True)
    (root / str(COMPANY_B) / "Secret.md").write_text("other tenant", encoding="utf-8")

    with pytest.raises(VaultBoundaryError):
        resolve_note_path(COMPANY_A, f"../{COMPANY_B}/Secret.md")


def test_unconfigured_vault_refuses_every_path() -> None:
    """With no vault root configured, no path can be produced at all."""
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = ""
        with pytest.raises(VaultNotConfiguredError):
            resolve_note_path(COMPANY_A, "Knowledge/Note.md")


# ---------------------------------------------------------------------------
# §20 controls 1 and 2 — vault boundary and path traversal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hostile_id", ["../../Windows", "..", "not-a-uuid", ""])
def test_non_uuid_company_id_is_refused(vault, hostile_id: str) -> None:
    """company_id is interpolated into a path, so it is validated, not trusted.

    The type annotation is not a runtime guard: a string company id reaching this
    boundary would otherwise walk straight out of the vault root.
    """
    with pytest.raises(VaultBoundaryError):
        company_vault_root(hostile_id)  # type: ignore[arg-type]
    with pytest.raises(VaultBoundaryError):
        resolve_note_path(hostile_id, "Note.md")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "hostile",
    [
        "../outside.md",
        "../../outside.md",
        "Knowledge/../../outside.md",
        "Knowledge/../../../etc/passwd.md",
        "./../outside.md",
    ],
)
def test_traversal_is_refused(vault, hostile: str) -> None:
    """Every ..-based escape is refused rather than clamped to the root."""
    with pytest.raises(VaultBoundaryError):
        resolve_note_path(COMPANY_A, hostile)


def test_absolute_path_is_refused(vault, tmp_path: Path) -> None:
    """An absolute path would ignore the root entirely, so it is refused."""
    outside = tmp_path / "elsewhere.md"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(VaultBoundaryError):
        resolve_note_path(COMPANY_A, str(outside))


def test_path_inside_vault_resolves(vault) -> None:
    """A well-formed relative path resolves under the company root."""
    root, _ = vault
    resolved = resolve_note_path(COMPANY_A, "Knowledge/Note.md")
    assert resolved == (root / str(COMPANY_A) / "Knowledge" / "Note.md").resolve()


def test_interior_dotdot_that_stays_inside_is_allowed(vault) -> None:
    """.. is not banned outright — only escaping the root is."""
    root, _ = vault
    resolved = resolve_note_path(COMPANY_A, "Knowledge/../Note.md")
    assert resolved == (root / str(COMPANY_A) / "Note.md").resolve()


# ---------------------------------------------------------------------------
# §20 control 3 — symlinks
# ---------------------------------------------------------------------------


def test_symlink_escaping_vault_is_refused(vault, tmp_path: Path) -> None:
    """A link inside the vault pointing outside it is refused, not followed."""
    root, _ = vault
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")

    link = root / str(COMPANY_A) / "Knowledge" / "Escape.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")

    with pytest.raises(VaultBoundaryError):
        resolve_note_path(COMPANY_A, "Knowledge/Escape.md")


def test_symlink_inside_vault_is_allowed(vault) -> None:
    """A link whose target stays inside the vault is fine."""
    root, _ = vault
    company = root / str(COMPANY_A)
    target = company / "Knowledge" / "Real.md"
    target.write_text("body", encoding="utf-8")

    link = company / "Alias.md"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")

    assert resolve_note_path(COMPANY_A, "Alias.md") == target.resolve()


# ---------------------------------------------------------------------------
# §20 control 4 — extension allowlist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["Knowledge/Note.txt", "Knowledge/script.py", "Knowledge/data.json", "Knowledge/Note"]
)
def test_non_markdown_extension_is_refused(vault, path: str) -> None:
    """Only .md is indexable; anything else is refused."""
    with pytest.raises(VaultExtensionError):
        resolve_note_path(COMPANY_A, path)


def test_extension_check_is_case_insensitive(vault) -> None:
    """A .MD file from another platform is still Markdown."""
    assert resolve_note_path(COMPANY_A, "Knowledge/Note.MD").suffix == ".MD"
    assert is_allowed_extension("x.Md")
    assert not is_allowed_extension("x.txt")


# ---------------------------------------------------------------------------
# §20 control 5 — size limit
# ---------------------------------------------------------------------------


def test_oversized_note_is_refused_before_read(vault) -> None:
    """The cap is enforced on stat, so an oversized file is never loaded."""
    root, mock_settings = vault
    mock_settings.obsidian_max_note_bytes = 16

    note = root / str(COMPANY_A) / "Knowledge" / "Big.md"
    note.write_text("x" * 100, encoding="utf-8")

    reader = ObsidianReader(COMPANY_A)
    with pytest.raises(VaultFileTooLargeError):
        reader.read_note("Knowledge/Big.md")


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------


def test_frontmatter_is_extracted_and_body_excludes_it() -> None:
    """Metadata parses, and the body starts after the closing delimiter."""
    parsed = parse_note(
        "---\n"
        "nexus_id: 3f2a\n"
        "type: knowledge\n"
        "title: SSRF Protection\n"
        "tags:\n"
        "  - security\n"
        "---\n"
        "# SSRF Protection\n\nBody text.\n"
    )
    assert parsed.nexus_id == "3f2a"
    assert parsed.doc_type == "knowledge"
    assert parsed.title == "SSRF Protection"
    assert parsed.metadata["tags"] == ["security"]
    assert "nexus_id" not in parsed.body
    assert parsed.body.startswith("# SSRF Protection")


def test_note_without_frontmatter_is_all_body() -> None:
    """A hand-written note with no metadata block is still readable."""
    parsed = parse_note("# Just a note\n\nNo metadata here.\n")
    assert parsed.metadata == {}
    assert parsed.nexus_id is None
    assert parsed.body.startswith("# Just a note")


def test_horizontal_rule_is_not_mistaken_for_frontmatter() -> None:
    """An opening --- with no close is content, not a metadata block."""
    content = "---\n\nJust a rule, no closing delimiter here.\n"
    parsed = parse_note(content)
    assert parsed.metadata == {}
    assert parsed.body == content


def test_malformed_yaml_yields_empty_metadata_not_an_exception() -> None:
    """One bad note must not fail a whole vault scan."""
    parsed = parse_note("---\nnexus_id: [unclosed\n---\nBody.\n")
    assert parsed.metadata == {}
    assert parsed.body == "Body.\n"


def test_non_mapping_frontmatter_yields_empty_metadata() -> None:
    """A YAML list where a mapping was expected is ignored, body preserved."""
    parsed = parse_note("---\n- a\n- b\n---\nBody.\n")
    assert parsed.metadata == {}
    assert parsed.body == "Body.\n"


@pytest.mark.parametrize("depth", [500, 10_000])
def test_deeply_nested_yaml_does_not_abort_the_scan(depth: int) -> None:
    """PyYAML recurses per nesting level, so a small note can raise RecursionError.

    A 1 KB note of 500 nested brackets is far under the size cap. Catching only
    yaml.YAMLError would let one such note abort a whole vault scan.
    """
    note = "---\na: " + "[" * depth + "]" * depth + "\n---\nbody\n"
    assert len(note.encode("utf-8")) < 1_048_576  # under the size cap
    parsed = parse_note(note)
    assert parsed.metadata == {}
    assert parsed.body == "body\n"


def test_yaml_alias_amplification_is_refused() -> None:
    """Aliases expand multiplicatively, which the size cap cannot bound.

    This 190-byte block expands to roughly 580 KB of objects under plain
    safe_load, and each further nesting level multiplies by ten.
    """
    bomb = (
        "---\n"
        "a: &a [x,x,x,x,x,x,x,x,x,x]\n"
        "b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a,*a]\n"
        "c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b,*b]\n"
        "d: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c,*c]\n"
        "e: [*d,*d,*d,*d,*d,*d,*d,*d,*d,*d]\n"
        "---\nbody\n"
    )
    parsed = parse_note(bomb)
    assert parsed.metadata == {}
    assert parsed.body == "body\n"


def test_empty_content_parses() -> None:
    """An empty file is empty, not an error."""
    parsed = parse_note("")
    assert parsed.metadata == {}
    assert parsed.body == ""


# ---------------------------------------------------------------------------
# Read-only provider
# ---------------------------------------------------------------------------


def test_list_notes_finds_markdown_recursively_and_skips_the_rest(vault) -> None:
    """Markdown at any depth is listed; other files and dot-dirs are skipped."""
    root, _ = vault
    company = root / str(COMPANY_A)
    (company / "Knowledge" / "A.md").write_text("a", encoding="utf-8")
    (company / "Knowledge" / "Nested").mkdir()
    (company / "Knowledge" / "Nested" / "B.md").write_text("b", encoding="utf-8")
    (company / "Knowledge" / "notes.txt").write_text("skip", encoding="utf-8")
    (company / ".obsidian").mkdir()
    (company / ".obsidian" / "workspace.md").write_text("editor state", encoding="utf-8")

    paths = [ref.vault_path for ref in ObsidianReader(COMPANY_A).list_notes()]
    assert paths == ["Knowledge/A.md", "Knowledge/Nested/B.md"]


def test_list_notes_on_absent_vault_returns_empty(vault) -> None:
    """A configured-but-uncreated vault is a normal state, not an error."""
    reader = ObsidianReader(COMPANY_B)
    assert reader.exists() is False
    assert reader.list_notes() == []


def test_list_notes_omits_entries_pointing_outside_the_vault(vault, tmp_path: Path) -> None:
    """Listing applies the same boundary as reading.

    Without this, a symlink or junction inside the vault pointing at another
    company's vault would leak its target's filename, size, and mtime here, even
    though the later read is correctly refused.
    """
    root, _ = vault
    (root / str(COMPANY_B) / "Deals").mkdir(parents=True)
    (root / str(COMPANY_B) / "Deals" / "Acquisition.md").write_text(
        "confidential", encoding="utf-8"
    )
    (root / str(COMPANY_A) / "Knowledge" / "Mine.md").write_text("ok", encoding="utf-8")

    link = root / str(COMPANY_A) / "Peek.md"
    try:
        link.symlink_to(root / str(COMPANY_B) / "Deals" / "Acquisition.md")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")

    paths = [ref.vault_path for ref in ObsidianReader(COMPANY_A).list_notes()]
    assert paths == ["Knowledge/Mine.md"]


def test_read_note_returns_parsed_body_hash_and_mtime(vault) -> None:
    """A read yields frontmatter, body, and a hash usable for change detection."""
    root, _ = vault
    text = "---\ntype: decision\n---\nWe chose Temporal.\n"
    # newline="" so the on-disk byte count matches `text` on Windows, where
    # write_text would otherwise translate \n to \r\n. The content hash is
    # computed over the newline-normalized read, so it is unaffected either way.
    (root / str(COMPANY_A) / "Knowledge" / "ADR.md").write_text(
        text, encoding="utf-8", newline=""
    )

    note = ObsidianReader(COMPANY_A).read_note("Knowledge/ADR.md")
    assert note.vault_path == "Knowledge/ADR.md"
    assert note.parsed.doc_type == "decision"
    assert note.parsed.body.strip() == "We chose Temporal."
    assert note.content_hash == content_hash(text)
    assert note.mtime.tzinfo is None  # naive UTC, matching the model columns
    assert note.size_bytes == len(text.encode("utf-8"))


def test_content_hash_changes_with_content(vault) -> None:
    """Change detection depends on the hash actually tracking the body."""
    assert content_hash("a") != content_hash("b")
    assert content_hash("a") == content_hash("a")


def test_missing_note_raises_file_not_found(vault) -> None:
    """A path that passes validation but does not exist is a plain miss."""
    with pytest.raises(FileNotFoundError):
        ObsidianReader(COMPANY_A).read_note("Knowledge/Absent.md")


def test_reader_cannot_reach_another_tenants_note(vault) -> None:
    """A reader is bound to one company for its whole lifetime."""
    root, _ = vault
    (root / str(COMPANY_B)).mkdir(parents=True)
    (root / str(COMPANY_B) / "Secret.md").write_text("other", encoding="utf-8")

    with pytest.raises(VaultBoundaryError):
        ObsidianReader(COMPANY_A).read_note(f"../{COMPANY_B}/Secret.md")


def test_provider_exposes_no_write_surface() -> None:
    """Phase 1 is read-only (ADR 0002 §23): no mutating method may exist."""
    forbidden = {"write", "write_note", "create", "create_note", "update",
                 "update_note", "append", "append_note", "move", "move_note",
                 "delete", "delete_note", "save"}
    assert forbidden.isdisjoint(dir(ObsidianReader))


# ---------------------------------------------------------------------------
# §21 embedding dimension policy
# ---------------------------------------------------------------------------


def test_embedding_policy_ignores_a_disabled_vault() -> None:
    """With no vault configured, an existing deployment is unaffected."""
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = ""
        with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "ollama"}):
            validate_embedding_policy()  # must not raise


def test_embedding_policy_rejects_wrong_dimension(tmp_path: Path) -> None:
    """A vault plus a 768-dim provider refuses to start (ADR 0002 §21)."""
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = str(tmp_path)
        with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "ollama"}):
            with pytest.raises(EmbeddingPolicyError, match="768"):
                validate_embedding_policy()


def test_embedding_policy_accepts_1536_dimension(tmp_path: Path) -> None:
    """The OpenAI small model is the sanctioned provider for the vault."""
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = str(tmp_path)
        with patch.dict(
            os.environ,
            {
                "EMBEDDING_PROVIDER": "openai",
                "OPENAI_EMBED_MODEL": "text-embedding-3-small",
            },
        ):
            validate_embedding_policy()  # must not raise


def test_embedding_policy_allows_no_provider(tmp_path: Path) -> None:
    """No provider means keyword-only search — visible, not silent degradation."""
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = str(tmp_path)
        with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "none"}):
            validate_embedding_policy()  # must not raise


# ---------------------------------------------------------------------------
# Vault root startup validation
# ---------------------------------------------------------------------------


def test_disabled_vault_validates_to_none() -> None:
    """Unset means deliberately off, which is the default and not an error."""
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = ""
        assert validate_vault_root() is None


def test_nonexistent_vault_root_fails_explicitly(tmp_path: Path) -> None:
    """A typo must not resolve to a silently empty vault forever."""
    missing = tmp_path / "does-not-exist"
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = str(missing)
        mock_settings.obsidian_max_note_bytes = 1_048_576
        with pytest.raises(VaultConfigurationError, match="cannot be resolved"):
            validate_vault_root()


def test_vault_root_pointing_at_a_file_fails(tmp_path: Path) -> None:
    """The root holds one subdirectory per company, so it must be a directory."""
    not_a_dir = tmp_path / "vault.md"
    not_a_dir.write_text("x", encoding="utf-8")
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = str(not_a_dir)
        mock_settings.obsidian_max_note_bytes = 1_048_576
        with pytest.raises(VaultConfigurationError, match="not a directory"):
            validate_vault_root()


def test_valid_vault_root_returns_resolved_path(tmp_path: Path) -> None:
    """A real directory validates and comes back canonicalized."""
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = str(tmp_path)
        mock_settings.obsidian_max_note_bytes = 1_048_576
        assert validate_vault_root() == tmp_path.resolve()


@pytest.mark.parametrize("bad_limit", [0, -1, "big"])
def test_non_positive_note_size_limit_fails(tmp_path: Path, bad_limit: object) -> None:
    """A zero or negative cap would refuse every note; catch it at startup."""
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = str(tmp_path)
        mock_settings.obsidian_max_note_bytes = bad_limit
        with pytest.raises(VaultConfigurationError, match="positive integer"):
            validate_vault_root()
