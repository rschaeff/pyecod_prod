"""Utility modules for pyecod_prod."""

from pyecod_prod.utils.pdb_ids import (
    is_valid_pdb_id,
    is_extended_pdb_id,
    is_legacy_pdb_id,
    to_extended_pdb_id,
    to_legacy_pdb_id,
    get_directory_hash,
    normalize_pdb_id,
    parse_pdb_chain_id,
    extract_pdb_id_from_line,
)

from pyecod_prod.utils.designed_proteins import (
    DesignedProteinDetector,
    DesignedProteinResult,
    DesignedProteinConfidence,
    is_designed_protein,
    get_designed_protein_info,
)

__all__ = [
    # PDB ID utilities
    "is_valid_pdb_id",
    "is_extended_pdb_id",
    "is_legacy_pdb_id",
    "to_extended_pdb_id",
    "to_legacy_pdb_id",
    "get_directory_hash",
    "normalize_pdb_id",
    "parse_pdb_chain_id",
    "extract_pdb_id_from_line",
    # Designed protein detection
    "DesignedProteinDetector",
    "DesignedProteinResult",
    "DesignedProteinConfidence",
    "is_designed_protein",
    "get_designed_protein_info",
]
