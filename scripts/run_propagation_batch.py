#!/usr/bin/env python3
"""
Run full cluster propagation batch.

Usage:
    # Dry run first
    python scripts/run_propagation_batch.py --dry-run

    # Real run
    python scripts/run_propagation_batch.py

    # With limit for testing
    python scripts/run_propagation_batch.py --limit 10
"""

import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.database.cluster_propagation import ClusterPropagator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Run cluster propagation batch")
    parser.add_argument("--dry-run", action="store_true", help="Preview without inserting")
    parser.add_argument("--limit", type=int, help="Limit number of representatives to process")
    parser.add_argument("--domain-version", default="pyecod_prod_ecod_q4_2025_q1_2026",
                        help="Domain version to propagate from")
    parser.add_argument("--start-date", default="2025-10-01", help="Start of release date range")
    parser.add_argument("--end-date", default="2026-01-31", help="End of release date range")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Cluster Propagation Batch")
    logger.info("=" * 60)
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'REAL RUN'}")
    logger.info(f"Domain version: {args.domain_version}")
    logger.info(f"Release dates: {args.start_date} to {args.end_date}")
    if args.limit:
        logger.info(f"Limit: {args.limit} representatives")
    logger.info("=" * 60)

    # Create propagator
    propagator = ClusterPropagator(dry_run=args.dry_run)

    # Run batch propagation
    start_time = datetime.now()

    summary = propagator.propagate_batch(
        domain_version=args.domain_version,
        release_dates=(args.start_date, args.end_date),
        limit=args.limit
    )

    elapsed = (datetime.now() - start_time).total_seconds()

    # Print summary
    summary.print_summary()

    logger.info(f"Processing time: {elapsed:.1f} seconds")
    if summary.total_members > 0:
        logger.info(f"Rate: {summary.total_members / elapsed:.1f} members/sec")

    # Print rollback instructions if real run
    if not args.dry_run and summary.total_domains_propagated > 0:
        logger.info("")
        logger.info("=" * 60)
        logger.info("ROLLBACK INSTRUCTIONS")
        logger.info("=" * 60)
        logger.info("To rollback propagated domains:")
        logger.info("")
        logger.info(f"DELETE FROM ecod_commons.domain_ranges WHERE domain_id IN (")
        logger.info(f"    SELECT id FROM ecod_commons.domains")
        logger.info(f"    WHERE domain_version = '{args.domain_version}_propagated'")
        logger.info(f");")
        logger.info("")
        logger.info(f"DELETE FROM ecod_commons.f_group_assignments WHERE domain_id IN (")
        logger.info(f"    SELECT id FROM ecod_commons.domains")
        logger.info(f"    WHERE domain_version = '{args.domain_version}_propagated'")
        logger.info(f");")
        logger.info("")
        logger.info(f"DELETE FROM ecod_commons.t_group_only_assignments WHERE domain_id IN (")
        logger.info(f"    SELECT id FROM ecod_commons.domains")
        logger.info(f"    WHERE domain_version = '{args.domain_version}_propagated'")
        logger.info(f");")
        logger.info("")
        logger.info(f"DELETE FROM ecod_commons.domains")
        logger.info(f"WHERE domain_version = '{args.domain_version}_propagated';")
        logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
