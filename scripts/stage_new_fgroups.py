#!/usr/bin/env python3
"""
Stage new F-groups in ecod_rep.fgroup_staging for Track 2a domains.

These are domains with Pfam hits that don't map to existing ECOD F-groups.
Each unique Pfam family gets a new F-group staged with a provisional representative.

Usage:
    # Dry run
    python scripts/stage_new_fgroups.py --dry-run

    # Real staging
    python scripts/stage_new_fgroups.py
"""

import sys
import os
import argparse
import logging
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

import psycopg2

# Configure logging
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
BATCH_ID = "pyecod_prod_q4_2025_q1_2026"
SOURCE = "pyecod_prod"


def get_connection():
    """Get database connection."""
    return psycopg2.connect(**DEFAULT_CONNECTION_PARAMS)


def load_track2a_domains(tsv_path: Path) -> Dict[str, List[Dict]]:
    """
    Load Track 2a domains from the Pfam assignments TSV.

    Returns dict mapping pfam_acc -> list of domain info dicts
    """
    pfam_domains = defaultdict(list)

    with open(tsv_path, 'r') as f:
        header = f.readline().strip().split('\t')

        for line in f:
            fields = line.strip().split('\t')
            if len(fields) < len(header):
                continue

            row = dict(zip(header, fields))

            # Only Track 2a domains
            if row.get('track') != 'track2a':
                continue

            pfam_acc = row.get('pfam_acc', '')
            if not pfam_acc:
                continue

            pfam_domains[pfam_acc].append({
                'domain_id': row.get('domain_id'),
                'ecod_uid': int(row.get('ecod_uid', 0)) if row.get('ecod_uid') else 0,
                'pfam_name': row.get('pfam_name', ''),
                'score': float(row.get('score', 0)) if row.get('score') else 0,
                'evalue': float(row.get('evalue', 0)) if row.get('evalue') else 0,
            })

    return pfam_domains


def get_domain_hierarchy(conn, domain_ids: List[str]) -> Dict[str, Dict]:
    """
    Get hierarchy info (F-group, T-group, H-group) for domains.

    Returns dict mapping domain_id -> {f_group_id, t_group_id, h_group_id}
    Uses the t_group_id, h_group_id, x_group_id columns from f_group_assignments.
    If t_group_id is NULL, tries to parse from f_group_id (X.H.T.0 format).
    """
    cursor = conn.cursor()

    # Get hierarchy directly from f_group_assignments columns
    cursor.execute("""
        SELECT d.domain_id, fa.f_group_id, fa.t_group_id, fa.h_group_id, fa.x_group_id
        FROM ecod_commons.domains d
        JOIN ecod_commons.f_group_assignments fa ON d.id = fa.domain_id
        WHERE d.domain_id = ANY(%s)
    """, (domain_ids,))

    hierarchy = {}
    for domain_id, f_group_id, t_group_id, h_group_id, x_group_id in cursor:
        # If t_group_id is populated, use it
        if t_group_id:
            hierarchy[domain_id] = {
                'f_group_id': f_group_id,
                't_group_id': t_group_id,
                'h_group_id': h_group_id,
                'x_group_id': x_group_id,
            }
        # Otherwise, try to parse from f_group_id (X.H.T.0 format)
        elif f_group_id and re.match(r'^\d+\.\d+\.\d+\.\d+$', f_group_id):
            parts = f_group_id.split('.')
            t_group = '.'.join(parts[:3])  # X.H.T
            h_group = '.'.join(parts[:2])  # X.H
            x_group = parts[0]             # X
            hierarchy[domain_id] = {
                'f_group_id': f_group_id,
                't_group_id': t_group,
                'h_group_id': h_group,
                'x_group_id': x_group,
            }

    cursor.close()
    return hierarchy


def get_domain_ecod_uids(conn, domain_ids: List[str]) -> Dict[str, int]:
    """Get ecod_uid for domains."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT domain_id, ecod_uid
        FROM ecod_commons.domains
        WHERE domain_id = ANY(%s)
    """, (domain_ids,))

    uids = {}
    for domain_id, ecod_uid in cursor:
        uids[domain_id] = ecod_uid

    cursor.close()
    return uids


def select_best_representative(domains: List[Dict]) -> Dict:
    """
    Select best representative domain for a new F-group.

    Criteria: Highest Pfam bit score
    """
    return max(domains, key=lambda d: d.get('score', 0))


def determine_parent_groups(hierarchy_info: Dict[str, Dict], domains: List[Dict]) -> Tuple[str, str]:
    """
    Determine the T-group and H-group for a new F-group.

    Uses majority vote from the domains' current assignments.
    """
    t_group_counts = defaultdict(int)
    h_group_counts = defaultdict(int)

    for domain in domains:
        domain_id = domain['domain_id']
        if domain_id in hierarchy_info:
            t_group_counts[hierarchy_info[domain_id]['t_group_id']] += 1
            h_group_counts[hierarchy_info[domain_id]['h_group_id']] += 1

    if not t_group_counts:
        return None, None

    t_group = max(t_group_counts, key=t_group_counts.get)
    h_group = max(h_group_counts, key=h_group_counts.get)

    return t_group, h_group


