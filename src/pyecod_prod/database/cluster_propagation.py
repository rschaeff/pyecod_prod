"""
Cluster propagation module for ECOD domain assignments.

This module handles propagating domain classifications from cluster representatives
to their members. For 70% identity clusters, we use a tiered approach:

Tier 1 (auto-propagate):
    - Length difference ≤10%
    - Copy domain assignments directly

Tier 2 (verify domain count):
    - Length difference 10-20%
    - Only propagate if member and representative have same domain count

Tier 3 (full re-classify):
    - Length difference >20%
    - Member needs full pyecod-mini classification

Ranges (Tiers 1 and 2): the rep's seqid ranges are carried onto the member through a
sequence alignment of the two construct sequences, then translated to the member's
author numbering for domain_ranges (see range_mapping.py). A member whose ranges do not
map cleanly is reported as RANGE_UNMAPPABLE and gets no domains.

Members that already have active domains are skipped (ALREADY_CLASSIFIED), so a batch
can be rerun safely.

Usage:
    from pyecod_prod.database.cluster_propagation import ClusterPropagator

    propagator = ClusterPropagator()

    # Propagate from a single representative to its members
    results = propagator.propagate_from_representative(
        rep_pdb_id="8abc",
        rep_chain_id="A",
        batch_id="ecod_q4_2025_q1_2026"
    )

    # Or propagate all in a batch
    summary = propagator.propagate_batch(batch_id="ecod_q4_2025_q1_2026")
"""

from .group_ids import clean_f_group
from .range_mapping import RangeMapper, RangeMappingError
from .versions import current_development_version_id
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Set
from enum import Enum

logger = logging.getLogger(__name__)

# Default connection parameters
DEFAULT_CONNECTION_PARAMS = {
    'host': os.environ.get('ECOD_DB_HOST', 'dione'),
    'port': int(os.environ.get('ECOD_DB_PORT', '45000')),
    'database': os.environ.get('ECOD_DB_NAME', 'ecod_protein'),
    'user': os.environ.get('ECOD_DB_USER', 'ecod'),
    'password': os.environ.get('ECOD_DB_PASSWORD', ''),
}


class PropagationTier(Enum):
    """Tier classification for cluster member propagation."""
    TIER1_AUTO = "tier1_auto"        # ≤10% length diff, auto-propagate
    TIER2_VERIFY = "tier2_verify"    # 10-20% length diff, verify domain count
    TIER3_RECLASSIFY = "tier3_reclassify"  # >20% length diff, needs full classification
    SINGLETON = "singleton"           # No members to propagate to
    ALREADY_CLASSIFIED = "already_classified"  # Member already has domains
    RANGE_UNMAPPABLE = "range_unmappable"  # Rep ranges don't map cleanly onto member


@dataclass
class PropagationResult:
    """Result of propagating to a single cluster member."""
    member_pdb_id: str
    member_chain_id: str
    representative_pdb_id: str
    representative_chain_id: str
    tier: PropagationTier
    success: bool
    domains_propagated: int = 0
    length_diff_pct: float = 0.0
    message: str = ""
    error: Optional[str] = None


@dataclass
class PropagationSummary:
    """Summary of propagation for a batch."""
    batch_id: str
    total_representatives: int = 0
    total_members: int = 0
    tier1_propagated: int = 0
    tier2_propagated: int = 0
    tier2_skipped: int = 0  # Domain count mismatch
    tier3_needs_reclassify: int = 0
    already_classified: int = 0
    range_unmappable: int = 0
    failed: int = 0
    total_domains_propagated: int = 0
    results: List[PropagationResult] = field(default_factory=list)

    def print_summary(self):
        """Print a summary of propagation results."""
        print(f"\n{'='*60}")
        print(f"Cluster Propagation Summary")
        print(f"{'='*60}")
        print(f"Batch: {self.batch_id}")
        print(f"Representatives processed: {self.total_representatives}")
        print(f"Total members: {self.total_members}")
        print(f"\nPropagation Results:")
        print(f"  Tier 1 (auto): {self.tier1_propagated}")
        print(f"  Tier 2 (verified): {self.tier2_propagated}")
        print(f"  Tier 2 (skipped - domain count mismatch): {self.tier2_skipped}")
        print(f"  Tier 3 (needs re-classify): {self.tier3_needs_reclassify}")
        print(f"  Already classified: {self.already_classified}")
        print(f"  Range unmappable (needs re-classify): {self.range_unmappable}")
        print(f"  Failed: {self.failed}")
        print(f"\nTotal domains propagated: {self.total_domains_propagated}")
        print(f"{'='*60}\n")


