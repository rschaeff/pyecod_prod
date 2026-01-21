#!/usr/bin/env python3
"""
Auto-accession domains from partition XMLs to ecod_commons.

This script processes partition XMLs from pyecod-mini and loads approved domains
into the ecod_commons schema, implementing the same overlap detection logic as
the legacy Perl script (process_domain_summary_to_ecod_release.pl).

Key features:
- Dry-run mode for previewing changes
- Coverage filtering (default: >=80%)
- Overlap detection (identical, loose correspondence, >10 residue conflict)
- Domain ID collision handling (auto-renumber)
- Version tracking for all inserted domains
- JSON report generation
- Rollback support via domain_version field

Usage:
    # Dry run (preview only)
    python scripts/auto_accession_batch.py \
        /data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/partitions_v293_fixed \
        --dry-run

    # Real run with batch ID
    python scripts/auto_accession_batch.py \
        /data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/partitions_v293_fixed \
        --batch-id ecod_q4_2025_q1_2026

    # With explicit versions and coverage threshold
    python scripts/auto_accession_batch.py \
        /data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/partitions_v293_fixed \
        --batch-id ecod_q4_2025_q1_2026 \
        --pyecod-mini-version 2.0.3 \
        --pyecod-prod-version 1.0.0 \
        --ecod-reference v293.1 \
        --min-coverage 0.80

    # Limited test run
    python scripts/auto_accession_batch.py \
        /data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/partitions_v293_fixed \
        --dry-run \
        --limit 10
"""

