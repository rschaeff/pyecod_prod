#!/usr/bin/env python3
"""
Utility for loading ECOD domain → family name lookups.

Provides fast in-memory lookups from domain ID to family name.
"""

from pathlib import Path
from typing import Dict


def load_family_lookup(tsv_path: str) -> Dict[str, str]:
    """
    Load domain → family name lookup from TSV file.

    Args:
        tsv_path: Path to domain_family_lookup.tsv

    Returns:
        Dictionary mapping ecod_domain_id → family_name

    Example:
        >>> lookup = load_family_lookup("/data/ecod/database_versions/v291/domain_family_lookup.tsv")
        >>> lookup["e1suaA1"]
        'GFP-like'
    """
    lookup = {}

    with open(tsv_path, "r") as f:
        for line in f:
            # Skip comments and header
            if line.startswith("#") or line.startswith("ecod_domain_id"):
                continue

            line = line.strip()
            if not line:
                continue

            parts = line.split("\t")
            if len(parts) == 2:
                domain_id, family_name = parts
                lookup[domain_id] = family_name

    return lookup


def get_default_lookup_path(reference_version: str = "develop291") -> str:
    """
    Get default path to family lookup file for a reference version.

    Args:
        reference_version: ECOD reference version (e.g., "develop291")

    Returns:
        Path to domain_family_lookup.tsv
    """
    # Extract version number (e.g., "develop291" → "v291")
    if reference_version.startswith("develop"):
        version_num = reference_version.replace("develop", "")
        version_dir = f"v{version_num}"
    else:
        version_dir = reference_version

    return f"/data/ecod/database_versions/{version_dir}/domain_family_lookup.tsv"


def load_family_lookup_for_version(reference_version: str = "develop291") -> Dict[str, str]:
    """
    Load family lookup for a specific ECOD version.

    Args:
        reference_version: ECOD reference version (e.g., "develop291")

    Returns:
        Dictionary mapping ecod_domain_id → family_name

    Example:
        >>> lookup = load_family_lookup_for_version("develop291")
        >>> lookup["e1suaA1"]
        'GFP-like'
    """
    tsv_path = get_default_lookup_path(reference_version)

    if not Path(tsv_path).exists():
        raise FileNotFoundError(
            f"Family lookup not found: {tsv_path}\n"
            f"Generate it with: python scripts/build_family_lookup.py"
        )

    return load_family_lookup(tsv_path)
