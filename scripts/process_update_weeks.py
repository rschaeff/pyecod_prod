#!/usr/bin/env python3
"""
Process all PDB weekly updates from a start date to present (catch-up processing).

This script:
1. Identifies all PDB weekly releases from start_date to latest
2. Creates and processes a batch for each week sequentially
3. Tracks progress to enable resuming from failures
4. Optionally syncs results to database

Usage:
    python scripts/process_update_weeks.py --start-date 2025-09-05 --submit
    python scripts/process_update_weeks.py --start-date 2025-09-05 --dry-run
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta
import time

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.batch.weekly_batch import WeeklyBatch
from pyecod_prod.batch.manifest import BatchManifest


def get_pdb_release_dates(start_date, end_date=None, pdb_status_base="/usr2/pdb/data/status"):
    """
    Get list of PDB weekly release dates between start_date and end_date.

    Args:
        start_date: Start date (YYYY-MM-DD or datetime)
        end_date: End date (YYYY-MM-DD or datetime), defaults to latest
        pdb_status_base: Base path to PDB status directories

    Returns:
        List of (date_str, status_dir_path) tuples
    """
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d")

    if end_date is None:
        # Use latest symlink
        latest_link = Path(pdb_status_base) / "latest"
        if latest_link.exists():
            latest_dir = latest_link.resolve().name
            end_date = datetime.strptime(latest_dir, "%Y%m%d")
        else:
            end_date = datetime.now()
    elif isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d")

    # Find all existing status directories
    status_base = Path(pdb_status_base)
    releases = []

    for status_dir in sorted(status_base.iterdir()):
        if not status_dir.is_dir():
            continue
        if status_dir.name == "latest" or not status_dir.name.isdigit():
            continue

        try:
            dir_date = datetime.strptime(status_dir.name, "%Y%m%d")
        except ValueError:
            continue

        # Check if date is in range
        if start_date <= dir_date <= end_date:
            # Check if added.pdb exists and is non-empty
            added_pdb = status_dir / "added.pdb"
            if added_pdb.exists() and added_pdb.stat().st_size > 0:
                date_str = dir_date.strftime("%Y-%m-%d")
                releases.append((date_str, str(status_dir)))

    return releases


def process_weekly_batch(release_date, status_dir, base_path, reference_version="develop291",
                        submit_jobs=False, dry_run=False):
    """
    Process a single weekly batch.

    Returns:
        (success, batch_path, message)
    """
    try:
        print(f"\n{'='*70}")
        print(f"Processing weekly release: {release_date}")
        print(f"Status directory: {status_dir}")
        print(f"{'='*70}\n")

        if dry_run:
            print(f"[DRY RUN] Would process {release_date}")
            return (True, None, "Dry run - no processing")

        # Create batch
        batch = WeeklyBatch(
            release_date=release_date,
            pdb_status_dir=status_dir,
            base_path=base_path,
            reference_version=reference_version
        )

        # Check if batch already exists and is complete
        if Path(batch.batch_path).exists():
            manifest = BatchManifest(batch.batch_path)
            if manifest.is_complete():
                print(f"✓ Batch already complete: {batch.batch_path}")
                return (True, batch.batch_path, "Already complete")
            else:
                print(f"⚠ Resuming incomplete batch: {batch.batch_path}")

        # Run complete workflow
        print("\nRunning complete workflow...")
        batch.run_complete_workflow(
            submit_blast=submit_jobs,
            submit_hhsearch=submit_jobs
        )

        # Print summary
        print(f"\n{'='*70}")
        print("Batch Summary")
        print(f"{'='*70}")
        batch.manifest.print_summary()

        return (True, batch.batch_path, "Complete")

    except Exception as e:
        import traceback
        error_msg = f"Failed to process {release_date}: {e}"
        print(f"\n✗ {error_msg}")
        traceback.print_exc()
        return (False, None, str(e))


def main():
    parser = argparse.ArgumentParser(
        description="Process all PDB weekly updates from start date to present"
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="Start date for processing (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end-date",
        help="End date for processing (YYYY-MM-DD), defaults to latest"
    )
    parser.add_argument(
        "--base-path",
        default="/data/ecod/pdb_updates/batches",
        help="Base path for batch output (default: /data/ecod/pdb_updates/batches)"
    )
    parser.add_argument(
        "--reference-version",
        default="develop291",
        help="ECOD reference version (default: develop291)"
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Submit BLAST/HHsearch jobs to SLURM (default: False)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without running"
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        help="Maximum number of batches to process (for testing)"
    )

    args = parser.parse_args()

    # Get list of releases to process
    print("Finding PDB weekly releases...")
    releases = get_pdb_release_dates(
        args.start_date,
        args.end_date
    )

    if not releases:
        print(f"No releases found between {args.start_date} and {args.end_date or 'latest'}")
        return 1

    print(f"\nFound {len(releases)} weekly releases to process:")
    for date_str, status_dir in releases[:10]:  # Show first 10
        print(f"  - {date_str} ({status_dir})")
    if len(releases) > 10:
        print(f"  ... and {len(releases) - 10} more")

    if args.max_batches:
        releases = releases[:args.max_batches]
        print(f"\nLimiting to first {args.max_batches} batches")

    if args.dry_run:
        print("\n[DRY RUN] No processing will occur")
        return 0

    # Confirm before processing
    if not args.dry_run and len(releases) > 1:
        response = input(f"\nProcess {len(releases)} weekly releases? [y/N]: ")
        if response.lower() != 'y':
            print("Cancelled")
            return 0

    # Process each release sequentially
    results = []
    start_time = datetime.now()

    for i, (date_str, status_dir) in enumerate(releases, 1):
        print(f"\n{'#'*70}")
        print(f"Batch {i}/{len(releases)}")
        print(f"{'#'*70}")

        success, batch_path, message = process_weekly_batch(
            release_date=date_str,
            status_dir=status_dir,
            base_path=args.base_path,
            reference_version=args.reference_version,
            submit_jobs=args.submit,
            dry_run=args.dry_run
        )

        results.append({
            "date": date_str,
            "success": success,
            "batch_path": batch_path,
            "message": message
        })

        if not success:
            print(f"\n⚠ Warning: Batch {date_str} failed, continuing...")

    # Print final summary
    end_time = datetime.now()
    duration = end_time - start_time

    print(f"\n{'='*70}")
    print("FINAL SUMMARY")
    print(f"{'='*70}")
    print(f"Total batches: {len(results)}")
    print(f"Successful: {sum(1 for r in results if r['success'])}")
    print(f"Failed: {sum(1 for r in results if not r['success'])}")
    print(f"Total time: {duration}")
    print()

    # Show failed batches
    failed = [r for r in results if not r["success"]]
    if failed:
        print("Failed batches:")
        for r in failed:
            print(f"  - {r['date']}: {r['message']}")
        print()

    return 0 if all(r["success"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
