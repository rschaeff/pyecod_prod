"""
Domain overlap detection and range utilities for ECOD auto-accession.

This module provides the Python equivalent of the legacy Perl script
process_domain_summary_to_ecod_release.pl, implementing:
- Range parsing (chain-specified and raw formats)
- Overlap calculation between domains (including discontinuous)
- Pre-insertion validation against existing domains
- Conflict detection with configurable thresholds

ECOD Overlap Policy:
- Small overlaps (≤5% or ≤10 residues) allowed between neighboring domains
- High bidirectional overlap (>80% both directions) → skip/flag
- Identical ranges → skip (duplicate)
- Large residue conflicts (>10 residues) → skip/flag
"""

import re
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Set, Dict, Any
from enum import Enum


class OverlapSeverity(Enum):
    """Severity levels for domain overlap conflicts."""
    NONE = "none"              # No significant overlap
    MINOR = "minor"            # Small overlap, acceptable (≤5% or ≤10 residues)
    MODERATE = "moderate"      # Moderate overlap, needs review
    SEVERE = "severe"          # High overlap, should skip
    IDENTICAL = "identical"    # Exact same range, duplicate


@dataclass
class RangeSegment:
    """A single continuous segment of a domain range."""
    chain_id: Optional[str]  # None for raw ranges
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @property
    def residues(self) -> Set[int]:
        return set(range(self.start, self.end + 1))

    def to_pg_range(self) -> str:
        """Convert to PostgreSQL int4range format: [start, end]"""
        return f"[{self.start}, {self.end}]"

    def overlaps(self, other: 'RangeSegment') -> bool:
        """Check if this segment overlaps another (ignoring chain for now)."""
        return not (self.end < other.start or self.start > other.end)

    def overlap_residues(self, other: 'RangeSegment') -> Set[int]:
        """Get the set of overlapping residues."""
        return self.residues & other.residues


@dataclass
class DomainRange:
    """
    A domain range, potentially discontinuous.

    Supports both formats:
    - Chain-specified: "A:10-150,A:200-250" (PDB standard)
    - Raw: "10-150,200-250" (legacy AFDB format)
    """
    segments: List[RangeSegment] = field(default_factory=list)
    original_string: str = ""

    @property
    def is_discontinuous(self) -> bool:
        return len(self.segments) > 1

    @property
    def chain_id(self) -> Optional[str]:
        """Return chain ID if all segments have same chain, else None."""
        if not self.segments:
            return None
        chains = set(s.chain_id for s in self.segments if s.chain_id)
        return chains.pop() if len(chains) == 1 else None

    @property
    def total_length(self) -> int:
        return sum(s.length for s in self.segments)

    @property
    def all_residues(self) -> Set[int]:
        """Get all residues covered by this range."""
        residues = set()
        for segment in self.segments:
            residues.update(segment.residues)
        return residues

    @property
    def min_residue(self) -> int:
        return min(s.start for s in self.segments)

    @property
    def max_residue(self) -> int:
        return max(s.end for s in self.segments)

    @property
    def bounding_range(self) -> Tuple[int, int]:
        """Get the bounding box (min, max) of all segments."""
        return (self.min_residue, self.max_residue)

    def normalize(self, default_chain: str = "A") -> 'DomainRange':
        """
        Normalize range to chain-specified format.

        This addresses the inconsistency between PDB (chain-specified)
        and AFDB (raw) range formats by standardizing on chain-specified.
        """
        normalized_segments = []
        for seg in self.segments:
            chain = seg.chain_id if seg.chain_id else default_chain
            normalized_segments.append(RangeSegment(chain, seg.start, seg.end))

        # Reconstruct the string
        parts = [f"{s.chain_id}:{s.start}-{s.end}" for s in normalized_segments]
        return DomainRange(
            segments=normalized_segments,
            original_string=",".join(parts)
        )

    def to_string(self, include_chain: bool = True) -> str:
        """Convert to string representation."""
        if include_chain:
            parts = []
            for s in self.segments:
                if s.chain_id:
                    parts.append(f"{s.chain_id}:{s.start}-{s.end}")
                else:
                    parts.append(f"{s.start}-{s.end}")
            return ",".join(parts)
        else:
            return ",".join(f"{s.start}-{s.end}" for s in self.segments)


