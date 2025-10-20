#!/usr/bin/env python3
"""
Check the processing status of a batch from its YAML manifest.

This tool provides a quick assessment of:
- Overall batch progress
- Chain processing statistics
- BLAST/HHsearch/partition completion rates
- File existence validation
- Processing stage breakdown

Usage:
    # Check specific batch
    python scripts/check_batch_status.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905

    # Check with verbose output
    python scripts/check_batch_status.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --verbose

    # Validate all file paths exist
    python scripts/check_batch_status.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --validate-files

    # JSON output for scripting
    python scripts/check_batch_status.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --json
"""

import sys
import json
import argparse
from pathlib import Path
from collections import Counter, defaultdict

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.batch.manifest import BatchManifest


def check_file_exists(batch_path: Path, relative_path: str) -> bool:
    """Check if a file exists relative to batch path"""
    if not relative_path:
        return False
    full_path = batch_path / relative_path
    return full_path.exists()


def analyze_batch(batch_path: str, validate_files=False):
    """
    Analyze batch manifest and return statistics.

    Returns:
        dict with analysis results
    """
    batch_path = Path(batch_path)
    manifest = BatchManifest(str(batch_path))
    data = manifest.data

    # Basic metadata
    batch_name = data.get("batch_name", "unknown")
    batch_type = data.get("batch_type", "weekly")
    created = data.get("created", "unknown")
    reference_version = data.get("reference_version", "unknown")

    # Chain statistics
    total_chains = len(data.get("chains", {}))
    classifiable_chains = sum(1 for c in data["chains"].values() if c.get("can_classify", True))
    non_classifiable = total_chains - classifiable_chains

    # Cannot classify reasons
    cannot_classify_reasons = Counter()
    for chain_data in data["chains"].values():
        if not chain_data.get("can_classify", True):
            reason = chain_data.get("cannot_classify_reason", "unknown")
            cannot_classify_reasons[reason] += 1

    # Processing status counts
    blast_status_counts = Counter()
    hhsearch_status_counts = Counter()
    partition_status_counts = Counter()
    needs_hhsearch_count = 0

    # Coverage statistics
    blast_coverages = []
    hhsearch_coverages = []
    partition_coverages = []

    # Quality statistics
    partition_qualities = Counter()
    domain_counts = []

    # File existence (if validating)
    file_stats = defaultdict(lambda: {"total": 0, "missing": 0})

    for chain_key, chain_data in data["chains"].items():
        if not chain_data.get("can_classify", True):
            continue

        # Status counts
        blast_status = chain_data.get("blast_status", "pending")
        blast_status_counts[blast_status] += 1

        hhsearch_status = chain_data.get("hhsearch_status", "not_needed")
        hhsearch_status_counts[hhsearch_status] += 1

        partition_status = chain_data.get("partition_status", "pending")
        partition_status_counts[partition_status] += 1

        # HHsearch need
        if chain_data.get("needs_hhsearch", False):
            needs_hhsearch_count += 1

        # Coverage
        if "blast_coverage" in chain_data and chain_data["blast_coverage"] is not None:
            blast_coverages.append(chain_data["blast_coverage"])

        if "hhsearch_coverage" in chain_data and chain_data["hhsearch_coverage"] is not None:
            hhsearch_coverages.append(chain_data["hhsearch_coverage"])

        if "partition_coverage" in chain_data and chain_data["partition_coverage"] is not None:
            partition_coverages.append(chain_data["partition_coverage"])

        # Quality
        if "partition_quality" in chain_data and chain_data["partition_quality"]:
            partition_qualities[chain_data["partition_quality"]] += 1

        if "domain_count" in chain_data and chain_data["domain_count"] is not None:
            domain_counts.append(chain_data["domain_count"])

        # File validation
        if validate_files:
            files = chain_data.get("files", {})
            for file_type, file_path in files.items():
                file_stats[file_type]["total"] += 1
                if not check_file_exists(batch_path, file_path):
                    file_stats[file_type]["missing"] += 1

    # Calculate averages
    avg_blast_coverage = sum(blast_coverages) / len(blast_coverages) if blast_coverages else 0
    avg_hhsearch_coverage = sum(hhsearch_coverages) / len(hhsearch_coverages) if hhsearch_coverages else 0
    avg_partition_coverage = sum(partition_coverages) / len(partition_coverages) if partition_coverages else 0
    avg_domain_count = sum(domain_counts) / len(domain_counts) if domain_counts else 0

    # Determine overall status
    if partition_status_counts.get("complete", 0) == classifiable_chains and classifiable_chains > 0:
        overall_status = "complete"
    elif partition_status_counts.get("complete", 0) > 0:
        overall_status = "in_progress"
    elif blast_status_counts.get("complete", 0) == classifiable_chains and classifiable_chains > 0:
        overall_status = "blast_complete"
    elif blast_status_counts.get("complete", 0) > 0:
        overall_status = "in_progress"
    else:
        overall_status = "pending"

    return {
        "metadata": {
            "batch_name": batch_name,
            "batch_type": batch_type,
            "batch_path": str(batch_path),
            "created": created,
            "reference_version": reference_version,
        },
        "chains": {
            "total": total_chains,
            "classifiable": classifiable_chains,
            "non_classifiable": non_classifiable,
            "cannot_classify_reasons": dict(cannot_classify_reasons),
        },
        "processing_status": {
            "overall": overall_status,
            "blast": dict(blast_status_counts),
            "hhsearch": dict(hhsearch_status_counts),
            "partition": dict(partition_status_counts),
            "needs_hhsearch": needs_hhsearch_count,
        },
        "coverage": {
            "blast": {
                "avg": avg_blast_coverage,
                "count": len(blast_coverages),
                "min": min(blast_coverages) if blast_coverages else 0,
                "max": max(blast_coverages) if blast_coverages else 0,
            },
            "hhsearch": {
                "avg": avg_hhsearch_coverage,
                "count": len(hhsearch_coverages),
                "min": min(hhsearch_coverages) if hhsearch_coverages else 0,
                "max": max(hhsearch_coverages) if hhsearch_coverages else 0,
            },
            "partition": {
                "avg": avg_partition_coverage,
                "count": len(partition_coverages),
                "min": min(partition_coverages) if partition_coverages else 0,
                "max": max(partition_coverages) if partition_coverages else 0,
            },
        },
        "quality": {
            "partition_qualities": dict(partition_qualities),
            "avg_domain_count": avg_domain_count,
            "domain_count_total": len(domain_counts),
        },
        "files": dict(file_stats) if validate_files else None,
    }


