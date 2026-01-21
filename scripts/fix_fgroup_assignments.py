#!/usr/bin/env python3
"""
Fix F-group assignments for auto-accessioned domains.

The issue: Auto-accession stored T-group IDs in f_group_id column.
F-group IDs can ONLY be assigned via Pfam/hmmscan, not inherited from BLAST hits.

Correct behavior:
- T-group comes from BLAST hit reference domain
- F-group comes from Pfam assignment (Track 1: matching existing F-group)
- Domains without Pfam F-group match should have f_group_id = NULL

This script:
1. Clears f_group_id for domains that have T-group IDs stored there
2. For domains with UniProt/PDB IDs, recovers T-group from reference and clears f_group_id
3. Optionally archives bad partition files

Usage:
    # Dry run (preview changes)
    python scripts/fix_fgroup_assignments.py --dry-run

    # Apply fixes and cleanup
    python scripts/fix_fgroup_assignments.py --cleanup-bad-files
"""

import os
import sys
import argparse
import logging
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import xml.etree.ElementTree as ET

import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database connection parameters
DEFAULT_CONNECTION_PARAMS = {
    'host': os.environ.get('ECOD_DB_HOST', 'dione'),
    'port': int(os.environ.get('ECOD_DB_PORT', '45000')),
    'user': os.environ.get('ECOD_DB_USER', 'ecod'),
    'password': os.environ.get('ECOD_DB_PASSWORD', ''),
    'dbname': os.environ.get('ECOD_DB_NAME', 'ecod_protein'),
}

DEFAULT_BATCH_DIR = Path("/data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026")


def get_connection():
    """Get database connection."""
    return psycopg2.connect(**DEFAULT_CONNECTION_PARAMS)


