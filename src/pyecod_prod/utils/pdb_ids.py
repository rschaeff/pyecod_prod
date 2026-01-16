"""
PDB ID utilities for handling both legacy 4-character and extended 12-character formats.

Legacy format: XXXX (e.g., "1abc", "9zru")
Extended format: pdb_XXXXXXXX (e.g., "pdb_00001abc", "pdb_10021abc")

The wwPDB is transitioning to extended PDB IDs as the 4-character space approaches
exhaustion (~2027-2028). This module provides utilities for:
- Detecting PDB ID format
- Converting between formats
- Computing directory hashes for PDB mirror structure
- Parsing PDB IDs from various input formats

Reference: https://www.wwpdb.org/documentation/pdb-id-extension-faq
"""

import re
from typing import Optional, Tuple

# Regex patterns for PDB ID formats
LEGACY_PDB_PATTERN = re.compile(r'^[0-9][a-z0-9]{3}$', re.IGNORECASE)
EXTENDED_PDB_PATTERN = re.compile(r'^pdb_[a-z0-9]{8}$', re.IGNORECASE)

# Combined pattern that matches either format
ANY_PDB_PATTERN = re.compile(
    r'^(?:pdb_[a-z0-9]{8}|[0-9][a-z0-9]{3})$',
    re.IGNORECASE
)


def is_valid_pdb_id(pdb_id: str) -> bool:
    """
    Check if string is a valid PDB ID (legacy or extended format).

    Args:
        pdb_id: String to validate

    Returns:
        True if valid PDB ID format

    Examples:
        >>> is_valid_pdb_id("1abc")
        True
        >>> is_valid_pdb_id("pdb_00001abc")
        True
        >>> is_valid_pdb_id("invalid")
        False
    """
    if not pdb_id:
        return False
    return bool(ANY_PDB_PATTERN.match(pdb_id))


def is_extended_pdb_id(pdb_id: str) -> bool:
    """
    Check if PDB ID is in extended format (pdb_XXXXXXXX).

    Args:
        pdb_id: PDB identifier

    Returns:
        True if extended format (12 characters starting with 'pdb_')

    Examples:
        >>> is_extended_pdb_id("pdb_00001abc")
        True
        >>> is_extended_pdb_id("1abc")
        False
    """
    if not pdb_id:
        return False
    return bool(EXTENDED_PDB_PATTERN.match(pdb_id))


def is_legacy_pdb_id(pdb_id: str) -> bool:
    """
    Check if PDB ID is in legacy 4-character format.

    Args:
        pdb_id: PDB identifier

    Returns:
        True if legacy format (4 characters)

    Examples:
        >>> is_legacy_pdb_id("1abc")
        True
        >>> is_legacy_pdb_id("pdb_00001abc")
        False
    """
    if not pdb_id:
        return False
    return bool(LEGACY_PDB_PATTERN.match(pdb_id))


def to_extended_pdb_id(pdb_id: str) -> str:
    """
    Convert PDB ID to extended format.

    Legacy IDs are prefixed with 'pdb_0000'.
    Extended IDs are returned as-is (lowercased).

    Args:
        pdb_id: PDB identifier in any format

    Returns:
        Extended format PDB ID (lowercase)

    Raises:
        ValueError: If pdb_id is not a valid PDB ID

    Examples:
        >>> to_extended_pdb_id("1ABC")
        'pdb_00001abc'
        >>> to_extended_pdb_id("pdb_00001abc")
        'pdb_00001abc'
    """
    if not pdb_id:
        raise ValueError("Empty PDB ID")

    pdb_id_lower = pdb_id.lower()

    if is_extended_pdb_id(pdb_id_lower):
        return pdb_id_lower
    elif is_legacy_pdb_id(pdb_id_lower):
        return f"pdb_0000{pdb_id_lower}"
    else:
        raise ValueError(f"Invalid PDB ID format: {pdb_id}")


def to_legacy_pdb_id(pdb_id: str) -> Optional[str]:
    """
    Extract legacy 4-character PDB ID from extended format.

    Only works for IDs with '0000' padding (original legacy IDs).
    New extended IDs (e.g., pdb_10021abc) cannot be converted to legacy.

    Args:
        pdb_id: PDB identifier in any format

    Returns:
        Legacy 4-character ID, or None if not convertible

    Examples:
        >>> to_legacy_pdb_id("pdb_00001abc")
        '1abc'
        >>> to_legacy_pdb_id("1abc")
        '1abc'
        >>> to_legacy_pdb_id("pdb_10021abc")
        None
    """
    if not pdb_id:
        return None

    pdb_id_lower = pdb_id.lower()

    if is_legacy_pdb_id(pdb_id_lower):
        return pdb_id_lower
    elif is_extended_pdb_id(pdb_id_lower):
        # Check if it's a converted legacy ID (has 0000 padding)
        suffix = pdb_id_lower[4:]  # Remove 'pdb_'
        if suffix.startswith('0000'):
            legacy = suffix[4:]  # Remove '0000'
            if is_legacy_pdb_id(legacy):
                return legacy
        return None
    else:
        return None


