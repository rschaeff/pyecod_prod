#!/usr/bin/env python3
"""
Backfill metadata for historical PDB releases.

This script populates weekly_release and chain_status tables with metadata
from historical PDB weekly releases. It scans all releases in the specified
date range and extracts chain information from mmCIF files.

Usage:
    # Backfill single week
    python scripts/backfill_metadata.py --release-date 2023-10-27

    # Backfill date range
    python scripts/backfill_metadata.py --start-date 2023-10-27 --end-date 2025-10-10

    # Resume from last completed release
    python scripts/backfill_metadata.py --start-date 2023-10-27 --end-date 2025-10-10 --resume

    # Dry run (report only)
    python scripts/backfill_metadata.py --start-date 2023-10-27 --end-date 2025-10-10 --dry-run
"""

import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Tuple, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Error: psycopg2 not found. Install with: pip install psycopg2-binary")
    sys.exit(1)

from pyecod_prod.parsers.pdb_status import PDBStatusParser

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


def find_weekly_releases(
    start_date: date,
    end_date: date,
    status_base_dir: str = "/usr2/pdb/data/status"
) -> List[Tuple[date, Path]]:
    """
    Find all PDB weekly releases in the date range.

    Args:
        start_date: Start of date range
        end_date: End of date range
        status_base_dir: Base directory for PDB status files

    Returns:
        List of (date, status_dir_path) tuples
    """
    status_base = Path(status_base_dir)

    logger.info(f"Scanning {status_base} for releases between {start_date} and {end_date}...")

    # Get all status directories
    all_dirs = sorted([d for d in status_base.iterdir() if d.is_dir() and d.name.isdigit() and len(d.name) == 8])

    # Filter to date range
    releases = []
    for d in all_dirs:
        try:
            dir_date = datetime.strptime(d.name, "%Y%m%d").date()
            if start_date <= dir_date <= end_date:
                added_file = d / "added.pdb"
                if added_file.exists():
                    releases.append((dir_date, d))
        except ValueError:
            continue

    logger.info(f"Found {len(releases)} releases in date range")
    return releases


def check_release_exists(cursor, release_date: date) -> bool:
    """Check if a release has already been loaded"""
    cursor.execute("""
        SELECT COUNT(*) as count FROM pdb_update.weekly_release
        WHERE release_date = %s
    """, (release_date,))
    result = cursor.fetchone()
    return result['count'] > 0 if result else False


def insert_weekly_release(cursor, release_date: date, pdb_count: int, chain_count: int, classifiable_count: int):
    """Insert a weekly_release record"""
    # Generate batch info
    date_str = release_date.strftime("%Y%m%d")
    batch_name = f"ecod_weekly_{release_date.strftime('%Y%m%d')}"
    batch_path = f"/data/ecod/pdb_updates/batches/{batch_name}"
    pdb_status_path = f"/usr2/pdb/data/status/{date_str}"

    cursor.execute("""
        INSERT INTO pdb_update.weekly_release (
            release_date,
            pdb_status_path,
            batch_name,
            batch_path,
            total_structures,
            classifiable_chains,
            created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (release_date) DO UPDATE
        SET total_structures = EXCLUDED.total_structures,
            classifiable_chains = EXCLUDED.classifiable_chains
    """, (release_date, pdb_status_path, batch_name, batch_path, pdb_count, classifiable_count))


def insert_chain_status(cursor, release_date: date, chain_info, ecod_status: str = 'not_in_ecod'):
    """Insert a chain_status record"""
    cursor.execute("""
        INSERT INTO pdb_update.chain_status (
            pdb_id,
            chain_id,
            release_date,
            sequence_length,
            can_classify,
            cannot_classify_reason,
            ecod_status,
            updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, now()
        )
        ON CONFLICT (pdb_id, chain_id, release_date) DO UPDATE
        SET sequence_length = EXCLUDED.sequence_length,
            can_classify = EXCLUDED.can_classify,
            cannot_classify_reason = EXCLUDED.cannot_classify_reason
    """, (
        chain_info.pdb_id,
        chain_info.chain_id,
        release_date,
        chain_info.sequence_length,
        chain_info.can_classify,
        chain_info.cannot_classify_reason,
        ecod_status
    ))


def process_single_release(
    release_date: date,
    status_dir: Path,
    parser: PDBStatusParser,
    conn,
    dry_run: bool = False
) -> dict:
    """
    Process a single weekly release.

    Returns:
        Dict with statistics
    """
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Parse the release
        logger.info(f"Processing {release_date} ({status_dir})...")
        result = parser.process_weekly_release(str(status_dir))

        stats = {
            'release_date': release_date,
            'pdb_entries': len(result['pdb_ids']),
            'total_chains': len(result['chains']),
            'classifiable': len(result['classifiable']),
            'peptides': len(result['peptides']),
            'other': len(result['other']),
            'failed': len(result['failed'])
        }

        if dry_run:
            logger.info(f"DRY RUN - Would load:")
            logger.info(f"  PDB entries: {stats['pdb_entries']}")
            logger.info(f"  Total chains: {stats['total_chains']}")
            logger.info(f"  Classifiable: {stats['classifiable']}")
            logger.info(f"  Peptides: {stats['peptides']}")
            return stats

        # Insert weekly_release record
        insert_weekly_release(
            cursor,
            release_date,
            stats['pdb_entries'],
            stats['total_chains'],
            stats['classifiable']
        )

        # Insert all chains
        chains_inserted = 0
        for i, chain in enumerate(result['chains']):
            try:
                insert_chain_status(cursor, release_date, chain)
                chains_inserted += 1
            except Exception as e:
                if i == 0:  # Log first error in detail
                    logger.error(f"FIRST INSERT ERROR for {chain.pdb_id}_{chain.chain_id}: {e}")
                    logger.error(f"  Sequence length: {chain.sequence_length}")
                    logger.error(f"  Can classify: {chain.can_classify}")
                    raise  # Re-raise to see full traceback
                else:
                    logger.warning(f"Failed to insert {chain.pdb_id}_{chain.chain_id}: {e}")

        conn.commit()

        logger.info(f"✓ Loaded {release_date}:")
        logger.info(f"    PDB entries: {stats['pdb_entries']}")
        logger.info(f"    Chains: {chains_inserted}/{stats['total_chains']}")
        logger.info(f"    Classifiable: {stats['classifiable']}")

        stats['chains_inserted'] = chains_inserted
        return stats

    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to process {release_date}: {e}")
        raise
    finally:
        cursor.close()