def parse_range(range_string: str) -> DomainRange:
    """
    Parse a domain range string into a DomainRange object.

    Supported formats:
    - "A:10-150" (single segment, chain-specified)
    - "A:10-150,A:200-250" (discontinuous, chain-specified)
    - "10-150" (single segment, raw)
    - "10-150,200-250" (discontinuous, raw)
    - "A:10-50,B:60-100" (multi-chain, rare but valid)

    Args:
        range_string: The range definition string

    Returns:
        DomainRange object with parsed segments
    """
    if not range_string or range_string.strip() == "":
        return DomainRange(segments=[], original_string=range_string)

    segments = []

    # Split on comma for discontinuous ranges
    parts = range_string.split(",")

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Try chain-specified format first: "A:10-150" or "A:10-50"
        chain_match = re.match(r'^([A-Za-z0-9]+):(-?\d+)-(-?\d+)$', part)
        if chain_match:
            chain_id = chain_match.group(1)
            start = int(chain_match.group(2))
            end = int(chain_match.group(3))
            segments.append(RangeSegment(chain_id, start, end))
            continue

        # Try raw format: "10-150"
        raw_match = re.match(r'^(-?\d+)-(-?\d+)$', part)
        if raw_match:
            start = int(raw_match.group(1))
            end = int(raw_match.group(2))
            segments.append(RangeSegment(None, start, end))
            continue

        # Unrecognized format
        raise ValueError(f"Cannot parse range segment: '{part}'")

    return DomainRange(segments=segments, original_string=range_string)


def calculate_overlap(range1: DomainRange, range2: DomainRange) -> Dict[str, Any]:
    """
    Calculate overlap between two domain ranges.

    Returns metrics matching the legacy Perl script:
    - residue_overlap: Number of overlapping residues
    - coverage_1_by_2: Fraction of range1 covered by range2
    - coverage_2_by_1: Fraction of range2 covered by range1
    - is_identical: Whether ranges are exactly identical
    - overlap_fraction: Overall overlap as fraction of smaller domain

    Args:
        range1: First domain range
        range2: Second domain range

    Returns:
        Dict with overlap metrics
    """
    residues1 = range1.all_residues
    residues2 = range2.all_residues

    overlap = residues1 & residues2

    # Handle empty ranges
    if not residues1 or not residues2:
        return {
            'residue_overlap': 0,
            'coverage_1_by_2': 0.0,
            'coverage_2_by_1': 0.0,
            'is_identical': False,
            'overlap_fraction': 0.0,
            'overlapping_residues': set()
        }

    residue_overlap = len(overlap)
    coverage_1_by_2 = residue_overlap / len(residues1) if residues1 else 0.0
    coverage_2_by_1 = residue_overlap / len(residues2) if residues2 else 0.0

    # Overlap as fraction of smaller domain
    min_size = min(len(residues1), len(residues2))
    overlap_fraction = residue_overlap / min_size if min_size > 0 else 0.0

    return {
        'residue_overlap': residue_overlap,
        'coverage_1_by_2': coverage_1_by_2,
        'coverage_2_by_1': coverage_2_by_1,
        'is_identical': residues1 == residues2,
        'overlap_fraction': overlap_fraction,
        'overlapping_residues': overlap
    }


@dataclass
class OverlapConflict:
    """Represents a detected overlap conflict."""
    existing_domain_id: str
    existing_ecod_uid: int
    existing_range: str
    new_range: str
    residue_overlap: int
    coverage_existing_by_new: float
    coverage_new_by_existing: float
    severity: OverlapSeverity
    message: str


