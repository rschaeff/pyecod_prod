#!/usr/bin/env python3
"""
Utility for loading ECOD domain → classification (x/h/t/f group) lookups.

Provides fast in-memory lookups from an ECOD domain id to its X/H/T/F group ids.
Used by SummaryGenerator to emit classification attributes on evidence <hit>
elements, which enables F-group / T-group exclusion in pyecod_mini for
non-circular validation of existing reps.

See scripts/build_classification_lookup.py for the (legacy-naming-aware) builder.
"""

from pathlib import Path
from typing import Dict

# Mapping: ecod_domain_id -> {"x_group", "h_group", "t_group", "f_group"}
ClassificationLookup = Dict[str, Dict[str, str]]


def load_classification_lookup(tsv_path: str) -> ClassificationLookup:
    """Load domain → {x,h,t,f group} lookup from a TSV file.

    Args:
        tsv_path: Path to domain_classification_lookup.tsv

    Returns:
        Dict mapping ecod_domain_id → {"x_group", "h_group", "t_group", "f_group"}.
        Empty group ids are omitted from the per-domain dict.

    Example:
        >>> lk = load_classification_lookup(".../domain_classification_lookup.tsv")
        >>> lk["e1udzA1"]
        {'x_group': '1', 'h_group': '1.1', 't_group': '1.1.1', 'f_group': '1.1.1.1'}
    """
    lookup: ClassificationLookup = {}

    with open(tsv_path, "r") as f:
        for line in f:
            if line.startswith("#") or line.startswith("ecod_domain_id"):
                continue
            line = line.rstrip("\n")
            if not line:
                continue

            parts = line.split("\t")
            if len(parts) < 2:
                continue

            domain_id = parts[0]
            groups = {}
            # Columns: domain_id, x_group, h_group, t_group, f_group
            for idx, key in enumerate(("x_group", "h_group", "t_group", "f_group"), start=1):
                if idx < len(parts) and parts[idx]:
                    groups[key] = parts[idx]
            lookup[domain_id] = groups

    return lookup


def get_default_lookup_path(reference_version: str = "v294.2") -> str:
    """Get default path to the classification lookup for a reference version."""
    if reference_version.startswith("develop"):
        version_num = reference_version.replace("develop", "")
        version_dir = f"v{version_num}"
    else:
        version_dir = reference_version

    return f"/data/ecod/database_versions/{version_dir}/domain_classification_lookup.tsv"


def load_classification_lookup_for_version(
    reference_version: str = "v294.2",
) -> ClassificationLookup:
    """Load classification lookup for a specific ECOD version.

    Args:
        reference_version: ECOD reference version (e.g., "develop291")

    Returns:
        Dict mapping ecod_domain_id → {x/h/t/f group}.

    Raises:
        FileNotFoundError: If the lookup file does not exist.
    """
    tsv_path = get_default_lookup_path(reference_version)

    if not Path(tsv_path).exists():
        raise FileNotFoundError(
            f"Classification lookup not found: {tsv_path}\n"
            f"Generate it with: python scripts/build_classification_lookup.py"
        )

    return load_classification_lookup(tsv_path)