def get_directory_hash(pdb_id: str) -> str:
    """
    Get the 2-character directory hash for PDB mirror structure.

    For legacy IDs: characters at positions 1-2 (e.g., "1abc" -> "ab")
    For extended IDs: 2nd & 3rd chars from end of 8-char suffix
                      (e.g., "pdb_10021abc" -> "ab")

    This hash determines the subdirectory in the PDB mirror:
    - Legacy: /usr2/pdb/.../ab/1abc.cif.gz
    - Extended: /pdb/.../ab/pdb_10021abc.cif

    Args:
        pdb_id: PDB identifier in any format

    Returns:
        2-character directory hash (lowercase)

    Raises:
        ValueError: If pdb_id is not a valid PDB ID

    Examples:
        >>> get_directory_hash("1abc")
        'ab'
        >>> get_directory_hash("pdb_00001abc")
        'ab'
        >>> get_directory_hash("pdb_10021abc")
        'ab'
    """
    if not pdb_id:
        raise ValueError("Empty PDB ID")

    pdb_id_lower = pdb_id.lower()

    if is_extended_pdb_id(pdb_id_lower):
        # Extended: 2nd & 3rd chars from end of 8-char suffix
        suffix = pdb_id_lower[4:]  # Remove 'pdb_'
        return suffix[-3:-1]
    elif is_legacy_pdb_id(pdb_id_lower):
        # Legacy: chars at positions 1-2
        return pdb_id_lower[1:3]
    else:
        raise ValueError(f"Invalid PDB ID format: {pdb_id}")


def normalize_pdb_id(pdb_id: str) -> str:
    """
    Normalize PDB ID to lowercase.

    Does not convert between formats - just ensures consistent case.

    Args:
        pdb_id: PDB identifier

    Returns:
        Lowercase PDB ID

    Examples:
        >>> normalize_pdb_id("1ABC")
        '1abc'
        >>> normalize_pdb_id("PDB_00001ABC")
        'pdb_00001abc'
    """
    return pdb_id.lower() if pdb_id else ""


def parse_pdb_chain_id(identifier: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse a PDB_CHAIN identifier into PDB ID and chain ID components.

    Handles both legacy and extended formats:
    - "1abc_A" -> ("1abc", "A")
    - "pdb_00001abc_A" -> ("pdb_00001abc", "A")

    Args:
        identifier: Combined PDB_CHAIN identifier

    Returns:
        Tuple of (pdb_id, chain_id), or (None, None) if parsing fails

    Examples:
        >>> parse_pdb_chain_id("1abc_A")
        ('1abc', 'A')
        >>> parse_pdb_chain_id("pdb_00001abc_A")
        ('pdb_00001abc', 'A')
    """
    if not identifier or '_' not in identifier:
        return None, None

    # For extended IDs, the format is pdb_XXXXXXXX_CHAIN
    # For legacy IDs, the format is XXXX_CHAIN
    # The chain ID is always the last underscore-separated part

    parts = identifier.rsplit('_', 1)
    if len(parts) != 2:
        return None, None

    pdb_id, chain_id = parts

    # Validate the PDB ID part
    if is_valid_pdb_id(pdb_id):
        return pdb_id.lower(), chain_id

    # For extended format like "pdb_00001abc", split removes the chain
    # but pdb_00001abc is still valid
    return None, None


def extract_pdb_id_from_line(line: str) -> Optional[str]:
    """
    Extract PDB ID from a line of text (e.g., from status files).

    Handles both whitespace-separated and fixed-width formats.
    Supports both legacy and extended PDB IDs.

    Args:
        line: Line of text potentially containing a PDB ID

    Returns:
        Extracted PDB ID (lowercase), or None if not found

    Examples:
        >>> extract_pdb_id_from_line("1abc")
        '1abc'
        >>> extract_pdb_id_from_line("1abc  some other text")
        '1abc'
        >>> extract_pdb_id_from_line("pdb_00001abc")
        'pdb_00001abc'
    """
    if not line:
        return None

    line = line.strip()
    if not line or line.startswith('#'):
        return None

    # Try whitespace-separated first
    parts = line.split()
    if parts:
        candidate = parts[0].lower()
        if is_valid_pdb_id(candidate):
            return candidate

    # Try fixed-width legacy format (first 4 chars)
    if len(line) >= 4:
        candidate = line[:4].lower()
        if is_legacy_pdb_id(candidate):
            return candidate

    # Try extended format (first 12 chars)
    if len(line) >= 12:
        candidate = line[:12].lower()
        if is_extended_pdb_id(candidate):
            return candidate

    return None