def backfill_metadata(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    release_date: Optional[date] = None,
    resume: bool = False,
    dry_run: bool = False
) -> dict:
    """
    Backfill metadata for historical releases.

    Args:
        start_date: Start of date range (inclusive)
        end_date: End of date range (inclusive)
        release_date: Single release date (alternative to range)
        resume: Skip releases already in database
        dry_run: Report only, no database writes

    Returns:
        Dict with overall statistics
    """
    # Initialize parser
    logger.info("Initializing PDB status parser...")
    parser = PDBStatusParser()

    # Connect to database
    conn_params = get_connection_params()
    conn = psycopg2.connect(**conn_params)
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Determine releases to process
        if release_date:
            # Single release
            status_dir = Path(f"/usr2/pdb/data/status/{release_date.strftime('%Y%m%d')}")
            if not status_dir.exists():
                raise FileNotFoundError(f"Status directory not found: {status_dir}")
            releases = [(release_date, status_dir)]
        else:
            # Date range
            if not start_date or not end_date:
                raise ValueError("Must provide either --release-date or --start-date/--end-date")
            releases = find_weekly_releases(start_date, end_date)

        if not releases:
            logger.warning("No releases found in specified range")
            return {'releases_processed': 0}

        logger.info(f"Processing {len(releases)} releases...")

        # Track overall statistics
        total_stats = {
            'releases_found': len(releases),
            'releases_processed': 0,
            'releases_skipped': 0,
            'releases_failed': 0,
            'total_pdb_entries': 0,
            'total_chains': 0,
            'total_classifiable': 0,
            'total_peptides': 0
        }

        # Process each release
        for i, (rel_date, status_dir) in enumerate(releases, 1):
            logger.info(f"\n{'='*70}")
            logger.info(f"Release {i}/{len(releases)}: {rel_date}")
            logger.info('='*70)

            # Check if already loaded
            if resume and check_release_exists(cursor, rel_date):
                logger.info(f"Skipping {rel_date} (already loaded)")
                total_stats['releases_skipped'] += 1
                continue

            # Process the release
            try:
                stats = process_single_release(
                    rel_date,
                    status_dir,
                    parser,
                    conn,
                    dry_run=dry_run
                )

                total_stats['releases_processed'] += 1
                total_stats['total_pdb_entries'] += stats['pdb_entries']
                total_stats['total_chains'] += stats['total_chains']
                total_stats['total_classifiable'] += stats['classifiable']
                total_stats['total_peptides'] += stats['peptides']

            except Exception as e:
                logger.error(f"Failed to process {rel_date}: {e}")
                total_stats['releases_failed'] += 1
                continue

        # Summary
        logger.info(f"\n{'='*70}")
        logger.info("BACKFILL SUMMARY")
        logger.info('='*70)
        logger.info(f"Releases found: {total_stats['releases_found']}")
        logger.info(f"Releases processed: {total_stats['releases_processed']}")
        logger.info(f"Releases skipped (resume): {total_stats['releases_skipped']}")
        logger.info(f"Releases failed: {total_stats['releases_failed']}")
        logger.info(f"Total PDB entries: {total_stats['total_pdb_entries']:,}")
        logger.info(f"Total chains: {total_stats['total_chains']:,}")
        logger.info(f"  Classifiable: {total_stats['total_classifiable']:,}")
        logger.info(f"  Peptides: {total_stats['total_peptides']:,}")

        return total_stats

    finally:
        cursor.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Backfill metadata for historical PDB releases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Backfill single week
    python scripts/backfill_metadata.py --release-date 2023-10-27

    # Backfill date range
    python scripts/backfill_metadata.py --start-date 2023-10-27 --end-date 2025-10-10

    # Resume from last completed (skip already loaded)
    python scripts/backfill_metadata.py --start-date 2023-10-27 --end-date 2025-10-10 --resume

    # Dry run
    python scripts/backfill_metadata.py --start-date 2023-10-27 --end-date 2023-12-31 --dry-run
        """
    )

    parser.add_argument(
        '--release-date',
        type=str,
        help='Single release date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        help='Start date for range (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        help='End date for range (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Skip releases already in database'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Report only, no database updates'
    )

    args = parser.parse_args()

    # Parse dates
    release_date = None
    start_date = None
    end_date = None

    if args.release_date:
        release_date = datetime.strptime(args.release_date, "%Y-%m-%d").date()

    if args.start_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()

    if args.end_date:
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()

    # Validate arguments
    if not release_date and not (start_date and end_date):
        parser.error("Must provide either --release-date or --start-date/--end-date")

    if release_date and (start_date or end_date):
        parser.error("Cannot use --release-date with --start-date/--end-date")

    # Run backfill
    try:
        backfill_metadata(
            start_date=start_date,
            end_date=end_date,
            release_date=release_date,
            resume=args.resume,
            dry_run=args.dry_run
        )
        return 0
    except Exception as e:
        logger.error(f"Backfill failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
