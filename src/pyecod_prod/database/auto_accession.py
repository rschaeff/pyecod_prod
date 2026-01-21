"""
Auto-accession loader for ECOD domains.

This module handles the safe insertion of new domains into ecod_commons,
implementing the equivalent of the legacy Perl script's logic:
- UID generation from sequence
- Domain ID generation with collision handling
- Overlap detection and conflict resolution
- Audit trail for all accession decisions

Usage:
    from pyecod_prod.database.auto_accession import (
        AutoAccessionLoader,
        ProcessingContext,
    )

    # Create processing context with version tracking
    context = ProcessingContext(
        batch_id="ecod_q4_2025_q1_2026",
        pyecod_mini_version="2.0.2",
        pyecod_prod_version="1.0.0",
        ecod_reference_version="v293.1"
    )

    loader = AutoAccessionLoader()

    # Check and load a single domain
    result = loader.accession_domain(
        pdb_id="8abc",
        chain_id="A",
        range_definition="A:10-150",
        t_group="1.1.1",
        h_group="1.1.1.1",
        derived_from_uid=123456,
        context=context
    )

    # Batch load from partition results
    results = loader.accession_batch(partition_results, context=context)
"""

import logging
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Set
from enum import Enum

from .domain_overlap import (
    DomainOverlapChecker,
    OverlapSeverity,
    OverlapConflict,
    parse_range,
)

logger = logging.getLogger(__name__)


@dataclass
class ProcessingContext:
    """
    Context for tracking the source and version of auto-accessioned domains.

    This ensures we can trace every domain back to:
    - The batch it came from
    - The pyecod-mini version that partitioned it
    - The pyecod-prod version that accessioned it
    - The ECOD reference version used for BLAST/HHsearch
    """
    batch_id: str                              # e.g., "ecod_q4_2025_q1_2026"
    pyecod_mini_version: Optional[str] = None  # e.g., "2.0.2"
    pyecod_prod_version: Optional[str] = None  # e.g., "1.0.0"
    ecod_reference_version: Optional[str] = None  # e.g., "v293.1", "develop291"
    processing_date: datetime = field(default_factory=datetime.now)
    notes: Optional[str] = None

    def to_domain_version(self) -> str:
        """
        Generate a domain_version string for the domains table.

        Format: pyecod_prod_{batch_id}
        """
        return f"pyecod_prod_{self.batch_id}"

    def to_metadata_dict(self) -> Dict[str, Any]:
        """Convert to metadata dictionary for JSONB storage."""
        return {
            'batch_id': self.batch_id,
            'pyecod_mini_version': self.pyecod_mini_version,
            'pyecod_prod_version': self.pyecod_prod_version,
            'ecod_reference_version': self.ecod_reference_version,
            'processing_date': self.processing_date.isoformat(),
            'notes': self.notes
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_metadata_dict())


def get_pyecod_mini_version() -> Optional[str]:
    """Get the installed pyecod-mini version."""
    try:
        from pyecod_mini import __version__
        return __version__
    except ImportError:
        return None


def get_pyecod_prod_version() -> Optional[str]:
    """Get the installed pyecod-prod version."""
    try:
        from pyecod_prod import __version__
        return __version__
    except (ImportError, AttributeError):
        return None


class AccessionDecision(Enum):
    """Decision made for a domain accession attempt."""
    ACCEPTED = "accepted"           # Domain added to ecod_commons
    SKIPPED_DUPLICATE = "skipped_duplicate"  # Identical to existing domain
    SKIPPED_OVERLAP = "skipped_overlap"      # Severe overlap with existing
    SKIPPED_EXISTS = "skipped_exists"        # Domain ID already exists (same range)
    RENUMBERED = "renumbered"       # Domain ID collision, renumbered
    DEFERRED = "deferred"           # Moderate overlap, needs review
    FAILED = "failed"               # Error during accession


@dataclass
class AccessionResult:
    """Result of a domain accession attempt."""
    decision: AccessionDecision
    pdb_id: str
    chain_id: str
    original_domain_id: str
    final_domain_id: Optional[str] = None
    ecod_uid: Optional[int] = None
    range_definition: str = ""
    conflicts: List[OverlapConflict] = field(default_factory=list)
    message: str = ""
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    # Processing context for tracking
    context: Optional[ProcessingContext] = None


