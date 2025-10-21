#!/usr/bin/env python3
"""
Populate ECOD inclusion status from ecod_commons database.

This script queries ecod_commons to determine which chains already exist
in ECOD and populates the ecod_status, ecod_uid, and ecod_version columns
in pdb_update.chain_status.

Usage:
    # Test on specific release
    python scripts/populate_ecod_status.py --release-date 2025-09-05

    # Process all releases
    python scripts/populate_ecod_status.py --all

    # Dry run (report only)
    python scripts/populate_ecod_status.py --release-date 2025-09-05 --dry-run
"""

import sys
import argparse
import logging
from pathlib import Path
from typing import List, Tuple, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Error: psycopg2 not found. Install with: pip install psycopg2-binary")
    sys.exit(1)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_connection_params():
    """Get database connection parameters (default to dione)"""
    return {
        "host": "dione",
        "port": 45000,
        "database": "ecod_protein",
        "user": "ecod",
        "password": "ecod#badmin"
    }


def check_clustering_available(cursor, release_date: str) -> bool:
    """Check if clustering data exists for a release."""
    cursor.execute("""
        SELECT COUNT(*) as count FROM pdb_update.clustering_run
        WHERE release_date = %s
    """, (release_date,))
    result = cursor.fetchone()
    return result['count'] > 0 if result else False


def propagate_ecod_status_to_cluster(cursor, release_date: str) -> int:
    """
    Propagate ECOD status from representatives to cluster members.

    Returns count of members updated.
    """
    sql = """
    UPDATE pdb_update.chain_status member
    SET
        ecod_status = rep.ecod_status,
        ecod_uid = rep.ecod_uid,
        ecod_version = rep.ecod_version
    FROM pdb_update.chain_status rep
    WHERE member.representative_pdb_id = rep.pdb_id
      AND member.representative_chain_id = rep.chain_id
      AND member.release_date = rep.release_date
      AND member.release_date = %s
      AND member.is_representative = FALSE
      AND rep.is_representative = TRUE
      AND rep.ecod_status != 'not_in_ecod'
      AND member.ecod_status = 'not_in_ecod'
    RETURNING member.pdb_id, member.chain_id
    """

    cursor.execute(sql, (release_date,))
    results = cursor.fetchall()
    return len(results)


