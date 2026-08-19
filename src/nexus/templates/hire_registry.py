"""Manifest registry - filesystem-based storage and lookup of hire manifests.

Provides a ManifestRegistry class for discovering, loading, and importing
hire manifests from a directory of JSON files.
"""

from __future__ import annotations

import json
from pathlib import Path

from nexus.templates.hire_manifest import HireManifest, HireValidation, validate_hire_manifest


class ManifestRegistry:
    """Registry for discovering, loading, and importing hire manifests from a directory.

    Manifests are stored as individual JSON files named after the manifest's name
    field (lowercased, spaces replaced with hyphens).
    """

    def __init__(self, root: Path) -> None:
        """Initialize the registry with a root directory path.

        Args:
            root: Path to the directory containing manifest JSON files.
        """
        self._root = root
        self._manifests: dict[str, HireManifest] = {}

    def load(self) -> None:
        """Load all .json manifest files from the root directory.

        Silently skips files that fail validation.
        """
        self._manifests.clear()
        if not self._root.exists():
            return
        for path in sorted(self._root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                result = validate_hire_manifest(data)
                if result.ok and result.manifest is not None:
                    self._manifests[result.manifest.name] = result.manifest
            except (json.JSONDecodeError, OSError):
                continue

    def list_manifests(self) -> list[HireManifest]:
        """Return all loaded manifests sorted by name."""
        return sorted(self._manifests.values(), key=lambda m: m.name)

    def get_manifest(self, name: str) -> HireManifest | None:
        """Look up a manifest by name.

        Args:
            name: The manifest name to look up.

        Returns:
            The manifest if found, None otherwise.
        """
        return self._manifests.get(name)

    def import_manifest(self, data: dict) -> HireValidation:
        """Validate and save a manifest from raw dict data.

        Args:
            data: Raw dictionary representing a manifest.

        Returns:
            HireValidation result with ok=True if import succeeded.
        """
        result = validate_hire_manifest(data)
        if result.ok and result.manifest is not None:
            self._manifests[result.manifest.name] = result.manifest
            self._save(result.manifest)
        return result

    def _save(self, manifest: HireManifest) -> None:
        """Write manifest as JSON to the registry directory.

        Args:
            manifest: The validated manifest to persist.
        """
        self._root.mkdir(parents=True, exist_ok=True)
        filename = manifest.name.lower().replace(" ", "-") + ".json"
        path = self._root / filename
        data = manifest.model_dump(exclude_none=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
