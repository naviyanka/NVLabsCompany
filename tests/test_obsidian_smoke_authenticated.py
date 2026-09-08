"""Authenticated black-box smoke test for the Obsidian endpoints (Phase 1B-3C).

Skipped unless an operator supplies real credentials, so the normal suite never
depends on a key, a running server, or an external service:

    NEXUS_SMOKE_API_KEY   an API key for a real company (required)
    NEXUS_SMOKE_BASE_URL  API root, default http://127.0.0.1:8000
    NEXUS_SMOKE_VAULT_DIR the company's vault directory on the SERVER's disk,
                          i.e. <obsidian_vault_root>/<company_id> (required)
    NEXUS_SMOKE_OTHER_API_KEY  a second company's key, to prove isolation
                               (optional; that check is skipped without it)

This drives the real authentication path — a bearer token through the normal
middleware — rather than overriding the dependency, so what it proves includes
that the tenant scope comes from the key. The key is never printed, never logged,
and never written to a file.

Run it explicitly:

    NEXUS_SMOKE_API_KEY=... NEXUS_SMOKE_VAULT_DIR=... \\
      python -m pytest tests/test_obsidian_smoke_authenticated.py -v
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import httpx
import pytest

API_KEY = os.environ.get("NEXUS_SMOKE_API_KEY", "")
OTHER_API_KEY = os.environ.get("NEXUS_SMOKE_OTHER_API_KEY", "")
BASE_URL = os.environ.get("NEXUS_SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
VAULT_DIR = os.environ.get("NEXUS_SMOKE_VAULT_DIR", "")

pytestmark = [
    pytest.mark.skipif(
        not API_KEY or not VAULT_DIR,
        reason=(
            "authenticated smoke test needs NEXUS_SMOKE_API_KEY and "
            "NEXUS_SMOKE_VAULT_DIR; skipped so the normal suite stays offline"
        ),
    ),
]

# Unique per run, so a repeat cannot pass on a previous run's leftovers.
SENTINEL = f"NEXUS_SMOKE_SENTINEL_{uuid.uuid4().hex[:12].upper()}"
FRONTMATTER_SENTINEL = f"SMOKE_FRONTMATTER_{uuid.uuid4().hex[:8].upper()}"
NOTE_NAME = f"_smoke_{uuid.uuid4().hex[:8]}.md"
NOTE_BODY = (
    f"---\ntitle: {FRONTMATTER_SENTINEL}\ntype: knowledge\n---\n"
    f"# Smoke\n\nThis note exists only for a smoke test and holds {SENTINEL}.\n"
)


@pytest.fixture(scope="module")
def note() -> Path:
    """Place a sentinel note in the vault, and remove it afterwards."""
    vault = Path(VAULT_DIR)
    if not vault.is_dir():
        pytest.skip(f"NEXUS_SMOKE_VAULT_DIR is not a directory: {vault}")
    path = vault / NOTE_NAME
    path.write_text(NOTE_BODY, encoding="utf-8")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    """An authenticated client. The key stays in the header, out of the output."""
    with httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=60.0,
    ) as http:
        try:
            http.get("/api/v1/integrations/obsidian/status")
        except httpx.HTTPError as exc:
            pytest.skip(f"no API at {BASE_URL}: {type(exc).__name__}")
        yield http


def _assert_no_key_leak(text: str) -> None:
    """A response must never echo the credential back."""
    assert API_KEY not in text
    if OTHER_API_KEY:
        assert OTHER_API_KEY not in text


def _company_id(http: httpx.Client) -> str:
    """The authenticated company, per the server — not a value the test picked."""
    response = http.get("/api/v1/integrations/obsidian/status")
    assert response.status_code == 200, response.text
    return str(response.json()["company_id"])


def test_authentication_succeeds_and_scopes_the_company(client) -> None:
    """1-2: the key authenticates, and identity comes from it, not from input."""
    response = client.get("/api/v1/integrations/obsidian/status")
    assert response.status_code == 200, response.text
    _assert_no_key_leak(response.text)

    body = response.json()
    assert body["state"] in {"not_configured", "available", "unavailable"}
    if body["state"] == "not_configured":
        pytest.skip("the server has no obsidian_vault_root configured")

    # 8: the absolute vault root is never disclosed.
    assert "vault_root" not in body
    assert VAULT_DIR not in response.text


def test_unauthenticated_request_is_rejected() -> None:
    """The endpoints are not open: no credential, no answer."""
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as anon:
        try:
            response = anon.post("/api/v1/integrations/obsidian/scan")
        except httpx.HTTPError as exc:
            pytest.skip(f"no API at {BASE_URL}: {type(exc).__name__}")
    assert response.status_code in (401, 403), response.text


def test_scan_then_index_then_retrieve(client, note) -> None:
    """3-6: scan finds the note, index processes it, RAG retrieves it, labelled."""
    scan = client.post("/api/v1/integrations/obsidian/scan")
    assert scan.status_code == 200, scan.text
    _assert_no_key_leak(scan.text)
    scanned = scan.json()
    seen = set(scanned["created"]) | set(scanned["updated"]) | set(scanned["unchanged"])
    assert NOTE_NAME in seen, f"scan did not discover the note: {scanned['counts']}"
    # Relative paths only.
    for path in scanned["created"]:
        assert not Path(path).is_absolute()
    assert VAULT_DIR not in scan.text

    index = client.post("/api/v1/integrations/obsidian/index")
    assert index.status_code == 200, index.text
    _assert_no_key_leak(index.text)
    indexed = index.json()
    processed = set(indexed["indexed"]) | set(indexed["partial"])
    assert NOTE_NAME in processed or not indexed["failed"], (
        f"index did not process the note: {indexed}"
    )
    assert VAULT_DIR not in index.text

    # The company comes from status, which echoes back the credential's own
    # company — never a value this test chose.
    search = client.post(
        f"/api/v1/companies/{_company_id(client)}/knowledge/search",
        json={"query": SENTINEL, "top_k": 10},
    )
    assert search.status_code == 200, search.text
    _assert_no_key_leak(search.text)

    hits = [hit for hit in search.json() if SENTINEL in hit["content"]]
    assert hits, f"the sentinel was not retrievable: {search.text[:400]}"
    hit = hits[0]
    # 6: provenance identifies the Obsidian source explicitly.
    assert hit["source_type"] == "obsidian_document"
    assert hit["source_id"] == hit["page_id"]


def test_frontmatter_is_not_retrievable(client, note) -> None:
    """Metadata must not become searchable text, over the real API."""
    client.post("/api/v1/integrations/obsidian/scan")
    client.post("/api/v1/integrations/obsidian/index")

    search = client.post(
        f"/api/v1/companies/{_company_id(client)}/knowledge/search",
        json={"query": FRONTMATTER_SENTINEL, "top_k": 10},
    )
    assert search.status_code == 200, search.text

    assert [h for h in search.json() if FRONTMATTER_SENTINEL in h["content"]] == []


@pytest.mark.skipif(
    not OTHER_API_KEY,
    reason="tenant-isolation leg needs NEXUS_SMOKE_OTHER_API_KEY",
)
def test_another_company_cannot_retrieve_the_note(client, note) -> None:
    """7: a second company's key must not reach the first company's content."""
    client.post("/api/v1/integrations/obsidian/scan")
    client.post("/api/v1/integrations/obsidian/index")

    with httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {OTHER_API_KEY}"},
        timeout=60.0,
    ) as other:
        other_company = _company_id(other)
        search = other.post(
            f"/api/v1/companies/{other_company}/knowledge/search",
            json={"query": SENTINEL, "top_k": 10},
        )

    if search.status_code == 403:
        return  # authorization refused outright, which is a stronger pass
    assert search.status_code == 200, search.text
    assert [h for h in search.json() if SENTINEL in h["content"]] == [], (
        "another company retrieved this company's vault content"
    )


def test_endpoints_ignore_client_supplied_scope(client) -> None:
    """Part E: company_id, vault_root and vault_path are not client inputs."""
    foreign = uuid.uuid4()
    response = client.post(
        "/api/v1/integrations/obsidian/scan",
        json={
            "company_id": str(foreign),
            "vault_root": "/tmp/attacker",
            "vault_path": "../../../etc/passwd",
        },
    )
    # The body is ignored (200) or rejected (409/422); what must not happen is the
    # scan acting on the supplied scope.
    assert response.status_code in (200, 409, 422), response.text
    if response.status_code == 200:
        assert str(foreign) not in response.text
        assert "/tmp/attacker" not in response.text
        assert "etc/passwd" not in response.text