import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.parsers.partition_parser import (
    parse_partition_directory,
)
from pyecod_prod.database.auto_accession import (
    AutoAccessionLoader,
    ProcessingContext,
    generate_accession_report,
    get_pyecod_mini_version,
    get_pyecod_prod_version,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Known designed proteins to exclude from the Q4 2025 + Q1 2026 batch
DESIGNED_PROTEINS = {
    "9hnh", "9hn3", "9hn0", "9hml", "9hmk", "9hmj", "9hmi", "9hmh",
    "9h9h", "9h9g", "9h9f", "9h9e", "9h9d", "9h9c", "9h9a", "9h99",
    "9h98", "9r0t"
}


def main():
    parser = argparse.ArgumentParser(
        description="Auto-accession domains from partition XMLs to ecod_commons"
    )

    parser.add_argument(
        "partition_dir",
        type=Path,
        help="Directory containing partition XML files"
    )

    parser.add_argument(
        "--batch-id",
        help="Batch identifier for tracking (required for real run)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without inserting to database"
    )

    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.80,
        help="Minimum coverage threshold (default: 0.80)"
    )

    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of partition XMLs to process (for testing)"
    )

    parser.add_argument(
        "--pyecod-mini-version",
        help="pyecod-mini version (auto-detected if not specified)"
    )

    parser.add_argument(
        "--pyecod-prod-version",
        help="pyecod-prod version (auto-detected if not specified)"
    )

    parser.add_argument(
        "--ecod-reference",
        help="ECOD reference version used for evidence (e.g., v293.1)"
    )

    parser.add_argument(
        "--output-report",
        type=Path,
        help="Path to write JSON report"
    )

    parser.add_argument(
        "--include-designed",
        action="store_true",
        help="Include designed proteins (normally excluded)"
    )

    parser.add_argument(
        "--max-residue-overlap",
        type=int,
        default=10,
        help="Maximum allowed residue overlap (default: 10)"
    )

    parser.add_argument(
        "--max-coverage-overlap",
        type=float,
        default=0.80,
        help="Maximum allowed bidirectional coverage overlap (default: 0.80)"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.dry_run and not args.batch_id:
        parser.error("--batch-id is required for real runs (use --dry-run for preview)")

    if not args.partition_dir.is_dir():
        parser.error(f"Partition directory not found: {args.partition_dir}")

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create processing context
    context = ProcessingContext(
        batch_id=args.batch_id or "dry_run",
        pyecod_mini_version=args.pyecod_mini_version or get_pyecod_mini_version(),
        pyecod_prod_version=args.pyecod_prod_version or get_pyecod_prod_version(),
        ecod_reference_version=args.ecod_reference
    )

    logger.info(f"{'='*60}")
    logger.info(f"Auto-Accession Batch Processing")
    logger.info(f"{'='*60}")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'REAL RUN'}")
    logger.info(f"Partition directory: {args.partition_dir}")
    logger.info(f"Batch ID: {context.batch_id}")
    logger.info(f"Min coverage: {args.min_coverage:.0%}")
    logger.info(f"Max residue overlap: {args.max_residue_overlap}")
    logger.info(f"Max coverage overlap: {args.max_coverage_overlap:.0%}")
    if args.limit:
        logger.info(f"Limit: {args.limit} partitions")
    logger.info(f"Versions:")
    logger.info(f"  pyecod-mini: {context.pyecod_mini_version or 'unknown'}")
    logger.info(f"  pyecod-prod: {context.pyecod_prod_version or 'unknown'}")
    logger.info(f"  ECOD reference: {context.ecod_reference_version or 'unknown'}")
    logger.info(f"{'='*60}")

    # Determine excluded PDBs
    exclude_pdbs = set() if args.include_designed else DESIGNED_PROTEINS
    if exclude_pdbs:
        logger.info(f"Excluding {len(exclude_pdbs)} designed proteins")

    # Parse partition XMLs
    logger.info(f"\nParsing partition XMLs...")
    partitions = parse_partition_directory(
        args.partition_dir,
        min_coverage=0.0,  # We'll filter later to count skipped
        limit=args.limit
    )

    total_partitions = len(list(args.partition_dir.glob("*.partition.xml")))
    if args.limit:
        total_partitions = min(total_partitions, args.limit)

    logger.info(f"Parsed {len(partitions)} partition XMLs")

    # Count partitions by coverage
    high_coverage = sum(1 for p in partitions if p.coverage >= args.min_coverage)
    low_coverage = len(partitions) - high_coverage

    logger.info(f"  >= {args.min_coverage:.0%} coverage: {high_coverage}")
    logger.info(f"  < {args.min_coverage:.0%} coverage: {low_coverage} (will be skipped)")

    # Count total domains
    total_domains = sum(len(p.domains) for p in partitions if p.coverage >= args.min_coverage)
    logger.info(f"  Total domains to process: {total_domains}")

    # Create loader
    loader = AutoAccessionLoader(
        max_residue_overlap=args.max_residue_overlap,
        max_coverage=args.max_coverage_overlap,
        defer_moderate_overlaps=False,  # For now, don't defer - reject or accept
        dry_run=args.dry_run
    )

    # Prefetch existing domains for all PDBs in batch (major optimization)
    pdb_ids = list(set(p.pdb_id for p in partitions if p.coverage >= args.min_coverage))
    logger.info(f"\nPrefetching existing data for {len(pdb_ids)} PDB IDs...")

    # Prefetch domains for overlap checks
    prefetch_count = loader.overlap_checker.prefetch_domains_for_pdbs(pdb_ids)
    logger.info(f"  Cached {prefetch_count} existing domains")

    # Prefetch domain IDs for collision checks (e.g., "e9qf6%")
    domain_id_prefixes = [f"e{pdb_id.lower()}" for pdb_id in pdb_ids]
    domain_id_count = loader.prefetch_domain_ids(domain_id_prefixes)
    logger.info(f"  Cached {domain_id_count} existing domain IDs")

    # Process partitions
    logger.info(f"\nProcessing domains...")
    start_time = datetime.now()

    summary = loader.accession_batch_from_partitions(
        partition_results=partitions,
        context=context,
        min_coverage=args.min_coverage,
        exclude_pdbs=exclude_pdbs
    )

    elapsed = (datetime.now() - start_time).total_seconds()

    # Print summary
    summary.print_summary()

    logger.info(f"Processing time: {elapsed:.1f} seconds")
    logger.info(f"Rate: {summary.total_domains / elapsed:.1f} domains/sec" if elapsed > 0 else "N/A")

    # Generate and save report
    report = generate_accession_report(
        summary=summary,
        context=context,
        partition_dir=str(args.partition_dir),
        partition_count=total_partitions,
        min_coverage=args.min_coverage
    )

    # Determine report path
    if args.output_report:
        report_path = args.output_report
    else:
        # Default path in batch directory
        report_name = f"accession_{'dry_run' if args.dry_run else 'report'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path = args.partition_dir.parent / report_name

    # Save report
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    logger.info(f"\nReport saved to: {report_path}")

    # Print rollback instructions if real run
    if not args.dry_run and (summary.accepted > 0 or summary.renumbered > 0):
        domain_version = context.to_domain_version()
        logger.info(f"\n{'='*60}")
        logger.info(f"ROLLBACK INSTRUCTIONS")
        logger.info(f"{'='*60}")
        logger.info(f"To rollback this batch, run the following SQL:")
        logger.info(f"")
        logger.info(f"BEGIN;")
        logger.info(f"")
        logger.info(f"-- Check what will be deleted")
        logger.info(f"SELECT COUNT(*) FROM ecod_commons.domains")
        logger.info(f"WHERE domain_version = '{domain_version}';")
        logger.info(f"")
        logger.info(f"-- Delete F-group assignments")
        logger.info(f"DELETE FROM ecod_commons.f_group_assignments")
        logger.info(f"WHERE domain_id IN (")
        logger.info(f"    SELECT id FROM ecod_commons.domains")
        logger.info(f"    WHERE domain_version = '{domain_version}'")
        logger.info(f");")
        logger.info(f"")
        logger.info(f"-- Delete T-group assignments")
        logger.info(f"DELETE FROM ecod_commons.t_group_only_assignments")
        logger.info(f"WHERE domain_id IN (")
        logger.info(f"    SELECT id FROM ecod_commons.domains")
        logger.info(f"    WHERE domain_version = '{domain_version}'")
        logger.info(f");")
        logger.info(f"")
        logger.info(f"-- Delete domains")
        logger.info(f"DELETE FROM ecod_commons.domains")
        logger.info(f"WHERE domain_version = '{domain_version}';")
        logger.info(f"")
        logger.info(f"COMMIT;")
        logger.info(f"{'='*60}")

    # Return exit code based on success
    if summary.failed > 0:
        logger.warning(f"\n{summary.failed} domains failed to process")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