def print_analysis(analysis, verbose=False):
    """Print formatted analysis"""
    meta = analysis["metadata"]
    chains = analysis["chains"]
    status = analysis["processing_status"]
    coverage = analysis["coverage"]
    quality = analysis["quality"]
    files = analysis["files"]

    print(f"\n{'='*70}")
    print(f"Batch Status: {meta['batch_name']}")
    print(f"{'='*70}")
    print(f"Type: {meta['batch_type']}")
    print(f"Path: {meta['batch_path']}")
    print(f"Created: {meta['created']}")
    print(f"Reference: {meta['reference_version']}")
    print(f"Overall Status: {status['overall'].upper()}")

    print(f"\n{'='*70}")
    print("Chain Summary")
    print(f"{'='*70}")
    print(f"Total chains: {chains['total']}")
    print(f"  Classifiable: {chains['classifiable']}")
    print(f"  Non-classifiable: {chains['non_classifiable']}")
    if chains['cannot_classify_reasons']:
        print(f"  Reasons:")
        for reason, count in chains['cannot_classify_reasons'].items():
            print(f"    - {reason}: {count}")

    print(f"\n{'='*70}")
    print("Processing Progress")
    print(f"{'='*70}")
    print(f"BLAST Status:")
    for blast_status, count in sorted(status['blast'].items()):
        pct = (count / chains['classifiable'] * 100) if chains['classifiable'] > 0 else 0
        print(f"  {blast_status:12} {count:5} ({pct:5.1f}%)")

    print(f"\nHHsearch Status:")
    print(f"  Chains needing HHsearch: {status['needs_hhsearch']}")
    for hhsearch_status, count in sorted(status['hhsearch'].items()):
        print(f"  {hhsearch_status:12} {count:5}")

    print(f"\nPartition Status:")
    for partition_status, count in sorted(status['partition'].items()):
        pct = (count / chains['classifiable'] * 100) if chains['classifiable'] > 0 else 0
        print(f"  {partition_status:12} {count:5} ({pct:5.1f}%)")

    print(f"\n{'='*70}")
    print("Coverage Statistics")
    print(f"{'='*70}")
    print(f"BLAST Coverage:")
    print(f"  Chains: {coverage['blast']['count']}")
    print(f"  Average: {coverage['blast']['avg']:.1%}")
    print(f"  Range: {coverage['blast']['min']:.1%} - {coverage['blast']['max']:.1%}")

    if coverage['hhsearch']['count'] > 0:
        print(f"\nHHsearch Coverage:")
        print(f"  Chains: {coverage['hhsearch']['count']}")
        print(f"  Average: {coverage['hhsearch']['avg']:.1%}")
        print(f"  Range: {coverage['hhsearch']['min']:.1%} - {coverage['hhsearch']['max']:.1%}")

    if coverage['partition']['count'] > 0:
        print(f"\nPartition Coverage:")
        print(f"  Chains: {coverage['partition']['count']}")
        print(f"  Average: {coverage['partition']['avg']:.1%}")
        print(f"  Range: {coverage['partition']['min']:.1%} - {coverage['partition']['max']:.1%}")

    if quality['partition_qualities']:
        print(f"\n{'='*70}")
        print("Partition Quality")
        print(f"{'='*70}")
        for qual, count in sorted(quality['partition_qualities'].items()):
            pct = (count / quality['domain_count_total'] * 100) if quality['domain_count_total'] > 0 else 0
            print(f"  {qual:20} {count:5} ({pct:5.1f}%)")

        print(f"\nDomain Statistics:")
        print(f"  Average domains/chain: {quality['avg_domain_count']:.2f}")
        print(f"  Chains with domains: {quality['domain_count_total']}")

    if files:
        print(f"\n{'='*70}")
        print("File Validation")
        print(f"{'='*70}")
        for file_type, stats in sorted(files.items()):
            missing = stats['missing']
            total = stats['total']
            status_str = "✓" if missing == 0 else f"✗ {missing} missing"
            print(f"  {file_type:20} {total:5} files  {status_str}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Check batch processing status from YAML manifest"
    )
    parser.add_argument(
        "batch_path",
        help="Path to batch directory containing batch_manifest.yaml"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output"
    )
    parser.add_argument(
        "--validate-files",
        action="store_true",
        help="Check if all referenced files exist"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )

    args = parser.parse_args()

    try:
        analysis = analyze_batch(args.batch_path, validate_files=args.validate_files)

        if args.json:
            print(json.dumps(analysis, indent=2))
        else:
            print_analysis(analysis, verbose=args.verbose)

        # Exit code based on status
        if analysis["processing_status"]["overall"] == "complete":
            return 0
        else:
            return 1

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error analyzing batch: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 3


if __name__ == "__main__":
    sys.exit(main())