def populate_ecod_status(release_date: Optional[str] = None, dry_run: bool = False) -> Tuple[int, int, int]:
    """
    Query ecod_commons to populate ECOD inclusion status.

    Uses clustering-aware strategy:
    - If clustering data exists: Process representatives first, then propagate to members
    - If no clustering: Process all chains

    Args:
        release_date: Optional specific release (YYYY-MM-DD)
                     If None, processes all releases
        dry_run: If True, report without updating

    Returns:
        Tuple of (total_updated, in_current_ecod, in_previous_ecod)
    """
    conn_params = get_connection_params()
    conn = psycopg2.connect(**conn_params)
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Check if clustering is available for this release
        use_clustering = False
        if release_date:
            use_clustering = check_clustering_available(cursor, release_date)
            if use_clustering:
                logger.info(f"Clustering data found for {release_date} - using clustering-aware strategy")
            else:
                logger.info(f"No clustering data for {release_date} - processing all chains")
        if dry_run:
            # Query without UPDATE
            # Add clustering filter if available
            clustering_filter = ""
            if use_clustering:
                clustering_filter = "AND (cs.is_representative = TRUE OR cs.is_representative IS NULL)"

            sql = f"""
            SELECT
                cs.pdb_id,
                cs.chain_id,
                cs.release_date,
                cs.ecod_status as current_status,
                cs.is_representative,
                CASE
                    WHEN d.classification_status = 'classified' THEN 'in_current_ecod'
                    ELSE cs.ecod_status
                END as new_status,
                d.ecod_uid,
                v.version_name
            FROM pdb_update.chain_status cs
            LEFT JOIN ecod_commons.pdb_chain_mappings pcm
                ON cs.pdb_id = pcm.pdb_id AND cs.chain_id = pcm.auth_chain_id
            LEFT JOIN ecod_commons.domains d ON pcm.id = d.protein_id
            LEFT JOIN ecod_commons.versions v ON d.version_id = v.id
            WHERE (cs.release_date = %s OR %s IS NULL)
              AND cs.ecod_status = 'not_in_ecod'
              AND d.ecod_uid IS NOT NULL
              {clustering_filter}
            ORDER BY cs.pdb_id, cs.chain_id
            """

            cursor.execute(sql, (release_date, release_date))
            results = cursor.fetchall()

            # Report findings
            if results:
                in_current = sum(1 for r in results if r['new_status'] == 'in_current_ecod')

                if use_clustering:
                    reps = sum(1 for r in results if r.get('is_representative') == True)
                    logger.info(f"DRY RUN: Would update {len(results)} chains ({reps} representatives):")
                else:
                    logger.info(f"DRY RUN: Would update {len(results)} chains:")

                for i, row in enumerate(results[:10]):  # Show first 10
                    rep_marker = " [REP]" if row.get('is_representative') else ""
                    logger.info(f"  {row['pdb_id']}_{row['chain_id']}: {row['current_status']} -> {row['new_status']} (uid: {row['ecod_uid']}){rep_marker}")

                if len(results) > 10:
                    logger.info(f"  ... and {len(results) - 10} more")

                logger.info(f"\nSummary:")
                logger.info(f"  - Direct updates (reps): {in_current}")
                if use_clustering and in_current > 0:
                    # Estimate propagation
                    cursor.execute("""
                        SELECT COUNT(*) as count
                        FROM pdb_update.chain_status
                        WHERE release_date = %s
                          AND is_representative = FALSE
                          AND ecod_status = 'not_in_ecod'
                    """, (release_date,))
                    result = cursor.fetchone()
                    potential_propagation = result['count'] if result else 0
                    logger.info(f"  - Potential propagation to members: {potential_propagation}")
                logger.info(f"  - Would remain not_in_ecod: {len(results) - in_current}")

                return (len(results), in_current, 0)
            else:
                logger.info("DRY RUN: No chains would be updated")
                return (0, 0, 0)

        else:
            # Actual UPDATE query
            # Add clustering filter if available
            clustering_filter = ""
            if use_clustering:
                clustering_filter = "AND (cs.is_representative = TRUE OR cs.is_representative IS NULL)"

            sql = f"""
            UPDATE pdb_update.chain_status cs
            SET
                ecod_status = CASE
                    WHEN d.classification_status = 'classified' THEN 'in_current_ecod'
                    ELSE cs.ecod_status
                END,
                ecod_uid = d.ecod_uid,
                ecod_version = v.version_name
            FROM ecod_commons.pdb_chain_mappings pcm
            JOIN ecod_commons.domains d ON pcm.id = d.protein_id
            LEFT JOIN ecod_commons.versions v ON d.version_id = v.id
            WHERE cs.pdb_id = pcm.pdb_id
              AND cs.chain_id = pcm.auth_chain_id
              AND (cs.release_date = %s OR %s IS NULL)
              AND cs.ecod_status = 'not_in_ecod'
              AND d.classification_status = 'classified'
              {clustering_filter}
            RETURNING cs.pdb_id, cs.chain_id, cs.ecod_status, d.ecod_uid
            """

            cursor.execute(sql, (release_date, release_date))
            results = cursor.fetchall()
            conn.commit()

            # Log statistics
            total_updated = len(results)
            in_current = sum(1 for r in results if r['ecod_status'] == 'in_current_ecod')

            logger.info(f"Updated {total_updated} chains with ECOD status")
            logger.info(f"  - Representatives updated: {in_current}")

            # Propagate to cluster members if clustering is used
            propagated = 0
            if use_clustering and in_current > 0 and release_date:
                logger.info("Propagating ECOD status to cluster members...")
                propagated = propagate_ecod_status_to_cluster(cursor, release_date)
                conn.commit()
                logger.info(f"  - Cluster members propagated: {propagated}")

            # Final summary
            total_chains_updated = in_current + propagated
            logger.info(f"Total chains with ECOD status: {total_chains_updated}")
            if use_clustering:
                logger.info(f"  (Direct: {in_current}, Propagated: {propagated})")

            # Show sample
            if results:
                logger.info("Sample updated chains:")
                for i, row in enumerate(results[:5]):
                    logger.info(f"  {row['pdb_id']}_{row['chain_id']}: {row['ecod_status']} (uid: {row['ecod_uid']})")
                if len(results) > 5:
                    logger.info(f"  ... and {len(results) - 5} more")

            return (total_chains_updated, in_current, propagated)

    finally:
        cursor.close()
        conn.close()


