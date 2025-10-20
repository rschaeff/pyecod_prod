#!/usr/bin/env python3
"""
Process a repair batch for reprocessing specific chains or weeks.

Repair batches are used for:
- Reprocessing chains that failed in previous runs
- Updating chains due to PDB modifications/obsoletes
- Reclassifying chains after ECOD hierarchy changes
- Reprocessing with updated algorithms (e.g., new pyecod-mini version)

Usage:
    # Reprocess specific weeks
    python scripts/process_repair_batch.py --weeks 2025-09-05,2025-09-12 --reason "pdb_modifications"

    # Reprocess specific chains from file
    python scripts/process_repair_batch.py --chains-file failed_chains.txt --reason "algorithm_update"

    # Reprocess chains matching criteria
    python scripts/process_repair_batch.py --low-quality --reason "repartition_low_quality"
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.batch.weekly_batch import WeeklyBatch
from pyecod_prod.batch.manifest import BatchManifest


class RepairBatch:
    """Manage repair/reprocessing batches"""

    def __init__(self, batch_name, base_path="/data/ecod/pdb_updates/batches",
                 reference_version="develop291"):
        self.batch_name = batch_name
        self.base_path = Path(base_path)
        self.batch_path = self.base_path / batch_name
        self.reference_version = reference_version

    def create_from_weeks(self, week_dates: List[str], rerun_blast=False,
                         rerun_hhsearch=False, rerun_partition=True):
        """
        Create repair batch from specific weekly releases.

        Args:
            week_dates: List of release dates (YYYY-MM-DD)
            rerun_blast: Whether to rerun BLAST
            rerun_hhsearch: Whether to rerun HHsearch
            rerun_partition: Whether to rerun partitioning (default True)
        """
        print(f"Creating repair batch: {self.batch_name}")
        print(f"Source weeks: {', '.join(week_dates)}")
        print()

        # Create batch directory
        self.batch_path.mkdir(parents=True, exist_ok=True)

        # Initialize manifest
        manifest_data = {
            "batch_name": self.batch_name,
            "batch_type": "repair",
            "created": datetime.now().isoformat(),
            "reference_version": self.reference_version,
            "source_weeks": week_dates,
            "rerun_blast": rerun_blast,
            "rerun_hhsearch": rerun_hhsearch,
            "rerun_partition": rerun_partition,
            "chains": {},
            "processing_status": {
                "total_structures": 0,
                "blast_complete": 0,
                "hhsearch_complete": 0,
                "partition_complete": 0
            }
        }

        # Collect chains from source weeks
        for week_date in week_dates:
            week_batch_name = f"ecod_weekly_{week_date.replace('-', '')}"
            week_batch_path = self.batch_path / week_batch_name

            if not week_batch_path.exists():
                print(f"⚠ Warning: Week {week_date} batch not found: {week_batch_path}")
                continue

            # Load source manifest
            source_manifest = BatchManifest(str(week_batch_path))
            print(f"Loading chains from {week_date}: {len(source_manifest.data['chains'])} chains")

            # Copy chains to repair batch
            for chain_key, chain_data in source_manifest.data["chains"].items():
                if chain_data.get("can_classify", True):
                    manifest_data["chains"][chain_key] = {
                        **chain_data,
                        "source_week": week_date,
                        "repair_status": "pending"
                    }
                    manifest_data["processing_status"]["total_structures"] += 1

        # Save manifest
        manifest_path = self.batch_path / "batch_manifest.yaml"
        import yaml
        with open(manifest_path, 'w') as f:
            yaml.dump(manifest_data, f, default_flow_style=False, sort_keys=False)

        print(f"\n✓ Repair batch created with {manifest_data['processing_status']['total_structures']} chains")
        print(f"Batch path: {self.batch_path}")

        return str(self.batch_path)

    def create_from_chain_list(self, chain_list: List[Tuple[str, str, str]],
                               rerun_blast=False, rerun_hhsearch=False,
                               rerun_partition=True):
        """
        Create repair batch from explicit chain list.

        Args:
            chain_list: List of (pdb_id, chain_id, source_week) tuples
            rerun_blast: Whether to rerun BLAST
            rerun_hhsearch: Whether to rerun HHsearch
            rerun_partition: Whether to rerun partitioning
        """
        print(f"Creating repair batch: {self.batch_name}")
        print(f"Total chains: {len(chain_list)}")
        print()

        # Create batch directory
        self.batch_path.mkdir(parents=True, exist_ok=True)

        # Initialize manifest
        manifest_data = {
            "batch_name": self.batch_name,
            "batch_type": "repair",
            "created": datetime.now().isoformat(),
            "reference_version": self.reference_version,
            "rerun_blast": rerun_blast,
            "rerun_hhsearch": rerun_hhsearch,
            "rerun_partition": rerun_partition,
            "chains": {},
            "processing_status": {
                "total_structures": len(chain_list),
                "blast_complete": 0,
                "hhsearch_complete": 0,
                "partition_complete": 0
            }
        }

        # Add chains
        for pdb_id, chain_id, source_week in chain_list:
            chain_key = f"{pdb_id}_{chain_id}"

            # Try to load chain data from source week
            week_batch_name = f"ecod_weekly_{source_week.replace('-', '')}"
            week_batch_path = self.base_path / week_batch_name

            chain_data = None
            if week_batch_path.exists():
                source_manifest = BatchManifest(str(week_batch_path))
                chain_data = source_manifest.data["chains"].get(chain_key)

            if chain_data:
                manifest_data["chains"][chain_key] = {
                    **chain_data,
                    "source_week": source_week,
                    "repair_status": "pending"
                }
            else:
                # Create minimal chain entry
                manifest_data["chains"][chain_key] = {
                    "pdb_id": pdb_id,
                    "chain_id": chain_id,
                    "source_week": source_week,
                    "can_classify": True,
                    "repair_status": "pending"
                }

        # Save manifest
        manifest_path = self.batch_path / "batch_manifest.yaml"
        import yaml
        with open(manifest_path, 'w') as f:
            yaml.dump(manifest_data, f, default_flow_style=False, sort_keys=False)

        print(f"✓ Repair batch created with {len(chain_list)} chains")
        print(f"Batch path: {self.batch_path}")

        return str(self.batch_path)


def read_chains_from_file(filepath: str) -> List[Tuple[str, str, str]]:
    """
    Read chain list from file.

    Format (one per line):
        pdb_id chain_id source_week
        8s72 A 2025-09-05
        8yl2 B 2025-09-05
    """
    chains = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            parts = line.split()
            if len(parts) >= 3:
                pdb_id, chain_id, source_week = parts[0], parts[1], parts[2]
                chains.append((pdb_id, chain_id, source_week))
            else:
                print(f"⚠ Warning: Invalid line format: {line}")

    return chains


def find_low_quality_chains(base_path: str, min_coverage=0.8) -> List[Tuple[str, str, str]]:
    """Find chains with low partition quality from all batches"""
    chains = []
    base = Path(base_path)

    for batch_dir in base.glob("ecod_weekly_*"):
        if not batch_dir.is_dir():
            continue

        manifest_path = batch_dir / "batch_manifest.yaml"
        if not manifest_path.exists():
            continue

        manifest = BatchManifest(str(batch_dir))
        week_date = manifest.data.get("release_date", "unknown")

        for chain_key, chain_data in manifest.data["chains"].items():
            partition_coverage = chain_data.get("partition_coverage", 1.0)
            partition_quality = chain_data.get("partition_quality", "unknown")

            if partition_coverage < min_coverage or partition_quality in ["low_coverage", "fragmentary"]:
                pdb_id = chain_data["pdb_id"]
                chain_id = chain_data["chain_id"]
                chains.append((pdb_id, chain_id, week_date))

    return chains


def main():
    parser = argparse.ArgumentParser(
        description="Create and process repair/reprocessing batch"
    )

    # Batch identification
    parser.add_argument(
        "--batch-name",
        help="Repair batch name (default: ecod_repair_YYYYMMDD)"
    )
    parser.add_argument(
        "--base-path",
        default="/data/ecod/pdb_updates/batches",
        help="Base path for batches"
    )

    # Source selection (mutually exclusive)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--weeks",
        help="Comma-separated list of weeks to reprocess (YYYY-MM-DD,YYYY-MM-DD)"
    )
    source_group.add_argument(
        "--chains-file",
        help="File containing chains to reprocess (format: pdb_id chain_id source_week)"
    )
    source_group.add_argument(
        "--low-quality",
        action="store_true",
        help="Find and reprocess all chains with low partition quality"
    )

    # Processing options
    parser.add_argument(
        "--rerun-blast",
        action="store_true",
        help="Rerun BLAST (default: False, use existing results)"
    )
    parser.add_argument(
        "--rerun-hhsearch",
        action="store_true",
        help="Rerun HHsearch (default: False, use existing results)"
    )
    parser.add_argument(
        "--rerun-partition",
        action="store_true",
        default=True,
        help="Rerun partitioning (default: True)"
    )

    # Metadata
    parser.add_argument(
        "--reason",
        required=True,
        choices=["pdb_modifications", "algorithm_update", "error_fix", "hierarchy_update", "user_request"],
        help="Reason for reprocessing"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without creating batch"
    )

    args = parser.parse_args()

    # Generate batch name
    if not args.batch_name:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.batch_name = f"ecod_repair_{timestamp}"

    print(f"{'='*70}")
    print(f"Repair Batch: {args.batch_name}")
    print(f"Reason: {args.reason}")
    print(f"{'='*70}\n")

    # Get chain list based on source
    if args.weeks:
        week_list = [w.strip() for w in args.weeks.split(',')]
        print(f"Source: {len(week_list)} weeks")

        if args.dry_run:
            print("\n[DRY RUN] Would create repair batch from weeks:")
            for week in week_list:
                print(f"  - {week}")
            return 0

        repair = RepairBatch(args.batch_name, args.base_path)
        batch_path = repair.create_from_weeks(
            week_list,
            rerun_blast=args.rerun_blast,
            rerun_hhsearch=args.rerun_hhsearch,
            rerun_partition=args.rerun_partition
        )

    elif args.chains_file:
        chains = read_chains_from_file(args.chains_file)
        print(f"Source: {len(chains)} chains from {args.chains_file}")

        if args.dry_run:
            print(f"\n[DRY RUN] Would create repair batch with {len(chains)} chains")
            for pdb_id, chain_id, week in chains[:10]:
                print(f"  - {pdb_id}_{chain_id} (from {week})")
            if len(chains) > 10:
                print(f"  ... and {len(chains) - 10} more")
            return 0

        repair = RepairBatch(args.batch_name, args.base_path)
        batch_path = repair.create_from_chain_list(
            chains,
            rerun_blast=args.rerun_blast,
            rerun_hhsearch=args.rerun_hhsearch,
            rerun_partition=args.rerun_partition
        )

    elif args.low_quality:
        print("Searching for low-quality chains...")
        chains = find_low_quality_chains(args.base_path)
        print(f"Found {len(chains)} low-quality chains")

        if args.dry_run or not chains:
            print(f"\n[DRY RUN] Would create repair batch with {len(chains)} chains")
            return 0

        repair = RepairBatch(args.batch_name, args.base_path)
        batch_path = repair.create_from_chain_list(
            chains,
            rerun_blast=args.rerun_blast,
            rerun_hhsearch=args.rerun_hhsearch,
            rerun_partition=args.rerun_partition
        )

    print(f"\n✓ Repair batch ready at: {batch_path}")
    print("\nNext steps:")
    print(f"  1. Review batch manifest: cat {batch_path}/batch_manifest.yaml")
    print(f"  2. Process batch (TODO: implement repair batch processing)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
