#!/usr/bin/env python3
"""
Check the current state of the database (what's been synced/checked in).

This tool queries the PostgreSQL database to show:
- All weekly releases synced to database
- Processing status for each week
- Coverage statistics across all batches
- Failed chains requiring attention
- Chains pending HHsearch
- Overall database health

Usage:
    # Show overall database status
    python scripts/check_database_status.py

    # Show status for specific week
    python scripts/check_database_status.py --week 2025-09-05

    # Show failed chains
    python scripts/check_database_status.py --failed

    # Show chains needing HHsearch
    python scripts/check_database_status.py --hhsearch

    # Custom database connection
    python scripts/check_database_status.py --host db.example.com --database update_protein

    # JSON output
    python scripts/check_database_status.py --json
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    from pyecod_prod.database import DatabaseSync
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    print("Error: psycopg2 not available. Install with: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)


def get_overall_status(db_sync):
    """Get overall database status"""
    cursor = db_sync.conn.cursor()

    try:
        # Total batches
        cursor.execute("SELECT COUNT(*) FROM pdb_update.weekly_release")
        total_batches = cursor.fetchone()[0]

        # Status breakdown
        cursor.execute("""
            SELECT status, COUNT(*)
            FROM pdb_update.weekly_release
            GROUP BY status
            ORDER BY status
        """)
        status_counts = dict(cursor.fetchall())

        # Total chains
        cursor.execute("""
            SELECT
                COUNT(*) as total_chains,
                SUM(CASE WHEN can_classify THEN 1 ELSE 0 END) as classifiable,
                SUM(CASE WHEN blast_status = 'complete' THEN 1 ELSE 0 END) as blast_complete,
                SUM(CASE WHEN partition_status = 'complete' THEN 1 ELSE 0 END) as partition_complete
            FROM pdb_update.chain_status
        """)
        chain_stats = cursor.fetchone()

        # Date range
        cursor.execute("""
            SELECT MIN(release_date), MAX(release_date)
            FROM pdb_update.weekly_release
        """)
        date_range = cursor.fetchone()

        # Failed chains
        cursor.execute("SELECT COUNT(*) FROM pdb_update.failed_chains")
        failed_count = cursor.fetchone()[0]

        # Chains needing HHsearch
        cursor.execute("SELECT COUNT(*) FROM pdb_update.chains_needing_hhsearch")
        hhsearch_pending = cursor.fetchone()[0]

        # Coverage stats
        cursor.execute("""
            SELECT
                AVG(blast_coverage) as avg_blast,
                AVG(partition_coverage) as avg_partition,
                AVG(domain_count) as avg_domains
            FROM pdb_update.chain_status
            WHERE can_classify = true AND partition_status = 'complete'
        """)
        coverage_stats = cursor.fetchone()

        # Quality distribution
        cursor.execute("""
            SELECT partition_quality, COUNT(*)
            FROM pdb_update.chain_status
            WHERE partition_status = 'complete' AND partition_quality IS NOT NULL
            GROUP BY partition_quality
            ORDER BY partition_quality
        """)
        quality_dist = dict(cursor.fetchall())

        return {
            "batches": {
                "total": total_batches,
                "status_breakdown": status_counts,
                "date_range": {
                    "earliest": str(date_range[0]) if date_range[0] else None,
                    "latest": str(date_range[1]) if date_range[1] else None,
                },
            },
            "chains": {
                "total": chain_stats[0] if chain_stats[0] else 0,
                "classifiable": chain_stats[1] if chain_stats[1] else 0,
                "blast_complete": chain_stats[2] if chain_stats[2] else 0,
                "partition_complete": chain_stats[3] if chain_stats[3] else 0,
                "failed": failed_count,
                "hhsearch_pending": hhsearch_pending,
            },
            "coverage": {
                "avg_blast_coverage": float(coverage_stats[0]) if coverage_stats[0] else 0,
                "avg_partition_coverage": float(coverage_stats[1]) if coverage_stats[1] else 0,
                "avg_domain_count": float(coverage_stats[2]) if coverage_stats[2] else 0,
            },
            "quality": quality_dist,
        }

    finally:
        cursor.close()


def get_week_status(db_sync, week):
    """Get status for a specific week"""
    cursor = db_sync.conn.cursor()

    try:
        # Batch info
        cursor.execute("""
            SELECT
                batch_name, batch_path, status,
                total_structures, classifiable_chains, processed_structures,
                created_at, completed_at
            FROM pdb_update.weekly_release
            WHERE release_date = %s
        """, (week,))
        batch_info = cursor.fetchone()

        if not batch_info:
            return None

        # Chain status breakdown
        cursor.execute("""
            SELECT
                blast_status,
                COUNT(*) as count
            FROM pdb_update.chain_status
            WHERE release_date = %s AND can_classify = true
            GROUP BY blast_status
        """, (week,))
        blast_status = dict(cursor.fetchall())

        cursor.execute("""
            SELECT
                hhsearch_status,
                COUNT(*) as count
            FROM pdb_update.chain_status
            WHERE release_date = %s AND can_classify = true
            GROUP BY hhsearch_status
        """, (week,))
        hhsearch_status = dict(cursor.fetchall())

        cursor.execute("""
            SELECT
                partition_status,
                COUNT(*) as count
            FROM pdb_update.chain_status
            WHERE release_date = %s AND can_classify = true
            GROUP BY partition_status
        """, (week,))
        partition_status = dict(cursor.fetchall())

        # Coverage stats
        cursor.execute("""
            SELECT
                AVG(blast_coverage) as avg_blast,
                AVG(partition_coverage) as avg_partition,
                AVG(domain_count) as avg_domains
            FROM pdb_update.chain_status
            WHERE release_date = %s AND can_classify = true AND partition_status = 'complete'
        """, (week,))
        coverage_stats = cursor.fetchone()

        # Quality distribution
        cursor.execute("""
            SELECT partition_quality, COUNT(*)
            FROM pdb_update.chain_status
            WHERE release_date = %s AND partition_status = 'complete' AND partition_quality IS NOT NULL
            GROUP BY partition_quality
        """, (week,))
        quality_dist = dict(cursor.fetchall())

        return {
            "batch": {
                "name": batch_info[0],
                "path": batch_info[1],
                "status": batch_info[2],
                "total_structures": batch_info[3],
                "classifiable_chains": batch_info[4],
                "processed_structures": batch_info[5],
                "created_at": str(batch_info[6]) if batch_info[6] else None,
                "completed_at": str(batch_info[7]) if batch_info[7] else None,
            },
            "processing": {
                "blast": blast_status,
                "hhsearch": hhsearch_status,
                "partition": partition_status,
            },
            "coverage": {
                "avg_blast_coverage": float(coverage_stats[0]) if coverage_stats[0] else 0,
                "avg_partition_coverage": float(coverage_stats[1]) if coverage_stats[1] else 0,
                "avg_domain_count": float(coverage_stats[2]) if coverage_stats[2] else 0,
            },
            "quality": quality_dist,
        }

    finally:
        cursor.close()


def print_overall_status(status):
    """Print formatted overall status"""
    batches = status["batches"]
    chains = status["chains"]
    coverage = status["coverage"]
    quality = status["quality"]

    print(f"\n{'='*70}")
    print("Database Status - Overall Summary")
    print(f"{'='*70}")

    print(f"\nBatches:")
    print(f"  Total batches: {batches['total']}")
    if batches['date_range']['earliest']:
        print(f"  Date range: {batches['date_range']['earliest']} to {batches['date_range']['latest']}")
    print(f"  Status breakdown:")
    for batch_status, count in sorted(batches['status_breakdown'].items()):
        pct = (count / batches['total'] * 100) if batches['total'] > 0 else 0
        print(f"    {batch_status:15} {count:5} ({pct:5.1f}%)")

    print(f"\nChains:")
    print(f"  Total chains: {chains['total']:,}")
    print(f"  Classifiable: {chains['classifiable']:,}")
    blast_pct = (chains['blast_complete'] / chains['classifiable'] * 100) if chains['classifiable'] > 0 else 0
    print(f"  BLAST complete: {chains['blast_complete']:,} ({blast_pct:.1f}%)")
    partition_pct = (chains['partition_complete'] / chains['classifiable'] * 100) if chains['classifiable'] > 0 else 0
    print(f"  Partition complete: {chains['partition_complete']:,} ({partition_pct:.1f}%)")
    print(f"  Failed: {chains['failed']}")
    print(f"  HHsearch pending: {chains['hhsearch_pending']}")

    print(f"\nCoverage Statistics:")
    print(f"  Average BLAST coverage: {coverage['avg_blast_coverage']:.1%}")
    print(f"  Average partition coverage: {coverage['avg_partition_coverage']:.1%}")
    print(f"  Average domains/chain: {coverage['avg_domain_count']:.2f}")

    if quality:
        print(f"\nPartition Quality Distribution:")
        total_quality = sum(quality.values())
        for qual, count in sorted(quality.items()):
            pct = (count / total_quality * 100) if total_quality > 0 else 0
            print(f"  {qual:20} {count:6,} ({pct:5.1f}%)")

    print()


def print_week_status(week, status):
    """Print formatted week status"""
    if not status:
        print(f"No data found for week {week}")
        return

    batch = status["batch"]
    processing = status["processing"]
    coverage = status["coverage"]
    quality = status["quality"]

    print(f"\n{'='*70}")
    print(f"Database Status - Week {week}")
    print(f"{'='*70}")

    print(f"\nBatch: {batch['name']}")
    print(f"Path: {batch['path']}")
    print(f"Status: {batch['status'].upper()}")
    print(f"Created: {batch['created_at']}")
    if batch['completed_at']:
        print(f"Completed: {batch['completed_at']}")

    print(f"\nChains:")
    print(f"  Total structures: {batch['total_structures']}")
    print(f"  Classifiable: {batch['classifiable_chains']}")
    print(f"  Processed: {batch['processed_structures']}")

    print(f"\nProcessing Status:")
    print(f"  BLAST:")
    for blast_status, count in sorted(processing['blast'].items()):
        pct = (count / batch['classifiable_chains'] * 100) if batch['classifiable_chains'] > 0 else 0
        print(f"    {blast_status:12} {count:5} ({pct:5.1f}%)")

    print(f"  HHsearch:")
    for hhsearch_status, count in sorted(processing['hhsearch'].items()):
        print(f"    {hhsearch_status:12} {count:5}")

    print(f"  Partition:")
    for partition_status, count in sorted(processing['partition'].items()):
        pct = (count / batch['classifiable_chains'] * 100) if batch['classifiable_chains'] > 0 else 0
        print(f"    {partition_status:12} {count:5} ({pct:5.1f}%)")

    print(f"\nCoverage:")
    print(f"  Average BLAST coverage: {coverage['avg_blast_coverage']:.1%}")
    print(f"  Average partition coverage: {coverage['avg_partition_coverage']:.1%}")
    print(f"  Average domains/chain: {coverage['avg_domain_count']:.2f}")

    if quality:
        print(f"\nQuality Distribution:")
        total_quality = sum(quality.values())
        for qual, count in sorted(quality.items()):
            pct = (count / total_quality * 100) if total_quality > 0 else 0
            print(f"  {qual:20} {count:5} ({pct:5.1f}%)")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Check database status (what's been synced/checked in)"
    )

    # Database connection
    parser.add_argument("--host", default="localhost", help="Database host")
    parser.add_argument("--port", type=int, default=5432, help="Database port")
    parser.add_argument("--database", default="update_protein", help="Database name")
    parser.add_argument("--user", default="ecod", help="Database user")

    # Query options
    parser.add_argument("--week", help="Show status for specific week (YYYY-MM-DD)")
    parser.add_argument("--failed", action="store_true", help="Show failed chains")
    parser.add_argument("--hhsearch", action="store_true", help="Show chains needing HHsearch")
    parser.add_argument("--summary", action="store_true", help="Show batch summary table")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    # Connection params
    conn_params = {
        "host": args.host,
        "port": args.port,
        "database": args.database,
        "user": args.user,
        "password": None,
    }

    try:
        with DatabaseSync(conn_params) as db_sync:
            if args.week:
                # Show specific week
                status = get_week_status(db_sync, args.week)
                if args.json:
                    print(json.dumps(status, indent=2))
                else:
                    print_week_status(args.week, status)

            elif args.failed:
                # Show failed chains
                failed = db_sync.get_failed_chains()
                if args.json:
                    print(json.dumps(failed, indent=2, default=str))
                else:
                    print(f"\n{'='*70}")
                    print(f"Failed Chains: {len(failed)}")
                    print(f"{'='*70}\n")
                    if failed:
                        print(f"{'PDB':<6} {'Chain':<5} {'Week':<12} {'Reason'}")
                        print(f"{'-'*70}")
                        for chain in failed:
                            print(f"{chain['pdb_id']:<6} {chain['chain_id']:<5} {chain['release_date']!s:<12} {chain['failure_reason']}")
                    print()

            elif args.hhsearch:
                # Show chains needing HHsearch
                chains = db_sync.get_chains_needing_hhsearch()
                if args.json:
                    print(json.dumps(chains, indent=2, default=str))
                else:
                    print(f"\n{'='*70}")
                    print(f"Chains Needing HHsearch: {len(chains)}")
                    print(f"{'='*70}\n")
                    if chains:
                        print(f"{'PDB':<6} {'Chain':<5} {'Week':<12} {'BLAST Cov':<12} {'Status'}")
                        print(f"{'-'*70}")
                        for chain in chains[:50]:  # Limit to 50
                            blast_cov = f"{chain['blast_coverage']:.1%}" if chain['blast_coverage'] else "N/A"
                            print(f"{chain['pdb_id']:<6} {chain['chain_id']:<5} {chain['release_date']!s:<12} {blast_cov:<12} {chain['hhsearch_status']}")
                        if len(chains) > 50:
                            print(f"... and {len(chains) - 50} more")
                    print()

            elif args.summary:
                # Show batch summary
                summary = db_sync.get_batch_summary()
                if args.json:
                    print(json.dumps(summary, indent=2, default=str))
                else:
                    print(f"\n{'='*70}")
                    print("Batch Summary")
                    print(f"{'='*70}\n")
                    print(f"{'Date':<12} {'Status':<15} {'Chains':<8} {'Complete':<8} {'%':<6}")
                    print(f"{'-'*70}")
                    for batch in summary:
                        pct = batch.get('percent_complete', 0) or 0
                        print(f"{batch['release_date']!s:<12} {batch['status']:<15} "
                              f"{batch['classifiable_chains'] or 0:<8} {batch['processed_structures'] or 0:<8} {pct:<6.1f}%")
                    print()

            else:
                # Show overall status
                status = get_overall_status(db_sync)
                if args.json:
                    print(json.dumps(status, indent=2))
                else:
                    print_overall_status(status)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