def assess_overlap_severity(
    overlap_metrics: Dict[str, Any],
    max_allowed_residue_overlap: int = 10,
    max_allowed_coverage: float = 0.80,
    minor_overlap_threshold: float = 0.05
) -> Tuple[OverlapSeverity, str]:
    """
    Assess the severity of an overlap based on ECOD policy.

    Thresholds based on legacy Perl script:
    - Identical ranges → IDENTICAL (skip as duplicate)
    - Both directions > 80% coverage → SEVERE (skip)
    - > 10 residues overlap → SEVERE (skip)
    - ≤ 5% overlap → MINOR (acceptable)
    - Otherwise → MODERATE (needs review)

    Args:
        overlap_metrics: Output from calculate_overlap()
        max_allowed_residue_overlap: Maximum residue overlap before SEVERE
        max_allowed_coverage: Maximum bidirectional coverage before SEVERE
        minor_overlap_threshold: Coverage threshold below which overlap is MINOR

    Returns:
        Tuple of (severity, message)
    """
    if overlap_metrics['is_identical']:
        return (OverlapSeverity.IDENTICAL, "Identical range - duplicate domain")

    if overlap_metrics['residue_overlap'] == 0:
        return (OverlapSeverity.NONE, "No overlap")

    c1 = overlap_metrics['coverage_1_by_2']
    c2 = overlap_metrics['coverage_2_by_1']
    residue_overlap = overlap_metrics['residue_overlap']

    # Check for severe overlap (legacy: "loose correspondence")
    if c1 > max_allowed_coverage and c2 > max_allowed_coverage:
        return (
            OverlapSeverity.SEVERE,
            f"High bidirectional overlap ({c1:.1%} / {c2:.1%}) - loose correspondence"
        )

    # Check for residue conflict threshold
    if residue_overlap > max_allowed_residue_overlap:
        return (
            OverlapSeverity.SEVERE,
            f"Residue conflict ({residue_overlap} residues) exceeds threshold ({max_allowed_residue_overlap})"
        )

    # Check for minor overlap (acceptable neighboring domain overlap)
    if c1 <= minor_overlap_threshold and c2 <= minor_overlap_threshold:
        return (
            OverlapSeverity.MINOR,
            f"Minor overlap ({residue_overlap} residues, {c1:.1%}/{c2:.1%}) - acceptable"
        )

    # Moderate - needs review but not automatically rejected
    return (
        OverlapSeverity.MODERATE,
        f"Moderate overlap ({residue_overlap} residues, {c1:.1%}/{c2:.1%}) - review recommended"
    )


