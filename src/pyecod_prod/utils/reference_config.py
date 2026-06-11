#!/usr/bin/env python3
"""
Reference-version registry: a single source of truth for the per-version reference
artifact paths the pipeline depends on (BLAST DBs, HHsearch DB, lookups, and the
reference CSVs handed to pyecod_mini).

Motivation
----------
Reference paths were previously specified ad-hoc in ≥7 places with several
incompatible version-string conventions (developNNN vs vNNN vs ecod_vNNN_M_F40),
and the BLAST/HHsearch DB paths were hardcoded class constants decoupled from the
configured ``reference_version`` — so a version mismatch (e.g. HHsearch on v294.2
while everything else is develop291) was the default state, not an accident, and a
correctness hazard (v294.2 is a reclassification release).

This module loads ``config/references.yaml`` and resolves every artifact path for a
canonical version key, so all components agree on the version. Use ``verify()`` to
assert the artifacts for a version actually exist and are coherent before running.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

# Path to the registry data file (packaged alongside the source).
_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "references.yaml"

# Fields that are filesystem paths (used by verify() and existence checks).
_PATH_FIELDS = (
    "blast_chain_db",
    "blast_domain_db",
    "hhsearch_db",
    "domains_txt",
    "range_cache",
    "family_lookup",
    "classification_lookup",
    "domain_definitions_csv",
    "domain_lengths_csv",
    "protein_lengths_csv",
)


@dataclass
class ReferenceConfig:
    """Resolved reference paths for one ECOD version.

    All path fields may be None, meaning "not applicable for this version / use the
    consumer's built-in default" (e.g. mini's bundled test_data CSVs for v291).
    """

    version: str  # canonical key, e.g. "v291" / "v294.2"
    summary_suffix: Optional[str] = None
    # True when pyecod_mini bundles this version's reference CSVs (so the *_csv
    # fields may be null and verify() does not require them).
    mini_bundled: bool = False

    blast_chain_db: Optional[str] = None
    blast_domain_db: Optional[str] = None
    hhsearch_db: Optional[str] = None

    domains_txt: Optional[str] = None
    range_cache: Optional[str] = None
    family_lookup: Optional[str] = None
    classification_lookup: Optional[str] = None

    domain_definitions_csv: Optional[str] = None
    domain_lengths_csv: Optional[str] = None
    protein_lengths_csv: Optional[str] = None

    # --- construction -----------------------------------------------------

    @classmethod
    def load(
        cls, reference_version: Optional[str] = None, registry_path: Optional[str] = None
    ) -> "ReferenceConfig":
        """Load the resolved config for a version from the registry.

        Args:
            reference_version: version key or alias (e.g. "v294.2", "develop291").
                Defaults to the registry's ``default``.
            registry_path: override path to references.yaml (for testing).

        Raises:
            KeyError: if the version/alias is unknown.
        """
        data = _load_registry(registry_path)
        key = _resolve_key(data, reference_version)
        entry = data["versions"][key]
        fields = {f: entry.get(f) for f in (("summary_suffix",) + _PATH_FIELDS)}
        return cls(version=key, mini_bundled=bool(entry.get("mini_bundled", False)), **fields)

    # --- helpers ----------------------------------------------------------

    def path(self, field_name: str) -> Optional[str]:
        """Return a path field by name (None if not set)."""
        return getattr(self, field_name)

    def missing(self, required: List[str]) -> List[str]:
        """Return the subset of ``required`` path-fields whose file does not exist.

        A field set to None counts as missing (it has no resolvable artifact).
        BLAST DB prefixes are checked via their first sequence volume (.psq/.00.psq).
        """
        absent = []
        for fname in required:
            p = getattr(self, fname)
            if not p or not _artifact_exists(fname, p):
                absent.append(fname)
        return absent

    def verify(self, required: Optional[List[str]] = None) -> None:
        """Assert that all ``required`` artifacts exist; raise otherwise.

        Default ``required`` is the set needed for a full production run.
        """
        if required is None:
            required = [
                "blast_chain_db",
                "blast_domain_db",
                "hhsearch_db",
                "family_lookup",
                "classification_lookup",
                "domain_definitions_csv",
                "domain_lengths_csv",
                "protein_lengths_csv",
            ]
            # When mini bundles this version's reference CSVs, they are expected
            # to be null here (mini uses its own defaults) — don't require them.
            if self.mini_bundled:
                required = [r for r in required if not r.endswith("_csv")]
        absent = self.missing(required)
        if absent:
            details = "\n".join(f"  - {f}: {getattr(self, f)!r}" for f in absent)
            raise FileNotFoundError(
                f"Reference version {self.version!r} is missing required artifacts:\n{details}"
            )


def _load_registry(registry_path: Optional[str]) -> dict:
    path = Path(registry_path) if registry_path else _REGISTRY_PATH
    with open(path) as fh:
        return yaml.safe_load(fh)


def _resolve_key(data: dict, reference_version: Optional[str]) -> str:
    """Resolve a version string (or None) to a canonical key in the registry."""
    versions = data.get("versions", {})
    aliases = data.get("aliases", {})
    if reference_version is None:
        reference_version = data.get("default")
    if reference_version in versions:
        return reference_version
    if reference_version in aliases and aliases[reference_version] in versions:
        return aliases[reference_version]
    raise KeyError(
        f"Unknown reference version {reference_version!r}. "
        f"Known: {sorted(versions)} (aliases: {sorted(aliases)})"
    )


def _artifact_exists(field_name: str, path: str) -> bool:
    """Existence check, with BLAST-DB-prefix awareness."""
    if field_name in ("blast_chain_db", "blast_domain_db"):
        # BLAST DB is a prefix; check the protein sequence volume.
        return (
            Path(f"{path}.psq").exists()
            or Path(f"{path}.00.psq").exists()
            or Path(f"{path}.pdb").exists()  # newer makeblastdb metadata file
        )
    if field_name == "hhsearch_db":
        return Path(f"{path}_hhm.ffdata").exists() and Path(f"{path}_hhm.ffindex").exists()
    return Path(path).exists()


def available_versions(registry_path: Optional[str] = None) -> List[str]:
    """List canonical version keys defined in the registry."""
    return sorted(_load_registry(registry_path).get("versions", {}))