def stage_fgroup(conn, pfam_acc: str, pfam_name: str,
                 parent_t_group: str, parent_h_group: str,
                 rep_domain_id: str, rep_ecod_uid: int,
                 domain_count: int, dry_run: bool = True) -> bool:
    """
    Stage a new F-group in ecod_rep.fgroup_staging.
    """
    cursor = conn.cursor()

    # Check if already staged
    cursor.execute("""
        SELECT id, status FROM ecod_rep.fgroup_staging
        WHERE pfam_combination = %s AND parent_t_group = %s
    """, (pfam_acc, parent_t_group))

    existing = cursor.fetchone()
    if existing:
        logger.warning(f"F-group for {pfam_acc} under {parent_t_group} already staged (id={existing[0]}, status={existing[1]})")
        cursor.close()
        return False

    if dry_run:
        logger.info(f"[DRY RUN] Would stage F-group: {pfam_acc} ({pfam_name}) under {parent_t_group}")
        logger.info(f"          Rep: {rep_domain_id} (uid={rep_ecod_uid}), {domain_count} domains")
        cursor.close()
        return True

    # Insert staging entry
    cursor.execute("""
        INSERT INTO ecod_rep.fgroup_staging (
            parent_t_group, parent_h_group, pfam_combination, name,
            domain_count, rep_domain_id, rep_ecod_uid,
            source, batch_id, status, created_by
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, 'pending', %s
        )
        RETURNING id
    """, (
        parent_t_group, parent_h_group, pfam_acc, pfam_name,
        domain_count, rep_domain_id, rep_ecod_uid,
        SOURCE, BATCH_ID, SOURCE
    ))

    staging_id = cursor.fetchone()[0]
    conn.commit()

    logger.info(f"Staged F-group {pfam_acc} ({pfam_name}) under {parent_t_group} - staging_id={staging_id}")
    cursor.close()
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Stage new F-groups for Track 2a Pfam families"
    )
    parser.add_argument(
        "--batch-dir", type=Path, default=DEFAULT_BATCH_DIR,
        help=f"Batch directory (default: {DEFAULT_BATCH_DIR})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview without staging"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Stage New F-groups for Track 2a Domains")
    logger.info("=" * 60)
    logger.info(f"Batch directory: {args.batch_dir}")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'REAL RUN'}")
    logger.info("=" * 60)

    # Load Track 2a domains
    tsv_path = args.batch_dir / "pfam" / "domain_pfam_assignments.tsv"
    if not tsv_path.exists():
        logger.error(f"Assignments file not found: {tsv_path}")
        return 1

    logger.info(f"Loading Track 2a domains from {tsv_path}...")
    pfam_domains = load_track2a_domains(tsv_path)

    logger.info(f"Found {len(pfam_domains)} unique Pfam families needing new F-groups")
    logger.info(f"Total Track 2a domains: {sum(len(v) for v in pfam_domains.values())}")

    # Get all domain IDs
    all_domain_ids = []
    for domains in pfam_domains.values():
        all_domain_ids.extend([d['domain_id'] for d in domains])

    # Connect to database
    logger.info("Connecting to database...")
    conn = get_connection()

    # Get hierarchy info for all domains
    logger.info("Fetching hierarchy information...")
    hierarchy_info = get_domain_hierarchy(conn, all_domain_ids)
    logger.info(f"Got hierarchy for {len(hierarchy_info)} domains")

    # Get ecod_uids
    ecod_uids = get_domain_ecod_uids(conn, all_domain_ids)

    # Stage each new F-group
    staged_count = 0
    skipped_count = 0
    failed_count = 0

    logger.info("")
    logger.info("Staging F-groups...")
    logger.info("-" * 60)

    for pfam_acc, domains in sorted(pfam_domains.items(), key=lambda x: -len(x[1])):
        # Get Pfam name from first domain
        pfam_name = domains[0].get('pfam_name', pfam_acc)

        # Determine parent T-group and H-group
        parent_t_group, parent_h_group = determine_parent_groups(hierarchy_info, domains)

        if not parent_t_group:
            logger.warning(f"Could not determine parent T-group for {pfam_acc} - skipping")
            failed_count += 1
            continue

        # Select best representative
        best_rep = select_best_representative(domains)
        rep_domain_id = best_rep['domain_id']
        rep_ecod_uid = ecod_uids.get(rep_domain_id, 0)

        # Stage the F-group
        success = stage_fgroup(
            conn=conn,
            pfam_acc=pfam_acc,
            pfam_name=pfam_name,
            parent_t_group=parent_t_group,
            parent_h_group=parent_h_group,
            rep_domain_id=rep_domain_id,
            rep_ecod_uid=rep_ecod_uid,
            domain_count=len(domains),
            dry_run=args.dry_run
        )

        if success:
            staged_count += 1
        else:
            skipped_count += 1

    conn.close()

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)
    logger.info(f"Staged: {staged_count}")
    logger.info(f"Skipped (already staged): {skipped_count}")
    logger.info(f"Failed: {failed_count}")

    if not args.dry_run and staged_count > 0:
        logger.info("")
        logger.info("Next steps:")
        logger.info("1. Review staged entries: SELECT * FROM ecod_rep.fgroup_staging WHERE batch_id = '%s'", BATCH_ID)
        logger.info("2. Approve entries: SELECT ecod_rep.approve_fgroup_staging(<id>)")
        logger.info("3. Or run pipeline: CALL ecod_rep.run_fgroup_staging_pipeline()")

    return 0


if __name__ == "__main__":
    sys.exit(main())