def categorize_fgroup_ids(conn) -> Dict[str, List[Dict]]:
    """
    Categorize domains by their f_group_id type.

    Returns dict with keys:
    - 't_group': Domains with T-group IDs (X.H.T format)
    - 'uniprot': Domains with UniProt accessions
    - 'pdb': Domains with PDB IDs
    - 'valid_fgroup': Domains with valid F-group IDs (X.H.T.F format)
    """
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            d.id, d.domain_id, d.domain_version,
            fa.f_group_id, fa.t_group_id, fa.h_group_id, fa.x_group_id,
            fa.representative_domain_ecod_uid
        FROM ecod_commons.domains d
        JOIN ecod_commons.f_group_assignments fa ON d.id = fa.domain_id
        WHERE d.domain_version LIKE 'pyecod_prod_ecod_q4_2025_q1_2026%%'
        ORDER BY d.domain_id
    """)

    categories = {
        't_group': [],      # T-group ID in f_group_id (need to clear)
        'uniprot': [],      # UniProt accession (need to fix T-group too)
        'pdb': [],          # PDB ID (need to fix T-group too)
        'valid_fgroup': [], # Valid F-group ID (keep)
    }

    for row in cursor:
        domain = {
            'db_id': row[0],
            'domain_id': row[1],
            'domain_version': row[2],
            'f_group_id': row[3],
            't_group_id': row[4],
            'h_group_id': row[5],
            'x_group_id': row[6],
            'rep_uid': row[7],
        }

        f_group = row[3] or ''

        # Categorize by f_group_id pattern
        if re.match(r'^\d+\.\d+\.\d+\.\d+$', f_group):
            # Valid F-group (X.H.T.F)
            categories['valid_fgroup'].append(domain)
        elif re.match(r'^\d+\.\d+\.\d+$', f_group):
            # T-group ID (X.H.T) - stored incorrectly
            categories['t_group'].append(domain)
        elif re.match(r'^[A-Z][0-9A-Z]{4,9}$', f_group):
            # UniProt accession
            categories['uniprot'].append(domain)
        elif re.match(r'^[0-9a-z]{4}$', f_group):
            # PDB ID
            categories['pdb'].append(domain)

    cursor.close()
    return categories


def lookup_tgroup_from_reference(conn, reference_domain_id: str) -> Optional[Dict]:
    """
    Look up T-group hierarchy from a reference ECOD domain.

    Args:
        conn: Database connection
        reference_domain_id: ECOD domain ID (e.g., "e5gl6A2")

    Returns:
        Dict with t_group, h_group, x_group or None
    """
    cursor = conn.cursor()

    # Try f_group_assignments first (for domains with F-groups)
    cursor.execute("""
        SELECT fa.t_group_id, fa.h_group_id, fa.x_group_id
        FROM ecod_commons.domains d
        JOIN ecod_commons.f_group_assignments fa ON d.id = fa.domain_id
        WHERE d.domain_id = %s
        LIMIT 1
    """, (reference_domain_id,))

    row = cursor.fetchone()
    if row and row[0]:
        cursor.close()
        return {
            't_group': row[0],
            'h_group': row[1],
            'x_group': row[2],
        }

    # Try t_group_only_assignments (for T-group only domains)
    cursor.execute("""
        SELECT ta.t_group_id, ta.h_group_id, ta.x_group_id
        FROM ecod_commons.domains d
        JOIN ecod_commons.t_group_only_assignments ta ON d.id = ta.domain_id
        WHERE d.domain_id = %s
        LIMIT 1
    """, (reference_domain_id,))

    row = cursor.fetchone()
    cursor.close()

    if row and row[0]:
        return {
            't_group': row[0],
            'h_group': row[1],
            'x_group': row[2],
        }

    return None


def parse_partition_xml(xml_path: Path) -> Dict:
    """Parse partition XML and extract domain hierarchy info."""
    if not xml_path.exists():
        return {}

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        result = {
            'pdb_id': root.get('pdb_id', ''),
            'chain_id': root.get('chain_id', ''),
            'domains': {}
        }

        domains_elem = root.find('domains')
        if domains_elem is None:
            return result

        for i, domain_elem in enumerate(domains_elem.findall('domain'), 1):
            result['domains'][i] = {
                'family': domain_elem.get('family'),  # Actually T-group
                't_group': domain_elem.get('t_group'),
                'h_group': domain_elem.get('h_group'),
                'x_group': domain_elem.get('x_group'),
                'reference_ecod_domain_id': domain_elem.get('reference_ecod_domain_id'),
            }

        return result

    except Exception as e:
        logger.error(f"Failed to parse {xml_path}: {e}")
        return {}


def get_tgroup_corrections_from_partitions(
    bad_domains: List[Dict],
    partition_dirs: List[Path]
) -> Dict[str, Dict]:
    """
    Get T-group corrections from good partition files.

    For each bad domain, read the partition file and extract T-group hierarchy.
    The "family" attribute in partition files is actually the T-group ID.

    Args:
        bad_domains: List of domain dicts needing T-group corrections
        partition_dirs: List of partition directories to search (in order of preference)
    """
    corrections = {}

    # Group domains by PDB_chain
    pdb_chains = {}
    for domain in bad_domains:
        domain_id = domain['domain_id']
        match = re.match(r'e([0-9a-z]{4})([A-Za-z0-9]+?)(\d+)$', domain_id)
        if match:
            pdb_id = match.group(1)
            chain_id = match.group(2)
            domain_num = int(match.group(3))
            key = f"{pdb_id}_{chain_id}"
            if key not in pdb_chains:
                pdb_chains[key] = []
            pdb_chains[key].append((domain_id, domain_num, domain))

    # Parse partition files to get T-group info
    for pdb_chain, domains_list in pdb_chains.items():
        pdb_id, chain_id = pdb_chain.split('_', 1)

        patterns = [
            f"{pdb_id}_{chain_id}.partition.xml",
            f"{pdb_id.lower()}_{chain_id}.partition.xml",
        ]

        partition_data = None
        # Try each partition directory
        for partition_dir in partition_dirs:
            if not partition_dir.exists():
                continue
            for pattern in patterns:
                xml_path = partition_dir / pattern
                if xml_path.exists():
                    partition_data = parse_partition_xml(xml_path)
                    if partition_data and partition_data.get('domains'):
                        break
            if partition_data and partition_data.get('domains'):
                break

        if not partition_data or not partition_data.get('domains'):
            continue

        # For each domain, extract T-group hierarchy
        for domain_id, domain_num, domain_info in domains_list:
            if domain_num not in partition_data['domains']:
                continue

            domain_data = partition_data['domains'][domain_num]

            # The "family" field actually contains T-group (X.H.T format)
            t_group = domain_data.get('family', '') or domain_data.get('t_group', '')
            h_group = domain_data.get('h_group', '')
            x_group = domain_data.get('x_group', '')

            # Validate it's a valid T-group (3-part format: X.H.T)
            if t_group and re.match(r'^\d+\.\d+\.\d+$', t_group):
                corrections[domain_id] = {
                    'db_id': domain_info['db_id'],
                    'domain_id': domain_id,
                    'old_f_group': domain_info['f_group_id'],
                    't_group': t_group,
                    'h_group': h_group,
                    'x_group': x_group,
                    'reference': domain_data.get('reference_ecod_domain_id', ''),
                }
                logger.debug(f"Found T-group for {domain_id}: {t_group}")

    return corrections


def get_tgroup_from_reference_domain(conn, bad_domains: List[Dict]) -> Dict[str, Dict]:
    """
    Get T-group corrections by looking up reference domain in database.

    Uses the representative_domain_ecod_uid to find the reference domain
    and get its T-group assignment.
    """
    corrections = {}
    cursor = conn.cursor()

    for domain in bad_domains:
        domain_id = domain['domain_id']
        rep_uid = domain.get('rep_uid')

        if not rep_uid:
            continue

        # Look up reference domain's T-group
        cursor.execute("""
            SELECT fa.t_group_id, fa.h_group_id, fa.x_group_id, d.domain_id
            FROM ecod_commons.domains d
            JOIN ecod_commons.f_group_assignments fa ON d.id = fa.domain_id
            WHERE d.ecod_uid = %s
            LIMIT 1
        """, (rep_uid,))

        row = cursor.fetchone()
        if row and row[0] and re.match(r'^\d+\.\d+\.\d+$', row[0]):
            corrections[domain_id] = {
                'db_id': domain['db_id'],
                'domain_id': domain_id,
                'old_f_group': domain['f_group_id'],
                't_group': row[0],
                'h_group': row[1],
                'x_group': row[2],
                'reference': row[3],
            }
            logger.debug(f"Found T-group for {domain_id} from ref {row[3]}: {row[0]}")

    cursor.close()
    return corrections


def make_tgroup_only_fid(t_group: str) -> str:
    """
    Create a T-group-only F-group ID by appending .0 suffix.

    For domains without a Pfam-assigned F-group, we use T-group.0
    e.g., T-group "376.1.1" -> F-group "376.1.1.0"
    """
    return f"{t_group}.0"


def apply_fixes(
    conn,
    tgroup_domains: List[Dict],
    uniprot_domains: List[Dict],
    pdb_domains: List[Dict],
    uniprot_corrections: Dict[str, Dict],
    pdb_corrections: Dict[str, Dict],
    dry_run: bool = True
) -> Dict[str, int]:
    """
    Apply fixes to the database.

    For domains without Pfam F-group assignment, use T-group.0 format.
    e.g., T-group "376.1.1" -> F-group "376.1.1.0"

    1. For T-group domains: Set f_group_id = t_group.0
    2. For UniProt/PDB domains: Fix T-group if possible, set f_group_id = t_group.0
    """
    cursor = conn.cursor()
    stats = {
        'set_tgroup_fid': 0,
        'fixed_tgroup': 0,
        'unfixable': 0,
        'failed': 0,
    }

    # Step 1: Set f_group_id = t_group.0 for domains that have T-group IDs stored
    logger.info(f"Setting f_group_id to T-group.0 for {len(tgroup_domains)} domains...")
    for domain in tgroup_domains:
        try:
            # The f_group_id currently contains the T-group, use it to make proper F-group
            t_group = domain['f_group_id']  # Currently storing T-group incorrectly
            f_group = make_tgroup_only_fid(t_group)

            if dry_run:
                logger.debug(f"[DRY RUN] Would set {domain['domain_id']}: f_group={f_group}, t_group={t_group}")
            else:
                cursor.execute("""
                    UPDATE ecod_commons.f_group_assignments
                    SET f_group_id = %s,
                        t_group_id = %s
                    WHERE domain_id = %s
                """, (f_group, t_group, domain['db_id']))
            stats['set_tgroup_fid'] += 1
        except Exception as e:
            logger.error(f"Failed to fix {domain['domain_id']}: {e}")
            stats['failed'] += 1

    # Step 2: Fix UniProt domains
    logger.info(f"Fixing {len(uniprot_domains)} domains with UniProt accessions...")
    for domain in uniprot_domains:
        domain_id = domain['domain_id']
        try:
            if domain_id in uniprot_corrections:
                correction = uniprot_corrections[domain_id]
                t_group = correction['t_group']
                f_group = make_tgroup_only_fid(t_group)

                if dry_run:
                    logger.debug(
                        f"[DRY RUN] Would fix {domain_id}: "
                        f"f_group={f_group}, t_group={t_group}"
                    )
                else:
                    cursor.execute("""
                        UPDATE ecod_commons.f_group_assignments
                        SET f_group_id = %s,
                            t_group_id = %s,
                            h_group_id = %s,
                            x_group_id = %s
                        WHERE domain_id = %s
                    """, (
                        f_group,
                        t_group,
                        correction['h_group'],
                        correction['x_group'],
                        domain['db_id']
                    ))
                stats['fixed_tgroup'] += 1
            else:
                # Can't fix - no T-group available
                logger.warning(f"Cannot fix {domain_id}: no T-group correction available")
                stats['unfixable'] += 1
        except Exception as e:
            logger.error(f"Failed to fix {domain_id}: {e}")
            stats['failed'] += 1

    # Step 3: Fix PDB ID domains
    logger.info(f"Fixing {len(pdb_domains)} domains with PDB IDs...")
    for domain in pdb_domains:
        domain_id = domain['domain_id']
        try:
            if domain_id in pdb_corrections:
                correction = pdb_corrections[domain_id]
                t_group = correction['t_group']
                f_group = make_tgroup_only_fid(t_group)

                if dry_run:
                    logger.debug(
                        f"[DRY RUN] Would fix {domain_id}: "
                        f"f_group={f_group}, t_group={t_group}"
                    )
                else:
                    cursor.execute("""
                        UPDATE ecod_commons.f_group_assignments
                        SET f_group_id = %s,
                            t_group_id = %s,
                            h_group_id = %s,
                            x_group_id = %s
                        WHERE domain_id = %s
                    """, (
                        f_group,
                        t_group,
                        correction['h_group'],
                        correction['x_group'],
                        domain['db_id']
                    ))
                stats['fixed_tgroup'] += 1
            else:
                # Can't fix - no T-group available
                logger.warning(f"Cannot fix {domain_id}: no T-group correction available")
                stats['unfixable'] += 1
        except Exception as e:
            logger.error(f"Failed to fix {domain_id}: {e}")
            stats['failed'] += 1

    if not dry_run:
        conn.commit()

    cursor.close()
    return stats


def cleanup_bad_partition_files(
    bad_partition_dir: Path,
    archive_dir: Path,
    dry_run: bool = True
) -> Tuple[int, int]:
    """Archive bad partition files with UniProt family values."""
    import shutil

    # Find files with UniProt-like family values
    bad_files = []
    for xml_file in bad_partition_dir.glob('*.xml'):
        try:
            with open(xml_file, 'r') as f:
                content = f.read()
                if re.search(r'family="[A-Z][0-9A-Z]{4,9}"', content):
                    bad_files.append(xml_file)
        except Exception as e:
            logger.warning(f"Error reading {xml_file}: {e}")

    logger.info(f"Found {len(bad_files)} partition files with bad family values")

    if not bad_files:
        return 0, 0

    if not dry_run:
        archive_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    for xml_file in bad_files:
        if dry_run:
            moved += 1
        else:
            try:
                shutil.move(str(xml_file), str(archive_dir / xml_file.name))
                moved += 1
            except Exception as e:
                logger.error(f"Failed to archive {xml_file}: {e}")

    return moved, len(bad_files)


def main():
    parser = argparse.ArgumentParser(
        description="Fix F-group assignments for auto-accessioned domains"
    )
    parser.add_argument(
        "--batch-dir", type=Path, default=DEFAULT_BATCH_DIR,
        help=f"Batch directory (default: {DEFAULT_BATCH_DIR})"
    )
    parser.add_argument(
        "--good-partition-dir", type=str, default="partitions",
        help="Partition subdirectory with correct data"
    )
    parser.add_argument(
        "--bad-partition-dir", type=str, default="partitions_v293_fixed",
        help="Partition subdirectory with bad data (for archiving)"
    )
    parser.add_argument(
        "--cleanup-bad-files", action="store_true",
        help="Archive bad partition files"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview changes without applying"
    )

    args = parser.parse_args()

    good_partition_dir = args.batch_dir / args.good_partition_dir
    bad_partition_dir = args.batch_dir / args.bad_partition_dir

    logger.info("=" * 60)
    logger.info("Fix F-group Assignments")
    logger.info("=" * 60)
    logger.info(f"Batch directory: {args.batch_dir}")
    logger.info(f"Good partition directory: {good_partition_dir}")
    logger.info(f"Bad partition directory: {bad_partition_dir}")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'APPLY FIXES'}")
    logger.info("=" * 60)

    if not good_partition_dir.exists():
        logger.error(f"Good partition directory not found: {good_partition_dir}")
        return 1

    # Connect to database
    logger.info("\nConnecting to database...")
    conn = get_connection()

    # Categorize domains by f_group_id type
    logger.info("Categorizing domains by f_group_id type...")
    categories = categorize_fgroup_ids(conn)

    logger.info(f"\nDomain categories:")
    logger.info(f"  T-group ID (need to clear f_group): {len(categories['t_group'])}")
    logger.info(f"  UniProt accession (need to fix): {len(categories['uniprot'])}")
    logger.info(f"  PDB ID (need to fix): {len(categories['pdb'])}")
    logger.info(f"  Valid F-group ID: {len(categories['valid_fgroup'])}")

    # Get T-group corrections for UniProt/PDB domains from GOOD partition files
    uniprot_corrections = {}
    pdb_corrections = {}

    # List of partition directories to search (in order of preference)
    partition_dirs = [
        good_partition_dir,
        args.batch_dir / "partitions_v293",
        args.batch_dir / "partitions_v293_fixed",  # May have some valid data
    ]
    logger.info(f"\nPartition directories to search: {[str(p) for p in partition_dirs if p.exists()]}")

    if categories['uniprot'] or categories['pdb']:
        logger.info(f"\nLooking up T-group corrections from partition files...")

        if categories['uniprot']:
            uniprot_corrections = get_tgroup_corrections_from_partitions(
                categories['uniprot'], partition_dirs
            )
            logger.info(f"  From partitions: {len(uniprot_corrections)}/{len(categories['uniprot'])} UniProt domains")

            # Try reference domain lookup for remaining domains
            remaining = [d for d in categories['uniprot'] if d['domain_id'] not in uniprot_corrections]
            if remaining:
                ref_corrections = get_tgroup_from_reference_domain(conn, remaining)
                uniprot_corrections.update(ref_corrections)
                logger.info(f"  From reference domains: {len(ref_corrections)} more")
            logger.info(f"  Total: {len(uniprot_corrections)}/{len(categories['uniprot'])} UniProt domains")

        if categories['pdb']:
            pdb_corrections = get_tgroup_corrections_from_partitions(
                categories['pdb'], partition_dirs
            )
            logger.info(f"  From partitions: {len(pdb_corrections)}/{len(categories['pdb'])} PDB domains")

            # Try reference domain lookup for remaining domains
            remaining = [d for d in categories['pdb'] if d['domain_id'] not in pdb_corrections]
            if remaining:
                ref_corrections = get_tgroup_from_reference_domain(conn, remaining)
                pdb_corrections.update(ref_corrections)
                logger.info(f"  From reference domains: {len(ref_corrections)} more")
            logger.info(f"  Total: {len(pdb_corrections)}/{len(categories['pdb'])} PDB domains")

    # Apply fixes
    logger.info("\nApplying fixes...")
    stats = apply_fixes(
        conn,
        categories['t_group'],
        categories['uniprot'],
        categories['pdb'],
        uniprot_corrections,
        pdb_corrections,
        dry_run=args.dry_run
    )

    conn.close()

    # Cleanup bad partition files
    if args.cleanup_bad_files and bad_partition_dir.exists():
        logger.info("\nCleaning up bad partition files...")
        archive_dir = args.batch_dir / "partitions_v293_fixed_archived"
        moved, total_bad = cleanup_bad_partition_files(
            bad_partition_dir, archive_dir, dry_run=args.dry_run
        )
        logger.info(f"Archived {moved}/{total_bad} bad partition files")

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)
    logger.info(f"Domains processed:")
    logger.info(f"  T-group domains: {len(categories['t_group'])}")
    logger.info(f"  UniProt domains: {len(categories['uniprot'])}")
    logger.info(f"  PDB domains: {len(categories['pdb'])}")
    logger.info(f"\nFix results:")
    logger.info(f"  Set f_group_id to T-group.0: {stats['set_tgroup_fid']}")
    logger.info(f"  Fixed T-group + set f_group_id: {stats['fixed_tgroup']}")
    logger.info(f"  Unfixable (no T-group available): {stats['unfixable']}")
    logger.info(f"  Failed: {stats['failed']}")

    if args.dry_run:
        logger.info("")
        logger.info("This was a DRY RUN. Run without --dry-run to apply changes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