class DomainOverlapChecker:
    """
    Check new domains for overlaps against existing domains in ecod_commons.

    This class provides the database integration for overlap detection,
    querying existing domains and applying the overlap policy.
    """

    def __init__(
        self,
        connection_params: Optional[Dict] = None,
        max_residue_overlap: int = 10,
        max_coverage: float = 0.80,
        minor_threshold: float = 0.05
    ):
        """
        Initialize the overlap checker.

        Args:
            connection_params: Database connection parameters
            max_residue_overlap: Maximum allowed residue overlap
            max_coverage: Maximum allowed bidirectional coverage
            minor_threshold: Threshold below which overlap is minor
        """
        self.connection_params = connection_params or {
            "host": "dione",
            "port": 45000,
            "database": "ecod_protein",
            "user": "ecod",
            "password": "ecod#badmin"
        }
        self.max_residue_overlap = max_residue_overlap
        self.max_coverage = max_coverage
        self.minor_threshold = minor_threshold

        # Cache for existing domains (pdb_id, chain_id) -> list of domains
        self._domain_cache: Dict[Tuple[str, str], List[Dict]] = {}

    def _get_connection(self):
        """Get database connection."""
        import psycopg2
        return psycopg2.connect(**self.connection_params)

    def get_existing_domains(
        self,
        pdb_id: str,
        chain_id: str,
        include_obsolete: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get existing domains for a PDB chain from ecod_commons.

        Args:
            pdb_id: PDB identifier
            chain_id: Chain identifier
            include_obsolete: Whether to include obsolete domains

        Returns:
            List of domain dicts with domain_id, ecod_uid, range_definition
        """
        cache_key = (pdb_id.lower(), chain_id)
        if cache_key in self._domain_cache:
            return self._domain_cache[cache_key]

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            query = """
                SELECT
                    d.id,
                    d.domain_id,
                    d.ecod_uid,
                    d.range_definition,
                    d.is_obsolete,
                    d.domain_version
                FROM ecod_commons.domains d
                JOIN ecod_commons.proteins p ON d.protein_id = p.id
                WHERE LOWER(p.pdb_id) = LOWER(%s)
                  AND p.chain_id = %s
            """

            if not include_obsolete:
                query += " AND d.is_obsolete = false"

            cursor.execute(query, (pdb_id, chain_id))

            domains = []
            for row in cursor.fetchall():
                domains.append({
                    'id': row[0],
                    'domain_id': row[1],
                    'ecod_uid': row[2],
                    'range_definition': row[3],
                    'is_obsolete': row[4],
                    'domain_version': row[5]
                })

            self._domain_cache[cache_key] = domains
            return domains

        finally:
            cursor.close()
            conn.close()

    def check_domain_overlaps(
        self,
        pdb_id: str,
        chain_id: str,
        new_range: str,
        new_domain_id: Optional[str] = None
    ) -> List[OverlapConflict]:
        """
        Check a new domain range for overlaps with existing domains.

        Args:
            pdb_id: PDB identifier
            chain_id: Chain identifier
            new_range: Range definition for new domain
            new_domain_id: Optional domain ID for the new domain

        Returns:
            List of OverlapConflict objects for any conflicts found
        """
        existing_domains = self.get_existing_domains(pdb_id, chain_id)
        new_parsed = parse_range(new_range)

        conflicts = []

        for existing in existing_domains:
            existing_parsed = parse_range(existing['range_definition'])

            # Calculate overlap
            metrics = calculate_overlap(new_parsed, existing_parsed)

            # Assess severity
            severity, message = assess_overlap_severity(
                metrics,
                max_allowed_residue_overlap=self.max_residue_overlap,
                max_allowed_coverage=self.max_coverage,
                minor_overlap_threshold=self.minor_threshold
            )

            # Only report conflicts that are not NONE
            if severity != OverlapSeverity.NONE:
                conflicts.append(OverlapConflict(
                    existing_domain_id=existing['domain_id'],
                    existing_ecod_uid=existing['ecod_uid'],
                    existing_range=existing['range_definition'],
                    new_range=new_range,
                    residue_overlap=metrics['residue_overlap'],
                    coverage_existing_by_new=metrics['coverage_1_by_2'],
                    coverage_new_by_existing=metrics['coverage_2_by_1'],
                    severity=severity,
                    message=message
                ))

        return conflicts

    def can_auto_accession(
        self,
        pdb_id: str,
        chain_id: str,
        new_range: str
    ) -> Tuple[bool, List[OverlapConflict]]:
        """
        Check if a new domain can be auto-accessioned.

        Returns True if:
        - No SEVERE or IDENTICAL overlaps
        - Only NONE, MINOR, or MODERATE overlaps

        MODERATE overlaps allow auto-accession but are logged for review.

        Args:
            pdb_id: PDB identifier
            chain_id: Chain identifier
            new_range: Range definition for new domain

        Returns:
            Tuple of (can_accession, list of conflicts)
        """
        conflicts = self.check_domain_overlaps(pdb_id, chain_id, new_range)

        # Check for blocking conflicts
        blocking = [
            c for c in conflicts
            if c.severity in (OverlapSeverity.SEVERE, OverlapSeverity.IDENTICAL)
        ]

        return (len(blocking) == 0, conflicts)

    def clear_cache(self):
        """Clear the domain cache."""
        self._domain_cache.clear()

    def prefetch_domains_for_pdbs(
        self,
        pdb_ids: List[str],
        include_obsolete: bool = False
    ) -> int:
        """
        Prefetch all domains for a list of PDB IDs into cache.

        This is a major optimization - instead of N queries (one per chain),
        we do one query to load all domains for all PDBs in the batch.

        Args:
            pdb_ids: List of PDB IDs to prefetch
            include_obsolete: Whether to include obsolete domains

        Returns:
            Number of domains cached
        """
        if not pdb_ids:
            return 0

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Lowercase all PDB IDs for consistent matching
            pdb_ids_lower = [p.lower() for p in pdb_ids]

            query = """
                SELECT
                    LOWER(p.pdb_id) as pdb_id,
                    p.chain_id,
                    d.id,
                    d.domain_id,
                    d.ecod_uid,
                    d.range_definition,
                    d.is_obsolete,
                    d.domain_version
                FROM ecod_commons.domains d
                JOIN ecod_commons.proteins p ON d.protein_id = p.id
                WHERE LOWER(p.pdb_id) = ANY(%s)
            """

            if not include_obsolete:
                query += " AND d.is_obsolete = false"

            cursor.execute(query, (pdb_ids_lower,))

            count = 0
            # Group results by (pdb_id, chain_id)
            for row in cursor.fetchall():
                pdb_id = row[0]
                chain_id = row[1]
                cache_key = (pdb_id, chain_id)

                if cache_key not in self._domain_cache:
                    self._domain_cache[cache_key] = []

                self._domain_cache[cache_key].append({
                    'id': row[2],
                    'domain_id': row[3],
                    'ecod_uid': row[4],
                    'range_definition': row[5],
                    'is_obsolete': row[6],
                    'domain_version': row[7]
                })
                count += 1

            return count

        finally:
            cursor.close()
            conn.close()


# Utility functions for PostgreSQL range operations

def ranges_to_segments_table_values(
    domain_id: int,
    range_definition: str
) -> List[Tuple[int, str, int, int, int]]:
    """
    Convert a range definition to values for a segments table.

    This supports efficient PostgreSQL range queries by storing each
    segment separately with int4range operators.

    Args:
        domain_id: The domain's database ID
        range_definition: The range definition string

    Returns:
        List of tuples: (domain_id, chain_id, segment_num, start, end)
    """
    parsed = parse_range(range_definition)
    values = []

    for i, segment in enumerate(parsed.segments):
        values.append((
            domain_id,
            segment.chain_id or 'A',  # Default to 'A' for raw ranges
            i + 1,  # 1-indexed segment number
            segment.start,
            segment.end
        ))

    return values


def create_domain_segments_table_sql() -> str:
    """
    Generate SQL to create a domain_segments table for efficient overlap queries.

    This table stores each segment of a domain separately, enabling
    PostgreSQL int4range operators for overlap detection.
    """
    return """
    CREATE TABLE IF NOT EXISTS ecod_commons.domain_segments (
        id SERIAL PRIMARY KEY,
        domain_id INTEGER NOT NULL REFERENCES ecod_commons.domains(id) ON DELETE CASCADE,
        chain_id VARCHAR(10) NOT NULL DEFAULT 'A',
        segment_num INTEGER NOT NULL DEFAULT 1,
        segment_range int4range NOT NULL,

        -- Constraint to ensure valid range
        CONSTRAINT valid_segment_range CHECK (
            lower(segment_range) >= 0 AND
            upper(segment_range) > lower(segment_range)
        ),

        -- Index for efficient overlap queries
        CONSTRAINT unique_domain_segment UNIQUE (domain_id, chain_id, segment_num)
    );

    -- GiST index for range overlap queries (the key to efficient overlap detection)
    CREATE INDEX IF NOT EXISTS idx_domain_segments_range
    ON ecod_commons.domain_segments USING GIST (segment_range);

    -- Composite index for chain-specific queries
    CREATE INDEX IF NOT EXISTS idx_domain_segments_chain_range
    ON ecod_commons.domain_segments USING GIST (chain_id, segment_range);

    -- Function to check if any segment of a new domain overlaps existing segments
    CREATE OR REPLACE FUNCTION ecod_commons.check_segment_overlaps(
        p_protein_id INTEGER,
        p_chain_id VARCHAR(10),
        p_segments int4range[]
    ) RETURNS TABLE (
        existing_domain_id INTEGER,
        existing_segment_range int4range,
        overlap_with int4range
    ) AS $$
    BEGIN
        RETURN QUERY
        SELECT
            ds.domain_id,
            ds.segment_range,
            s.segment as overlap_with
        FROM ecod_commons.domain_segments ds
        JOIN ecod_commons.domains d ON ds.domain_id = d.id
        CROSS JOIN UNNEST(p_segments) AS s(segment)
        WHERE d.protein_id = p_protein_id
          AND ds.chain_id = p_chain_id
          AND d.is_obsolete = false
          AND ds.segment_range && s.segment;  -- && is the overlap operator
    END;
    $$ LANGUAGE plpgsql;
    """