@dataclass
class BatchAccessionSummary:
    """Summary of a batch accession run."""
    total_domains: int = 0
    accepted: int = 0
    skipped_duplicate: int = 0
    skipped_overlap: int = 0
    skipped_exists: int = 0
    renumbered: int = 0
    deferred: int = 0
    failed: int = 0
    results: List[AccessionResult] = field(default_factory=list)

    def add_result(self, result: AccessionResult):
        self.results.append(result)
        self.total_domains += 1

        if result.decision == AccessionDecision.ACCEPTED:
            self.accepted += 1
        elif result.decision == AccessionDecision.SKIPPED_DUPLICATE:
            self.skipped_duplicate += 1
        elif result.decision == AccessionDecision.SKIPPED_OVERLAP:
            self.skipped_overlap += 1
        elif result.decision == AccessionDecision.SKIPPED_EXISTS:
            self.skipped_exists += 1
        elif result.decision == AccessionDecision.RENUMBERED:
            self.renumbered += 1
        elif result.decision == AccessionDecision.DEFERRED:
            self.deferred += 1
        elif result.decision == AccessionDecision.FAILED:
            self.failed += 1

    def print_summary(self):
        """Print a summary of the batch accession."""
        print(f"\n{'='*60}")
        print("Auto-Accession Summary")
        print(f"{'='*60}")
        print(f"Total domains processed: {self.total_domains}")
        print(f"  Accepted:           {self.accepted}")
        print(f"  Renumbered:         {self.renumbered}")
        print(f"  Skipped (duplicate):{self.skipped_duplicate}")
        print(f"  Skipped (overlap):  {self.skipped_overlap}")
        print(f"  Skipped (exists):   {self.skipped_exists}")
        print(f"  Deferred (review):  {self.deferred}")
        print(f"  Failed:             {self.failed}")
        print(f"{'='*60}\n")