class ClusterPropagator:
    """
    Handles propagation of domain assignments from representatives to cluster members.
    """

    # Length difference thresholds for tiering
    TIER1_MAX_LENGTH_DIFF = 0.10  # 10%
    TIER2_MAX_LENGTH_DIFF = 0.20  # 20%

    def __init__(
        self,
        tier1_max_length_diff: float = 0.10,
        tier2_max_length_diff: float = 0.20,
        dry_run: bool = False,
        connection_params: Optional[Dict] = None,
        range_mapper: Optional[RangeMapper] = None,
        pdb_mirror_path: str = "/usr2/pdb/data/structures/divided/mmCIF",
    ):
        """
        Initialize the propagator.

        Args:
            tier1_max_length_diff: Max length difference for Tier 1 auto-propagation
            tier2_max_length_diff: Max length difference for Tier 2 verification
            dry_run: If True, don't actually insert into database
            connection_params: Database connection parameters (uses defaults if not provided)
            range_mapper: Maps rep seqid ranges onto members; built over pdb_mirror_path
                if not given
            pdb_mirror_path: Local mmCIF mirror (divided layout)
        """
        self.tier1_max_length_diff = tier1_max_length_diff
        self.tier2_max_length_diff = tier2_max_length_diff
        self.dry_run = dry_run
        self.connection_params = connection_params or DEFAULT_CONNECTION_PARAMS
        if range_mapper is None:
            from ..parsers.pdb_status import PDBStatusParser
            locator = PDBStatusParser(pdb_mirror_path=pdb_mirror_path,
                                      filter_designed_proteins=False)
            range_mapper = RangeMapper(locator.get_mmcif_path)
        self.range_mapper = range_mapper
        # ecod_commons.versions.id stamped on every inserted row; resolved on first insert
        self._version_id: Optional[int] = None

    def _get_connection(self):
        """Get a database connection."""
        import psycopg2
        return psycopg2.connect(**self.connection_params)

    def _get_version_id(self, conn) -> int:
        """ecod_commons.versions.id of the current development release (cached)."""
        if getattr(self, "_version_id", None) is None:
            self._version_id = current_development_version_id(conn)
        return self._version_id

    def classify_member_tier(
        self,
        member_length: int,
        rep_length: int
    ) -> PropagationTier:
        """
        Classify a member into a propagation tier based on length difference.

        Args:
            member_length: Sequence length of member
            rep_length: Sequence length of representative

        Returns:
            PropagationTier indicating how to handle this member
        """
        if rep_length == 0:
            return PropagationTier.TIER3_RECLASSIFY

        length_diff_pct = abs(member_length - rep_length) / rep_length

        if length_diff_pct <= self.tier1_max_length_diff:
            return PropagationTier.TIER1_AUTO
        elif length_diff_pct <= self.tier2_max_length_diff:
            return PropagationTier.TIER2_VERIFY
        else:
            return PropagationTier.TIER3_RECLASSIFY

    def get_representative_domains(
        self,
        pdb_id: str,
        chain_id: str,
        domain_version: str
    ) -> List[Dict]:
        """
        Get domain assignments for a representative.

        Args:
            pdb_id: PDB ID of representative
            chain_id: Chain ID of representative
            domain_version: Domain version string

        Returns:
            List of domain dicts with range, family assignments, etc.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT
                    d.id, d.domain_id, d.ecod_uid, d.range_definition,
                    d.is_discontinuous, d.classification_confidence, d.representative_domain_id,
                    fa.f_group_id, fa.t_group_id, fa.h_group_id, fa.x_group_id,
                    fa.representative_domain_ecod_uid
                FROM ecod_commons.domains d
                JOIN ecod_commons.proteins p ON d.protein_id = p.id
                LEFT JOIN ecod_commons.f_group_assignments fa ON d.id = fa.domain_id
                WHERE LOWER(p.pdb_id) = LOWER(%s)
                AND p.chain_id = %s
                AND d.domain_version = %s
                AND d.is_obsolete = false
                ORDER BY d.domain_id
            """, (pdb_id, chain_id, domain_version))

            domains = []
            for row in cursor.fetchall():
                domains.append({
                    'id': row[0],
                    'domain_id': row[1],
                    'ecod_uid': row[2],
                    'range_definition': row[3],
                    'is_discontinuous': row[4],
                    'confidence': row[5],
                    'representative_domain_id': row[6],
                    'f_group': row[7],
                    't_group': row[8],
                    'h_group': row[9],
                    'x_group': row[10],
                    'representative_uid': row[11]
                })

            return domains

        finally:
            cursor.close()
            conn.close()

    def get_cluster_members(
        self,
        rep_pdb_id: str,
        rep_chain_id: str,
        release_dates: Optional[Tuple[str, str]] = None
    ) -> List[Dict]:
        """
        Get all cluster members for a representative.

        Args:
            rep_pdb_id: PDB ID of representative
            rep_chain_id: Chain ID of representative
            release_dates: Optional (start, end) date range

        Returns:
            List of member dicts with pdb_id, chain_id, sequence_length
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # chain_status is keyed on (pdb_id, chain_id, release_date), so a chain
            # can appear more than once; return each chain once (latest release).
            query = """
                SELECT DISTINCT ON (pdb_id, chain_id)
                    pdb_id, chain_id, sequence_length, ecod_status
                FROM pdb_update.chain_status
                WHERE representative_pdb_id = %s
                AND representative_chain_id = %s
                AND is_representative = false
            """
            params = [rep_pdb_id, rep_chain_id]

            if release_dates:
                query += " AND release_date BETWEEN %s AND %s"
                params.extend(release_dates)

            query += " ORDER BY pdb_id, chain_id, release_date DESC"
            cursor.execute(query, params)

            members = []
            for row in cursor.fetchall():
                members.append({
                    'pdb_id': row[0],
                    'chain_id': row[1],
                    'sequence_length': row[2],
                    'ecod_status': row[3]
                })

            return members

        finally:
            cursor.close()
            conn.close()

    def get_chains_with_domains(
        self,
        chains: List[Tuple[str, str]]
    ) -> Dict[Tuple[str, str], int]:
        """
        Find which PDB chains already have active (non-obsolete) domains.

        This is the idempotency check. It reads ecod_commons directly rather than
        pdb_update.chain_status.ecod_status, which is not kept in sync.

        Args:
            chains: (pdb_id, chain_id) pairs; pdb_id case is ignored

        Returns:
            {(lowercase pdb_id, chain_id): active domain count} for chains with any
        """
        if not chains:
            return {}

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT LOWER(p.pdb_id), p.chain_id, COUNT(d.id)
                FROM ecod_commons.proteins p
                JOIN ecod_commons.domains d
                  ON d.protein_id = p.id AND d.is_obsolete = false
                WHERE p.pdb_id = ANY(%s)  -- uses idx_proteins_pdb_id
                AND (LOWER(p.pdb_id), p.chain_id) IN (
                    SELECT * FROM unnest(%s::text[], %s::text[])
                )
                GROUP BY 1, 2
            """, (
                sorted({v for p, _ in chains for v in (p.lower(), p.upper())}),
                [p.lower() for p, _ in chains],
                [c for _, c in chains],
            ))
            return {(pdb, chain): n for pdb, chain, n in cursor.fetchall()}
        finally:
            cursor.close()
            conn.close()

    def _already_classified(
        self,
        member_pdb_id: str,
        member_chain_id: str,
        rep_pdb_id: str,
        rep_chain_id: str,
        n_domains: int
    ) -> PropagationResult:
        return PropagationResult(
            member_pdb_id=member_pdb_id,
            member_chain_id=member_chain_id,
            representative_pdb_id=rep_pdb_id,
            representative_chain_id=rep_chain_id,
            tier=PropagationTier.ALREADY_CLASSIFIED,
            success=True,
            message=f"Already has {n_domains} active domains; skipped"
        )

    def propagate_to_member(
        self,
        member_pdb_id: str,
        member_chain_id: str,
        rep_domains: List[Dict],
        domain_version: str,
        tier: PropagationTier,
        member_ranges: List[Tuple[str, str]],
    ) -> PropagationResult:
        """
        Propagate domain assignments from representative to a single member.

        Args:
            member_pdb_id: PDB ID of member
            member_chain_id: Chain ID of member
            rep_domains: Domain assignments from representative
            domain_version: Domain version string for tracking
            tier: The propagation tier for this member
            member_ranges: (seqid range, author range) on the member, one per rep
                domain in the same order, from RangeMapper.map_member

        Returns:
            PropagationResult with outcome details
        """
        if len(member_ranges) != len(rep_domains):
            raise ValueError(
                f"{len(member_ranges)} member ranges for {len(rep_domains)} rep domains")

        if self.dry_run:
            return PropagationResult(
                member_pdb_id=member_pdb_id,
                member_chain_id=member_chain_id,
                representative_pdb_id=rep_domains[0]['domain_id'][:5] if rep_domains else "",
                representative_chain_id="",
                tier=tier,
                success=True,
                domains_propagated=len(rep_domains),
                message=f"Would propagate {len(rep_domains)} domains (dry run)"
            )

        conn = self._get_connection()
        version_id = self._get_version_id(conn)
        cursor = conn.cursor()

        try:
            # Get or create protein record for member. FOR UPDATE serializes
            # concurrent propagations to the same chain, so the domain check
            # below cannot race another run's insert.
            cursor.execute("""
                SELECT id FROM ecod_commons.proteins
                WHERE pdb_id IN (LOWER(%s), UPPER(%s)) AND chain_id = %s
                ORDER BY id
                FOR UPDATE
            """, (member_pdb_id, member_pdb_id, member_chain_id))

            result = cursor.fetchone()
            if result:
                protein_id = result[0]

                # Idempotency guard: never add a second set of domains to a chain
                # that already has active ones (from this or any other version).
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM ecod_commons.domains d
                    JOIN ecod_commons.proteins p ON p.id = d.protein_id
                    WHERE p.pdb_id IN (LOWER(%s), UPPER(%s)) AND p.chain_id = %s
                    AND d.is_obsolete = false
                """, (member_pdb_id, member_pdb_id, member_chain_id))
                n_existing = cursor.fetchone()[0]
                if n_existing:
                    conn.rollback()
                    return self._already_classified(
                        member_pdb_id, member_chain_id, "", "", n_existing
                    )
            else:
                # Create protein record
                source_id = f"{member_pdb_id}_{member_chain_id}"
                cursor.execute("""
                    INSERT INTO ecod_commons.proteins (source_id, source_type, pdb_id, chain_id)
                    VALUES (%s, 'pdb', %s, %s)
                    RETURNING id
                """, (source_id, member_pdb_id, member_chain_id))
                protein_id = cursor.fetchone()[0]

            domains_created = 0

            for i, (rep_domain, (member_range, member_pdb_range)) in enumerate(
                zip(rep_domains, member_ranges), 1
            ):
                # Generate domain ID for member
                # Replace the representative's PDB/chain with member's.
                # Multi-char chains get a '_' separator before the ordinal to avoid
                # id collisions (see parsers.generate_ecod_domain_id).
                _sep = "_" if len(member_chain_id) > 1 else ""
                member_domain_id = f"e{member_pdb_id.lower()}{member_chain_id}{_sep}{i}"

                # Get new UID
                cursor.execute("SELECT nextval('ecod_commons.ecod_uid_sequence')")
                new_uid = cursor.fetchone()[0]

                # Insert domain
                cursor.execute("""
                    INSERT INTO ecod_commons.domains (
                        protein_id, domain_id, ecod_uid, range_definition,
                        range_type, is_discontinuous, classification_confidence,
                        representative_domain_id, domain_version, is_obsolete, version_id
                    ) VALUES (%s, %s, %s, %s, 'seqid', %s, %s, %s, %s, false, %s)
                    RETURNING id
                """, (
                    protein_id,
                    member_domain_id,
                    new_uid,
                    member_range,
                    ',' in member_range,
                    rep_domain['confidence'],
                    rep_domain['id'],  # Link to representative's domain ID (primary key)
                    f"{domain_version}_propagated",
                    version_id
                ))

                domain_db_id = cursor.fetchone()[0]

                # Backstop: a representative carrying a malformed f_group_id must not
                # propagate it to every cluster member. This is how 26 of the 51 bad
                # rows in repair item 5 arose -- inheritance faithfully copying a bad
                # value. Falls through to the t_group branch below.
                rep_f_group = clean_f_group(
                    rep_domain['f_group'],
                    context=f"cluster member {member_domain_id} of rep {rep_domain['ecod_uid']}",
                    log=logger,
                )

                # Insert F-group assignment
                if rep_f_group:
                    cursor.execute("""
                        INSERT INTO ecod_commons.f_group_assignments (
                            domain_id, f_group_id, t_group_id, h_group_id, x_group_id,
                            assignment_method, assigned_by,
                            representative_domain_ecod_uid, version_id
                        ) VALUES (%s, %s, %s, %s, %s, 'inheritance', 'pyecod_prod', %s, %s)
                    """, (
                        domain_db_id,
                        rep_f_group,
                        rep_domain['t_group'],
                        rep_domain['h_group'],
                        rep_domain['x_group'],
                        rep_domain['ecod_uid'],
                        version_id
                    ))
                elif rep_domain['t_group']:
                    # T-group only assignment
                    cursor.execute("""
                        INSERT INTO ecod_commons.t_group_only_assignments (
                            domain_id, t_group_id, h_group_id, x_group_id,
                            assignment_method, assigned_by, version_id
                        ) VALUES (%s, %s, %s, %s, 'inheritance', 'pyecod_prod', %s)
                    """, (
                        domain_db_id,
                        rep_domain['t_group'],
                        rep_domain['h_group'],
                        rep_domain['x_group'],
                        version_id
                    ))

                # Insert domain_ranges entry: AUTHOR numbering, never the seqid range
                cursor.execute("""
                    INSERT INTO ecod_commons.domain_ranges (
                        domain_id, range_definition, range_type, is_primary,
                        source, confidence, created_date, created_by
                    ) VALUES (%s, %s, 'pdb', true, 'pyecod_prod', 1.0, NOW(), 'propagation')
                """, (domain_db_id, member_pdb_range))

                domains_created += 1

            conn.commit()

            return PropagationResult(
                member_pdb_id=member_pdb_id,
                member_chain_id=member_chain_id,
                representative_pdb_id="",
                representative_chain_id="",
                tier=tier,
                success=True,
                domains_propagated=domains_created,
                message=f"Propagated {domains_created} domains"
            )

        except Exception as e:
            conn.rollback()
            return PropagationResult(
                member_pdb_id=member_pdb_id,
                member_chain_id=member_chain_id,
                representative_pdb_id="",
                representative_chain_id="",
                tier=tier,
                success=False,
                error=str(e),
                message=f"Failed: {e}"
            )

        finally:
            cursor.close()
            conn.close()

    def propagate_from_representative(
        self,
        rep_pdb_id: str,
        rep_chain_id: str,
        domain_version: str,
        release_dates: Optional[Tuple[str, str]] = None
    ) -> List[PropagationResult]:
        """
        Propagate domain assignments from a single representative to all its members.

        Args:
            rep_pdb_id: PDB ID of representative
            rep_chain_id: Chain ID of representative
            domain_version: Domain version string
            release_dates: Optional date range filter

        Returns:
            List of PropagationResults for each member
        """
        results = []

        # Get representative's domains
        rep_domains = self.get_representative_domains(
            rep_pdb_id, rep_chain_id, domain_version
        )

        if not rep_domains:
            logger.warning(f"No domains found for representative {rep_pdb_id}_{rep_chain_id}")
            return results

        # Get representative's sequence length from first domain's chain
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT sequence_length FROM pdb_update.chain_status
                WHERE pdb_id = %s AND chain_id = %s
            """, (rep_pdb_id, rep_chain_id))
            row = cursor.fetchone()
            rep_length = row[0] if row else 0
        finally:
            cursor.close()
            conn.close()

        # Get cluster members
        members = self.get_cluster_members(
            rep_pdb_id, rep_chain_id, release_dates
        )

        # Skip members that already have active domains. This is checked against
        # ecod_commons, not chain_status.ecod_status: that flag is stale, and
        # trusting it let reruns insert a second copy of every member's domains.
        existing = self.get_chains_with_domains(
            [(m['pdb_id'], m['chain_id']) for m in members]
        )

        for member in members:
            n_existing = existing.get((member['pdb_id'].lower(), member['chain_id']), 0)
            if n_existing:
                results.append(self._already_classified(
                    member['pdb_id'], member['chain_id'],
                    rep_pdb_id, rep_chain_id, n_existing
                ))
                continue

            # Classify tier
            tier = self.classify_member_tier(
                member['sequence_length'],
                rep_length
            )

            length_diff_pct = abs(member['sequence_length'] - rep_length) / rep_length if rep_length > 0 else 1.0

            if tier in (PropagationTier.TIER1_AUTO, PropagationTier.TIER2_VERIFY):
                # Tier 2's domain-count check is still a placeholder; both tiers
                # propagate, but only through an alignment-based range mapping.
                try:
                    member_ranges = self.range_mapper.map_member(
                        rep_pdb_id, rep_chain_id,
                        member['pdb_id'], member['chain_id'],
                        [d['range_definition'] for d in rep_domains],
                    )
                except RangeMappingError as e:
                    results.append(PropagationResult(
                        member_pdb_id=member['pdb_id'],
                        member_chain_id=member['chain_id'],
                        representative_pdb_id=rep_pdb_id,
                        representative_chain_id=rep_chain_id,
                        tier=PropagationTier.RANGE_UNMAPPABLE,
                        success=False,
                        length_diff_pct=length_diff_pct,
                        message=f"Range mapping failed: {e}"
                    ))
                    continue

                result = self.propagate_to_member(
                    member['pdb_id'],
                    member['chain_id'],
                    rep_domains,
                    domain_version,
                    tier,
                    member_ranges=member_ranges,
                )
                result.length_diff_pct = length_diff_pct
                results.append(result)

            else:  # TIER3_RECLASSIFY
                # Don't propagate, needs full re-classification
                results.append(PropagationResult(
                    member_pdb_id=member['pdb_id'],
                    member_chain_id=member['chain_id'],
                    representative_pdb_id=rep_pdb_id,
                    representative_chain_id=rep_chain_id,
                    tier=PropagationTier.TIER3_RECLASSIFY,
                    success=False,
                    length_diff_pct=length_diff_pct,
                    message=f"Needs re-classification (length diff: {length_diff_pct:.1%})"
                ))

        return results

    def propagate_batch(
        self,
        domain_version: str,
        release_dates: Optional[Tuple[str, str]] = None,
        limit: Optional[int] = None
    ) -> PropagationSummary:
        """
        Propagate domain assignments for all representatives in a batch.

        Args:
            domain_version: Domain version string (e.g., "pyecod_prod_ecod_q4_2025_q1_2026")
            release_dates: Optional date range filter
            limit: Optional limit on number of representatives to process

        Returns:
            PropagationSummary with overall results
        """
        summary = PropagationSummary(batch_id=domain_version)

        # Get all representatives with domains in this version
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            query = """
                SELECT DISTINCT p.pdb_id, p.chain_id
                FROM ecod_commons.domains d
                JOIN ecod_commons.proteins p ON d.protein_id = p.id
                WHERE d.domain_version = %s
                AND d.is_obsolete = false
            """
            params = [domain_version]

            if limit:
                query += " LIMIT %s"
                params.append(limit)

            cursor.execute(query, params)
            representatives = cursor.fetchall()

        finally:
            cursor.close()
            conn.close()

        summary.total_representatives = len(representatives)
        logger.info(f"Processing {len(representatives)} representatives")

        for i, (rep_pdb_id, rep_chain_id) in enumerate(representatives, 1):
            if i % 100 == 0:
                logger.info(f"Processed {i}/{len(representatives)} representatives")

            results = self.propagate_from_representative(
                rep_pdb_id, rep_chain_id, domain_version, release_dates
            )

            for result in results:
                summary.results.append(result)
                summary.total_members += 1

                if result.tier == PropagationTier.TIER1_AUTO:
                    if result.success:
                        summary.tier1_propagated += 1
                        summary.total_domains_propagated += result.domains_propagated
                    else:
                        summary.failed += 1

                elif result.tier == PropagationTier.TIER2_VERIFY:
                    if result.success:
                        summary.tier2_propagated += 1
                        summary.total_domains_propagated += result.domains_propagated
                    else:
                        summary.tier2_skipped += 1

                elif result.tier == PropagationTier.TIER3_RECLASSIFY:
                    summary.tier3_needs_reclassify += 1

                elif result.tier == PropagationTier.ALREADY_CLASSIFIED:
                    summary.already_classified += 1

                elif result.tier == PropagationTier.RANGE_UNMAPPABLE:
                    summary.range_unmappable += 1

        return summary