def get_all_release_dates() -> List[str]:
    """Get all release dates from pdb_update.weekly_release"""
    conn_params = get_connection_params()
    conn = psycopg2.connect(**conn_params)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT release_date::text
            FROM pdb_update.weekly_release
            ORDER BY release_date
        """)
        return [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


def report_current_status(release_date: Optional[str] = None):
    """Report current ECOD status distribution"""
    conn_params = get_connection_params()
    conn = psycopg2.connect(**conn_params)
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        sql = """
        SELECT
            ecod_status,
            COUNT(*) as chains,
            COUNT(CASE WHEN can_classify THEN 1 END) as classifiable
        FROM pdb_update.chain_status
        WHERE release_date = %s OR %s IS NULL
        GROUP BY ecod_status
        ORDER BY chains DESC
        """

        cursor.execute(sql, (release_date, release_date))
        results = cursor.fetchall()

        if release_date:
            logger.info(f"\nCurrent ECOD status for {release_date}:")
        else:
            logger.info("\nCurrent ECOD status (all releases):")

        logger.info(f"{'Status':<20} {'Chains':>10} {'Classifiable':>15}")
        logger.info("-" * 50)
        for row in results:
            logger.info(f"{row['ecod_status']:<20} {row['chains']:>10} {row['classifiable']:>15}")

    finally:
        cursor.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Populate ECOD inclusion status from ecod_commons",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Test on specific release
    python scripts/populate_ecod_status.py --release-date 2025-09-05

    # Process all releases
    python scripts/populate_ecod_status.py --all

    # Dry run (report only)
    python scripts/populate_ecod_status.py --release-date 2025-09-05 --dry-run

    # Check current status
    python scripts/populate_ecod_status.py --status --release-date 2025-09-05
        """
    )

    parser.add_argument(
        '--release-date',
        help='Specific release date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Process all releases in database'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Report only, no database updates'
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Show current ECOD status distribution (no updates)'
    )

    args = parser.parse_args()

    if args.status:
        # Just show current status
        report_current_status(args.release_date)
        return 0

    if args.all:
        # Process all releases
        releases = get_all_release_dates()
        logger.info(f"Found {len(releases)} release(s) in database")

        total_chains = 0
        total_in_current = 0
        total_propagated = 0

        for release_date in releases:
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing {release_date}...")
            logger.info('='*60)

            updated, in_current, propagated = populate_ecod_status(
                release_date,
                dry_run=args.dry_run
            )

            total_chains += updated
            total_in_current += in_current
            total_propagated += propagated

        logger.info(f"\n{'='*60}")
        logger.info("SUMMARY")
        logger.info('='*60)
        logger.info(f"Total chains updated: {total_chains}")
        logger.info(f"  - Direct updates (reps): {total_in_current}")
        logger.info(f"  - Propagated to members: {total_propagated}")

    else:
        # Process specific release
        if not args.release_date:
            parser.error("--release-date required (or use --all)")

        populate_ecod_status(args.release_date, dry_run=args.dry_run)

        # Show final status
        if not args.dry_run:
            report_current_status(args.release_date)

    return 0


if __name__ == "__main__":
    sys.exit(main())
