"""
Load partition results into ecod_curation schema for manual curation.

This module writes pyecod_mini partition results to the ecod_curation staging schema
where they await manual review via pyecod_vis. After curation, proteins are accessioned
to ecod_commons via the accession script.
"""

import hashlib
import os
import psycopg2
from datetime import date
from typing import Optional, List, Dict, Any, Tuple


def get_db_connection(connection_params: Optional[Dict] = None):
    """
    Get database connection to ecod_protein database.

    Args:
        connection_params: Optional dict with host, port, database, user, password.
                         Defaults to dione:45000/ecod_protein with credentials from environment.

    Environment variables:
        ECOD_DB_PASSWORD: Database password (required if using defaults)

    Returns:
        psycopg2 connection
    """
    if connection_params is None:
        password = os.environ.get('ECOD_DB_PASSWORD')
        if not password:
            raise ValueError(
                "ECOD_DB_PASSWORD environment variable must be set. "
                "Set it in your shell: export ECOD_DB_PASSWORD='your_password'"
            )

        connection_params = {
            "host": "dione",
            "port": 45000,
            "database": "ecod_protein",
            "user": "ecod",
            "password": password
        }

    return psycopg2.connect(**connection_params)


def load_partition_to_curation(
    pdb_id: str,
    chain_id: str,
    release_date: date,
    sequence: str,
    partition_result: Dict[str, Any],
    processing_version: str = 'pyecod_prod_v1.0',
    connection_params: Optional[Dict] = None
) -> int:
    """
    Load a protein's partition results into ecod_curation schema.

    Args:
        pdb_id: PDB identifier (e.g., '8abc')
        chain_id: Chain identifier (e.g., 'A')
        release_date: PDB weekly release date
        sequence: Protein sequence
        partition_result: Dict containing:
            - coverage (float): Fraction of sequence covered by domains
            - domains (List[Dict]): List of domain dicts, each containing:
                - start (int): Domain start position
                - end (int): Domain end position
                - range_string (str): Residue range string (e.g., "10-150")
                - t_group (str): T-group assignment
                - h_group (str): H-group assignment (optional)
                - x_group (str): X-group assignment (optional)
                - f_group (str): F-group assignment (optional)
                - best_match_ecod_uid (int): ECOD UID of best match (optional)
                - assignment_method (str): 'blast', 'hhsearch', or 'inheritance'
                - classification_level (str): 'f_group_specific', 't_group_only', etc.
                - confidence (float): Assignment confidence 0-1
                - evidence (List[Dict]): List of evidence dicts, each containing:
                    - type (str): 'blast_chain', 'blast_domain', or 'hhsearch'
                    - hit_ecod_domain_id (int): ECOD domain ID (optional)
                    - hit_ecod_uid (int): ECOD UID (optional)
                    - hit_pdb_id (str): PDB ID of hit (optional)
                    - hit_chain_id (str): Chain ID of hit (optional)
                    - evalue (float): E-value
                    - score (float): Alignment score
                    - identity (float): Percent identity (optional)
                    - similarity (float): Percent similarity (optional)
                    - query_coverage (float): Query coverage fraction (optional)
                    - hit_coverage (float): Hit coverage fraction (optional)
                    - query_range (str): Query range string (optional)
                    - hit_range (str): Hit range string (optional)
                    - ref_t_group (str): Reference T-group (optional)
                    - ref_h_group (str): Reference H-group (optional)
                    - ref_x_group (str): Reference X-group (optional)
                    - ref_f_group (str): Reference F-group (optional)
                    - source_file (str): Path to BLAST XML or HHR file (optional)
        processing_version: Version string for provenance
        connection_params: Optional database connection parameters

    Returns:
        protein_id: ID of the created protein record

    Example:
        protein_id = load_partition_to_curation(
            pdb_id='8abc',
            chain_id='A',
            release_date=date(2025, 1, 20),
            sequence=seq,
            partition_result={
                'coverage': 0.95,
                'domains': [
                    {
                        'start': 10,
                        'end': 150,
                        'range_string': '10-150',
                        't_group': '1.1.13',
                        'h_group': '1.1',
                        'x_group': '1.1.13',
                        'f_group': '1.1.13.29',
                        'best_match_ecod_uid': 3066545,
                        'assignment_method': 'blast',
                        'classification_level': 'f_group_specific',
                        'confidence': 0.92,
                        'evidence': [...]
                    }
                ]
            }
        )
    """
    conn = get_db_connection(connection_params)
    cursor = conn.cursor()

    try:
        # 1. Insert protein
        cursor.execute("""
            INSERT INTO ecod_curation.protein
            (source_id, pdb_id, chain_id, release_date,
             sequence, sequence_length, sequence_md5,
             processed_at, processing_version,
             partition_coverage, domain_count, partition_quality,
             can_curate, cannot_curate_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            f"{pdb_id}_{chain_id}",
            pdb_id,
            chain_id,
            release_date,
            sequence,
            len(sequence),
            hashlib.md5(sequence.encode()).hexdigest(),
            processing_version,
            partition_result.get('coverage'),
            len(partition_result.get('domains', [])),
            classify_partition_quality(partition_result),
            can_curate(sequence, partition_result),
            get_cannot_curate_reason(sequence, partition_result)
        ))

        protein_id = cursor.fetchone()[0]

        # 2. Insert domain assignments
        for i, domain in enumerate(partition_result.get('domains', []), 1):
            cursor.execute("""
                INSERT INTO ecod_curation.domain_assignment
                (protein_id, domain_number, start_pos, end_pos, residue_range,
                 automated_start_pos, automated_end_pos, automated_range_string,
                 assigned_t_group, assigned_h_group, assigned_x_group, assigned_f_group,
                 best_match_ecod_uid, assignment_method, classification_level,
                 confidence, source, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                protein_id,
                i,
                domain.get('start'),
                domain.get('end'),
                domain.get('range_string'),
                domain.get('start'),  # Store original automated boundary
                domain.get('end'),    # Store original automated boundary
                domain.get('range_string'),  # Store original automated range
                domain.get('t_group'),
                domain.get('h_group'),
                domain.get('x_group'),
                domain.get('f_group'),  # May be NULL if only T-group assignment
                domain.get('best_match_ecod_uid'),
                domain.get('assignment_method'),  # 'blast', 'hhsearch', 'inheritance'
                domain.get('classification_level'),  # 'f_group_specific', 't_group_only', etc.
                domain.get('confidence'),
                'automated',
                processing_version
            ))

            domain_id = cursor.fetchone()[0]

            # 3. Insert evidence for this domain
            for evidence in domain.get('evidence', []):
                cursor.execute("""
                    INSERT INTO ecod_curation.domain_evidence
                    (domain_id, evidence_type,
                     hit_ecod_domain_id, hit_ecod_uid, hit_pdb_id, hit_chain_id,
                     evalue, score, identity, similarity,
                     query_coverage, hit_coverage,
                     query_range, hit_range,
                     ref_t_group, ref_h_group, ref_x_group, ref_f_group,
                     source_file)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    domain_id,
                    evidence.get('type'),  # 'blast_chain', 'blast_domain', 'hhsearch'
                    evidence.get('hit_ecod_domain_id'),
                    evidence.get('hit_ecod_uid'),
                    evidence.get('hit_pdb_id'),
                    evidence.get('hit_chain_id'),
                    evidence.get('evalue'),
                    evidence.get('score'),
                    evidence.get('identity'),
                    evidence.get('similarity'),
                    evidence.get('query_coverage'),
                    evidence.get('hit_coverage'),
                    evidence.get('query_range'),
                    evidence.get('hit_range'),
                    evidence.get('ref_t_group'),
                    evidence.get('ref_h_group'),
                    evidence.get('ref_x_group'),
                    evidence.get('ref_f_group'),
                    evidence.get('source_file')  # Relative path to BLAST XML or HHR
                ))

        # 4. Optionally add to curation queue
        should_queue, reason = should_queue_for_curation(partition_result)
        if should_queue:
            priority = calculate_queue_priority(partition_result)

            cursor.execute("""
                INSERT INTO ecod_curation.curation_queue
                (protein_id, priority, priority_reason)
                VALUES (%s, %s, %s)
            """, (protein_id, priority, reason))

        conn.commit()
        return protein_id

    except Exception as e:
        conn.rollback()
        raise Exception(f"Failed to load {pdb_id}_{chain_id} to ecod_curation: {e}") from e

    finally:
        cursor.close()
        conn.close()


def classify_partition_quality(result: Dict[str, Any]) -> str:
    """
    Classify partition quality based on coverage and confidence.

    Args:
        result: Partition result dict with 'coverage' and 'domains' keys

    Returns:
        One of: 'good', 'low_coverage', 'fragmentary', or 'failed'
    """
    coverage = result.get('coverage', 0.0)
    domains = result.get('domains', [])

    if not domains:
        return 'failed'

    min_confidence = min(d.get('confidence', 0.0) for d in domains)

    if coverage >= 0.9 and min_confidence >= 0.8:
        return 'good'
    elif coverage < 0.5:
        return 'fragmentary'
    elif coverage < 0.8:
        return 'low_coverage'
    else:
        return 'good'


def can_curate(sequence: str, result: Dict[str, Any]) -> bool:
    """
    Determine if protein is suitable for curation.

    Returns False for peptides, nucleic acids, etc.

    Args:
        sequence: Protein sequence
        result: Partition result dict (currently unused but available for future logic)

    Returns:
        True if protein can be curated, False otherwise
    """
    # Too short (peptide)
    if len(sequence) < 50:
        return False

    # Check for nucleic acid (simple heuristic)
    nucleic_chars = sum(1 for c in sequence.upper() if c in 'ATCGUN')
    if nucleic_chars / len(sequence) > 0.5:
        return False

    return True


def get_cannot_curate_reason(sequence: str, result: Dict[str, Any]) -> Optional[str]:
    """
    Get reason why protein cannot be curated, if any.

    Args:
        sequence: Protein sequence
        result: Partition result dict (currently unused but available for future logic)

    Returns:
        Reason string if cannot curate, None otherwise
    """
    if len(sequence) < 50:
        return 'too_short'

    nucleic_chars = sum(1 for c in sequence.upper() if c in 'ATCGUN')
    if nucleic_chars / len(sequence) > 0.5:
        return 'nucleic_acid'

    return None


def should_queue_for_curation(result: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Decide if protein should be added to curation queue.

    Heuristics:
    - Low confidence domains → needs review
    - Low coverage → needs review
    - Novel architecture → needs review
    - High confidence + good coverage → auto-accept (skip queue)

    Args:
        result: Partition result dict with 'coverage' and 'domains' keys

    Returns:
        Tuple of (should_queue: bool, reason: str)
    """
    domains = result.get('domains', [])

    if not domains:
        return (True, 'no_domains')

    min_confidence = min(d.get('confidence', 0.0) for d in domains)
    coverage = result.get('coverage', 0.0)

    # Low confidence
    if min_confidence < 0.7:
        return (True, 'low_confidence')

    # Low coverage
    if coverage < 0.8:
        return (True, 'low_coverage')

    # Check for novel architecture (no f-group assigned)
    has_unassigned = any(d.get('f_group') is None for d in domains)
    if has_unassigned:
        return (True, 'incomplete_classification')

    # Conflicting evidence (multiple strong hits with different classifications)
    # TODO: Implement this check when we have more complex evidence logic

    # High quality - can auto-accept
    return (False, 'auto_accepted')


def calculate_queue_priority(result: Dict[str, Any]) -> int:
    """
    Calculate priority for curation queue.

    Higher number = higher priority

    Priority scale:
    10 = Very low confidence or major issues
    5  = Medium confidence or partial classification
    1  = Minor issues or borderline cases

    Args:
        result: Partition result dict with 'coverage' and 'domains' keys

    Returns:
        Priority integer (1-10)
    """
    domains = result.get('domains', [])
    coverage = result.get('coverage', 0.0)

    if not domains:
        return 10  # Very urgent - no domains found

    min_confidence = min(d.get('confidence', 0.0) for d in domains)

    if min_confidence < 0.5:
        return 10  # Very urgent

    if coverage < 0.6:
        return 8  # High priority

    if min_confidence < 0.7:
        return 5  # Medium priority

    if coverage < 0.8:
        return 3  # Lower priority

    return 1  # Low priority