class AutoAccessionLoader:
    """
    Load domains into ecod_commons with overlap detection and safety checks.

    This class implements the Python equivalent of the legacy Perl script's
    auto-accession logic, ensuring:
    1. No duplicate domains (identical ranges)
    2. No severe overlaps with existing domains
    3. Proper UID generation from sequence
    4. Domain ID collision handling (renumbering)
    5. Audit trail for all decisions
    """

    def __init__(
        self,
        connection_params: Optional[Dict] = None,
        overlap_checker: Optional[DomainOverlapChecker] = None,
        max_residue_overlap: int = 10,
        max_coverage: float = 0.80,
        defer_moderate_overlaps: bool = True,
        dry_run: bool = False
    ):
        """
        Initialize the auto-accession loader.

        Args:
            connection_params: Database connection parameters
            overlap_checker: Optional pre-configured overlap checker
            max_residue_overlap: Maximum allowed residue overlap
            max_coverage: Maximum allowed bidirectional coverage
            defer_moderate_overlaps: If True, moderate overlaps go to review
            dry_run: If True, don't actually insert, just check
        """
        self.connection_params = connection_params or {
            "host": "dione",
            "port": 45000,
            "database": "ecod_protein",
            "user": "ecod",
            "password": "ecod#badmin"
        }

        self.overlap_checker = overlap_checker or DomainOverlapChecker(
            connection_params=self.connection_params,
            max_residue_overlap=max_residue_overlap,
            max_coverage=max_coverage
        )

        self.max_residue_overlap = max_residue_overlap
        self.max_coverage = max_coverage
        self.defer_moderate_overlaps = defer_moderate_overlaps
        self.dry_run = dry_run

        # Cache for existing domain IDs to detect collisions
        self._domain_id_cache: Dict[str, bool] = {}
        # Cache for protein IDs
        self._protein_id_cache: Dict[Tuple[str, str], int] = {}
        # Set of PDB ID prefixes that have been fully prefetched
        self._prefetched_pdb_prefixes: Set[str] = set()

    def prefetch_domain_ids(self, domain_id_patterns: List[str]) -> int:
        """
        Prefetch domain ID existence for patterns.

        This is an optimization to avoid N individual queries for domain ID checks.
        For new PDBs, we only need to check the patterns that would be generated.

        Args:
            domain_id_patterns: List of domain ID prefixes (e.g., ["e9qf6", "e8abc"])
                               or full domain IDs

        Returns:
            Number of existing domain IDs found
        """
        if not domain_id_patterns:
            return 0

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Build LIKE conditions for prefixes
            # e.g., "e9qf6%" matches e9qf6A1, e9qf6A2, e9qf6B1, etc.
            conditions = []
            params = []
            for pattern in domain_id_patterns:
                if '%' in pattern:
                    conditions.append("domain_id LIKE %s")
                    params.append(pattern)
                else:
                    # Assume it's a prefix, add wildcard
                    conditions.append("domain_id LIKE %s")
                    params.append(f"{pattern}%")

            if not conditions:
                return 0

            query = f"""
                SELECT domain_id
                FROM ecod_commons.domains
                WHERE {' OR '.join(conditions)}
            """

            cursor.execute(query, params)

            count = 0
            for (domain_id,) in cursor.fetchall():
                self._domain_id_cache[domain_id] = True
                count += 1

            # Mark these prefixes as fully prefetched so we don't query again
            for pattern in domain_id_patterns:
                prefix = pattern.rstrip('%')
                self._prefetched_pdb_prefixes.add(prefix)

            return count

        finally:
            cursor.close()
            conn.close()

    def _get_connection(self):
        """Get database connection."""
        import psycopg2
        return psycopg2.connect(**self.connection_params)

    def _get_next_uid(self) -> int:
        """Get the next available ecod_uid from the sequence."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT nextval('ecod_commons.ecod_uid_sequence')")
            return cursor.fetchone()[0]
        finally:
            cursor.close()
            conn.close()

    def _domain_id_exists(self, domain_id: str) -> bool:
        """Check if a domain ID already exists in ecod_commons."""
        # Check direct cache hit first
        if domain_id in self._domain_id_cache:
            return self._domain_id_cache[domain_id]

        # Check if we've prefetched this PDB's domain IDs
        # Domain IDs are format: e{pdb_id}{chain_id}{domain_num}
        # So prefix is e{pdb_id} (5 chars for 4-char PDB ID)
        if len(domain_id) >= 5:
            pdb_prefix = domain_id[:5]  # e.g., "e9qf6" from "e9qf6BA1"
            if pdb_prefix in self._prefetched_pdb_prefixes:
                # We've checked all domain IDs for this PDB
                # If not in cache, it doesn't exist
                self._domain_id_cache[domain_id] = False
                return False

        # Fall back to database query
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT 1 FROM ecod_commons.domains WHERE domain_id = %s LIMIT 1",
                (domain_id,)
            )
            exists = cursor.fetchone() is not None
            self._domain_id_cache[domain_id] = exists
            return exists
        finally:
            cursor.close()
            conn.close()

    def _get_existing_domain_by_id(self, domain_id: str) -> Optional[Dict]:
        """Get existing domain info by domain_id."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT id, ecod_uid, range_definition, is_obsolete
                FROM ecod_commons.domains
                WHERE domain_id = %s
            """, (domain_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'ecod_uid': row[1],
                    'range_definition': row[2],
                    'is_obsolete': row[3]
                }
            return None
        finally:
            cursor.close()
            conn.close()

    def _get_or_create_protein(
        self,
        pdb_id: str,
        chain_id: str,
        sequence_length: Optional[int] = None
    ) -> int:
        """Get or create a protein record, returning the protein_id."""
        cache_key = (pdb_id.lower(), chain_id)
        if cache_key in self._protein_id_cache:
            return self._protein_id_cache[cache_key]

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # Try to find existing protein
            cursor.execute("""
                SELECT id FROM ecod_commons.proteins
                WHERE LOWER(pdb_id) = LOWER(%s) AND chain_id = %s AND source_type = 'pdb'
            """, (pdb_id, chain_id))

            row = cursor.fetchone()
            if row:
                protein_id = row[0]
            else:
                # Create new protein record
                source_id = f"{pdb_id.lower()}_{chain_id}"
                cursor.execute("""
                    INSERT INTO ecod_commons.proteins
                        (source_id, source_type, pdb_id, chain_id, sequence_length)
                    VALUES (%s, 'pdb', %s, %s, %s)
                    RETURNING id
                """, (source_id, pdb_id.lower(), chain_id, sequence_length))
                protein_id = cursor.fetchone()[0]
                conn.commit()

            self._protein_id_cache[cache_key] = protein_id
            return protein_id

        except Exception as e:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

    def _generate_domain_id(self, pdb_id: str, chain_id: str, domain_num: int) -> str:
        """
        Generate an ECOD domain ID.

        Format: e{pdb_id}{chain_id}{domain_num}
        Example: e8abcA1, e8abcA2
        """
        return f"e{pdb_id.lower()}{chain_id}{domain_num}"

    def _find_available_domain_id(
        self,
        pdb_id: str,
        chain_id: str,
        preferred_num: int = 1
    ) -> Tuple[str, bool]:
        """
        Find an available domain ID, handling collisions.

        Args:
            pdb_id: PDB identifier
            chain_id: Chain identifier
            preferred_num: Preferred domain number

        Returns:
            Tuple of (domain_id, was_renumbered)
        """
        domain_num = preferred_num
        domain_id = self._generate_domain_id(pdb_id, chain_id, domain_num)

        was_renumbered = False

        # Keep incrementing until we find an unused ID
        while self._domain_id_exists(domain_id):
            domain_num += 1
            domain_id = self._generate_domain_id(pdb_id, chain_id, domain_num)
            was_renumbered = True

            # Safety limit
            if domain_num > 100:
                raise ValueError(f"Too many domains on chain {pdb_id}_{chain_id}")

        return domain_id, was_renumbered

    def accession_domain(
        self,
        pdb_id: str,
        chain_id: str,
        range_definition: str,
        domain_num: int = 1,
        t_group: Optional[str] = None,
        h_group: Optional[str] = None,
        x_group: Optional[str] = None,
        f_group: Optional[str] = None,
        derived_from_uid: Optional[int] = None,
        context: Optional[ProcessingContext] = None,
        confidence: Optional[float] = None,
        sequence_length: Optional[int] = None,
        force: bool = False
    ) -> AccessionResult:
        """
        Attempt to accession a single domain to ecod_commons.

        Args:
            pdb_id: PDB identifier
            chain_id: Chain identifier
            range_definition: Domain range (e.g., "A:10-150")
            domain_num: Preferred domain number (may be renumbered)
            t_group: T-group classification
            h_group: H-group classification
            x_group: X-group classification
            f_group: F-group classification (optional)
            derived_from_uid: UID of the reference domain
            context: ProcessingContext with batch and version tracking
            confidence: Classification confidence score
            sequence_length: Sequence length for protein record
            force: Override overlap checks (like --force_replace)

        Returns:
            AccessionResult with decision and details
        """
        # Create default context if not provided
        if context is None:
            context = ProcessingContext(
                batch_id="unknown",
                pyecod_mini_version=get_pyecod_mini_version(),
                pyecod_prod_version=get_pyecod_prod_version()
            )
        original_domain_id = self._generate_domain_id(pdb_id, chain_id, domain_num)

        try:
            # Parse the range to validate
            parsed_range = parse_range(range_definition)
            if not parsed_range.segments:
                return AccessionResult(
                    decision=AccessionDecision.FAILED,
                    pdb_id=pdb_id,
                    chain_id=chain_id,
                    original_domain_id=original_domain_id,
                    range_definition=range_definition,
                    error="Invalid range definition"
                )

            # Check if domain ID already exists with same range
            existing = self._get_existing_domain_by_id(original_domain_id)
            if existing:
                existing_range = parse_range(existing['range_definition'])
                if existing_range.all_residues == parsed_range.all_residues:
                    return AccessionResult(
                        decision=AccessionDecision.SKIPPED_EXISTS,
                        pdb_id=pdb_id,
                        chain_id=chain_id,
                        original_domain_id=original_domain_id,
                        final_domain_id=original_domain_id,
                        ecod_uid=existing['ecod_uid'],
                        range_definition=range_definition,
                        message=f"Domain already exists with identical range"
                    )

            # Check for overlaps with existing domains
            can_accession, conflicts = self.overlap_checker.can_auto_accession(
                pdb_id, chain_id, range_definition
            )

            # Handle blocking conflicts (unless force)
            if not can_accession and not force:
                severe = [c for c in conflicts if c.severity == OverlapSeverity.SEVERE]
                identical = [c for c in conflicts if c.severity == OverlapSeverity.IDENTICAL]

                if identical:
                    return AccessionResult(
                        decision=AccessionDecision.SKIPPED_DUPLICATE,
                        pdb_id=pdb_id,
                        chain_id=chain_id,
                        original_domain_id=original_domain_id,
                        range_definition=range_definition,
                        conflicts=conflicts,
                        message=f"Duplicate of {identical[0].existing_domain_id}"
                    )

                if severe:
                    return AccessionResult(
                        decision=AccessionDecision.SKIPPED_OVERLAP,
                        pdb_id=pdb_id,
                        chain_id=chain_id,
                        original_domain_id=original_domain_id,
                        range_definition=range_definition,
                        conflicts=conflicts,
                        message=f"Severe overlap with {severe[0].existing_domain_id}: {severe[0].message}"
                    )

            # Check for moderate overlaps that should be deferred
            moderate = [c for c in conflicts if c.severity == OverlapSeverity.MODERATE]
            if moderate and self.defer_moderate_overlaps and not force:
                return AccessionResult(
                    decision=AccessionDecision.DEFERRED,
                    pdb_id=pdb_id,
                    chain_id=chain_id,
                    original_domain_id=original_domain_id,
                    range_definition=range_definition,
                    conflicts=conflicts,
                    message=f"Moderate overlap with {len(moderate)} domain(s) - needs review"
                )

            # Find available domain ID (handling collisions)
            final_domain_id, was_renumbered = self._find_available_domain_id(
                pdb_id, chain_id, domain_num
            )

            if was_renumbered:
                logger.info(f"Domain ID collision: {original_domain_id} -> {final_domain_id}")

            # Dry run - don't actually insert
            if self.dry_run:
                return AccessionResult(
                    decision=AccessionDecision.RENUMBERED if was_renumbered else AccessionDecision.ACCEPTED,
                    pdb_id=pdb_id,
                    chain_id=chain_id,
                    original_domain_id=original_domain_id,
                    final_domain_id=final_domain_id,
                    range_definition=range_definition,
                    conflicts=conflicts,
                    message=f"[DRY RUN] Would insert as {final_domain_id}",
                    context=context
                )

            # Get or create protein record
            protein_id = self._get_or_create_protein(pdb_id, chain_id, sequence_length)

            # Get next UID
            ecod_uid = self._get_next_uid()

            # Insert domain
            conn = self._get_connection()
            cursor = conn.cursor()

            try:
                # Use context for domain_version tracking
                domain_version = context.to_domain_version()

                cursor.execute("""
                    INSERT INTO ecod_commons.domains (
                        ecod_uid,
                        protein_id,
                        domain_version,
                        domain_id,
                        range_definition,
                        range_type,
                        sequence_length,
                        is_discontinuous,
                        classification_status,
                        classification_method,
                        classification_confidence,
                        is_representative,
                        representative_domain_id,
                        created_by
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'seqid', %s, %s,
                        'classified', 'auto_accession', %s,
                        false, %s, %s
                    )
                    RETURNING id
                """, (
                    ecod_uid,
                    protein_id,
                    domain_version,
                    final_domain_id,
                    range_definition,
                    parsed_range.total_length,
                    parsed_range.is_discontinuous,
                    confidence,
                    derived_from_uid,
                    f'pyecod_prod_{context.pyecod_prod_version or "unknown"}'
                ))

                domain_db_id = cursor.fetchone()[0]

                # Insert T-group assignment if we have T/H/X but no F
                if t_group and not f_group:
                    cursor.execute("""
                        INSERT INTO ecod_commons.t_group_only_assignments (
                            domain_id, t_group_id, h_group_id, x_group_id,
                            assignment_method, assigned_by
                        ) VALUES (%s, %s, %s, %s, 'blast', 'pyecod_prod')
                    """, (domain_db_id, t_group, h_group, x_group))

                # Insert F-group assignment if we have it
                if f_group:
                    cursor.execute("""
                        INSERT INTO ecod_commons.f_group_assignments (
                            domain_id, f_group_id, t_group_id, h_group_id, x_group_id,
                            assignment_method, assigned_by,
                            representative_domain_ecod_uid
                        ) VALUES (%s, %s, %s, %s, %s, 'blast', 'pyecod_prod', %s)
                    """, (domain_db_id, f_group, t_group, h_group, x_group, derived_from_uid))

                # Insert domain_ranges entry (PDB range)
                cursor.execute("""
                    INSERT INTO ecod_commons.domain_ranges (
                        domain_id, range_definition, range_type, is_primary,
                        source, confidence, created_date, created_by
                    ) VALUES (%s, %s, 'pdb', true, 'pyecod_prod', 1.0, NOW(), 'auto_accession')
                """, (domain_db_id, range_definition))

                conn.commit()

                # Update cache
                self._domain_id_cache[final_domain_id] = True

                return AccessionResult(
                    decision=AccessionDecision.RENUMBERED if was_renumbered else AccessionDecision.ACCEPTED,
                    pdb_id=pdb_id,
                    chain_id=chain_id,
                    original_domain_id=original_domain_id,
                    final_domain_id=final_domain_id,
                    ecod_uid=ecod_uid,
                    range_definition=range_definition,
                    conflicts=conflicts,
                    message=f"Inserted as {final_domain_id} (uid={ecod_uid})",
                    context=context
                )

            except Exception as e:
                conn.rollback()
                raise

            finally:
                cursor.close()
                conn.close()

        except Exception as e:
            logger.error(f"Failed to accession {pdb_id}_{chain_id}: {e}")
            return AccessionResult(
                decision=AccessionDecision.FAILED,
                pdb_id=pdb_id,
                chain_id=chain_id,
                original_domain_id=original_domain_id,
                range_definition=range_definition,
                error=str(e),
                context=context
            )

    def accession_batch(
        self,
        domains: List[Dict[str, Any]],
        context: Optional[ProcessingContext] = None
    ) -> BatchAccessionSummary:
        """
        Accession a batch of domains.

        Each domain dict should have:
        - pdb_id: str
        - chain_id: str
        - range_definition: str (or 'range', 'range_string')
        - domain_num: int (optional, defaults to 1)
        - t_group: str (optional)
        - h_group: str (optional)
        - x_group: str (optional)
        - f_group: str (optional)
        - derived_from_uid: int (optional)
        - confidence: float (optional)

        Args:
            domains: List of domain dicts
            context: ProcessingContext with batch and version tracking

        Returns:
            BatchAccessionSummary with results
        """
        # Create default context if not provided
        if context is None:
            context = ProcessingContext(
                batch_id="unknown",
                pyecod_mini_version=get_pyecod_mini_version(),
                pyecod_prod_version=get_pyecod_prod_version()
            )

        summary = BatchAccessionSummary()

        for i, domain in enumerate(domains):
            # Extract fields with fallbacks
            range_def = domain.get('range_definition') or domain.get('range') or domain.get('range_string', '')

            result = self.accession_domain(
                pdb_id=domain['pdb_id'],
                chain_id=domain['chain_id'],
                range_definition=range_def,
                domain_num=domain.get('domain_num', 1),
                t_group=domain.get('t_group'),
                h_group=domain.get('h_group'),
                x_group=domain.get('x_group'),
                f_group=domain.get('f_group'),
                derived_from_uid=domain.get('derived_from_uid') or domain.get('best_match_ecod_uid'),
                context=context,
                confidence=domain.get('confidence'),
                sequence_length=domain.get('sequence_length')
            )

            summary.add_result(result)

            # Log progress every 100 domains
            if (i + 1) % 100 == 0:
                logger.info(f"Processed {i + 1}/{len(domains)} domains")

        return summary

    def clear_caches(self):
        """Clear all caches."""
        self._domain_id_cache.clear()
        self._protein_id_cache.clear()
        self.overlap_checker.clear_cache()

    def accession_from_partition(
        self,
        partition_result,  # PartitionResult from partition_parser
        context: Optional[ProcessingContext] = None
    ) -> List[AccessionResult]:
        """
        Accession all domains from a partition result.

        Args:
            partition_result: PartitionResult from partition_parser
            context: ProcessingContext with batch and version tracking

        Returns:
            List of AccessionResult for each domain
        """
        from ..parsers.partition_parser import partition_to_domain_data

        results = []

        for i, domain in enumerate(partition_result.domains, 1):
            # Convert to domain data dict
            data = partition_to_domain_data(partition_result, domain, i)

            result = self.accession_domain(
                pdb_id=data['pdb_id'],
                chain_id=data['chain_id'],
                range_definition=data['range_definition'],
                domain_num=data['domain_num'],
                t_group=data['t_group'],
                h_group=data['h_group'],
                x_group=data['x_group'],
                f_group=data['family'],  # Family is F-group
                derived_from_uid=None,  # Will look up from reference_ecod_domain_id later
                context=context,
                confidence=data['confidence'],
                sequence_length=data['sequence_length']
            )

            results.append(result)

        return results

    def accession_batch_from_partitions(
        self,
        partition_results: List,  # List[PartitionResult]
        context: Optional[ProcessingContext] = None,
        min_coverage: float = 0.80,
        exclude_pdbs: Optional[set] = None
    ) -> BatchAccessionSummary:
        """
        Accession domains from multiple partition results.

        Args:
            partition_results: List of PartitionResult objects
            context: ProcessingContext with batch and version tracking
            min_coverage: Minimum coverage threshold
            exclude_pdbs: Set of PDB IDs to exclude (e.g., designed proteins)

        Returns:
            BatchAccessionSummary with all results
        """
        if context is None:
            context = ProcessingContext(
                batch_id="unknown",
                pyecod_mini_version=get_pyecod_mini_version(),
                pyecod_prod_version=get_pyecod_prod_version()
            )

        exclude_pdbs = exclude_pdbs or set()
        summary = BatchAccessionSummary()

        for i, partition in enumerate(partition_results):
            # Skip excluded PDBs (designed proteins, etc.)
            if partition.pdb_id.lower() in {p.lower() for p in exclude_pdbs}:
                logger.info(f"Skipping excluded PDB: {partition.pdb_id}")
                continue

            # Skip if below coverage threshold
            if partition.coverage < min_coverage:
                logger.debug(f"Skipping {partition.pdb_id}_{partition.chain_id}: coverage {partition.coverage:.1%} < {min_coverage:.1%}")
                continue

            # Accession all domains from this partition
            results = self.accession_from_partition(partition, context)

            for result in results:
                summary.add_result(result)

            # Log progress every 100 partitions
            if (i + 1) % 100 == 0:
                logger.info(f"Processed {i + 1}/{len(partition_results)} partitions")

        return summary


def generate_accession_report(
    summary: BatchAccessionSummary,
    context: ProcessingContext,
    partition_dir: str,
    partition_count: int,
    min_coverage: float
) -> Dict[str, Any]:
    """
    Generate a JSON-serializable report of accession results.

    Args:
        summary: BatchAccessionSummary from accession run
        context: ProcessingContext with batch/version info
        partition_dir: Path to partition directory
        partition_count: Total partition XMLs scanned
        min_coverage: Coverage threshold used

    Returns:
        Dict suitable for JSON serialization
    """
    # Calculate UID range if any were assigned
    uids = [r.ecod_uid for r in summary.results if r.ecod_uid is not None]
    uid_range = [min(uids), max(uids)] if uids else None

    report = {
        "batch_id": context.batch_id,
        "timestamp": datetime.now().isoformat(),
        "versions": {
            "pyecod_mini": context.pyecod_mini_version,
            "pyecod_prod": context.pyecod_prod_version,
            "ecod_reference": context.ecod_reference_version
        },
        "input": {
            "partition_dir": partition_dir,
            "partition_count": partition_count,
            "min_coverage": min_coverage
        },
        "summary": {
            "chains_processed": len(set(
                f"{r.pdb_id}_{r.chain_id}" for r in summary.results
            )),
            "domains_processed": summary.total_domains,
            "decisions": {
                "ACCEPTED": summary.accepted,
                "RENUMBERED": summary.renumbered,
                "SKIPPED_DUPLICATE": summary.skipped_duplicate,
                "SKIPPED_OVERLAP": summary.skipped_overlap,
                "SKIPPED_EXISTS": summary.skipped_exists,
                "DEFERRED": summary.deferred,
                "FAILED": summary.failed
            }
        },
        "database": {
            "domains_inserted": summary.accepted + summary.renumbered,
            "uid_range": uid_range,
            "domain_version": context.to_domain_version()
        },
        # Detailed results (optional, can be large)
        "results": [
            {
                "decision": r.decision.value,
                "pdb_id": r.pdb_id,
                "chain_id": r.chain_id,
                "domain_id": r.final_domain_id or r.original_domain_id,
                "ecod_uid": r.ecod_uid,
                "range": r.range_definition,
                "message": r.message,
                "error": r.error
            }
            for r in summary.results
        ]
    }

    return report
