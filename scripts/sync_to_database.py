#!/usr/bin/env python3
"""
Sync batch manifests to PostgreSQL database.

This script syncs completed batch results to the database for:
- Central tracking and indexing
- Progress monitoring across batches
- Integration preparation for ECOD

Usage:
    # Sync specific batch
    python scripts/sync_to_database.py --batch /data/ecod/pdb_updates/batches/ecod_weekly_20250905

    # Sync all batches
    python scripts/sync_to_database.py --all --base-path /data/ecod/pdb_updates/batches

    # Sync and overwrite existing records
    python scripts/sync_to_database.py --all --overwrite

    # Check database status
    python scripts/sync_to_database.py --status
"""

import sys
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.database import DatabaseSync


def print_batch_summary(summary_list):
    """Print formatted batch summary"""
    if not summary_list:
        print("No batches found in database")
        return

    print(f"\n{'='*80}")
    print(f"{'Release Date':<12} {'Status':<15} {'Chains':<10} {'Complete':<10} {'%':<8}")
    print(f"{'='*80}")

    for batch in summary_list:
        release_date = batch.get("release_date", "")
        status = batch.get("status", "")
        classifiable = batch.get("classifiable_chains", 0)
        processed = batch.get("processed_structures", 0)
        percent = batch.get("percent_complete", 0) or 0

        print(f"{release_date!s:<12} {status:<15} {classifiable:<10} {processed:<10} {percent:<8.1f}%")

    print(f"{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Sync batch manifests to PostgreSQL database"
    )

    # Database connection
    parser.add_argument(
        "--host",
        default="localhost",
        help="Database host (default: localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5432,
        help="Database port (default: 5432)"
    )
    parser.add_argument(
        "--database",
        default="update_protein",
        help="Database name (default: update_protein)"
    )
    parser.add_argument(
        "--user",
        default="ecod",
        help="Database user (default: ecod)"
    )

    # Sync options (mutually exclusive)
    sync_group = parser.add_mutually_exclusive_group()
    sync_group.add_argument(
        "--batch",
        help="Sync specific batch directory"
    )
    sync_group.add_argument(
        "--all",
        action="store_true",
        help="Sync all batches from base path"
    )
    sync_group.add_argument(
        "--status",
        action="store_true",
        help="Show database status (no syncing)"
    )

    parser.add_argument(
        "--base-path",
        default="/data/ecod/pdb_updates/batches",
        help="Base path for batches (default: /data/ecod/pdb_updates/batches)"
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing database records (default: skip)"
    )

    args = parser.parse_args()

    # Database connection params
    conn_params = {
        "host": args.host,
        "port": args.port,
        "database": args.database,
        "user": args.user,
        "password": None  # Will use .pgpass or other auth
    }

    try:
        # Connect to database
        with DatabaseSync(conn_params) as db_sync:

            if args.status:
                # Show database status
                print("Fetching database status...")
                summary = db_sync.get_batch_summary()
                print_batch_summary(summary)

                # Show chains needing HHsearch
                hhsearch_chains = db_sync.get_chains_needing_hhsearch()
                print(f"Chains needing HHsearch: {len(hhsearch_chains)}")

                # Show failed chains
                failed_chains = db_sync.get_failed_chains()
                if failed_chains:
                    print(f"\nFailed chains: {len(failed_chains)}")
                    for chain in failed_chains[:10]:
                        print(f"  - {chain['pdb_id']}_{chain['chain_id']} ({chain['release_date']}): {chain['failure_reason']}")
                    if len(failed_chains) > 10:
                        print(f"  ... and {len(failed_chains) - 10} more")

            elif args.batch:
                # Sync specific batch
                print(f"Syncing batch: {args.batch}")
                db_sync.sync_weekly_batch(args.batch, overwrite=args.overwrite)
                print("✓ Sync complete")

            elif args.all:
                # Sync all batches
                print(f"Syncing all batches from: {args.base_path}")
                db_sync.sync_all_batches(args.base_path, overwrite=args.overwrite)
                print("\n✓ Sync complete")

                # Show updated summary
                print("\nDatabase summary:")
                summary = db_sync.get_batch_summary()
                print_batch_summary(summary)

            else:
                print("No action specified. Use --batch, --all, or --status")
                return 1

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
