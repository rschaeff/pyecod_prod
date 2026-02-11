#!/usr/bin/env python3
"""
Demonstrate overlap detection and auto-accession logic.

This script shows how the new overlap detection system works
by testing against actual domains in ecod_commons.

Usage:
    python scripts/demo_overlap_detection.py
    python scripts/demo_overlap_detection.py --pdb 1a0p --chain A
    python scripts/demo_overlap_detection.py --test-range "A:10-100"
"""

import sys
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.database.domain_overlap import (
    DomainOverlapChecker,
    parse_range,
    calculate_overlap,
    assess_overlap_severity,
    OverlapSeverity,
)
from pyecod_prod.database.auto_accession import (
    AutoAccessionLoader,
    AccessionDecision,
)


def demo_range_parsing():
    """Demonstrate range parsing capabilities."""
    print("\n" + "="*60)
    print("DEMO 1: Range Parsing")
    print("="*60)

    test_ranges = [
        "A:10-150",                    # Simple chain-specified
        "A:10-50,A:100-150",           # Discontinuous
        "10-150",                      # Raw (AFDB style)
        "A:1-50,B:60-100",             # Multi-chain
        "A:-5-50",                     # Negative residue numbers
    ]

    for range_str in test_ranges:
        parsed = parse_range(range_str)
        print(f"\n  Input: {range_str}")
        print(f"    Segments: {len(parsed.segments)}")
        print(f"    Discontinuous: {parsed.is_discontinuous}")
        print(f"    Total length: {parsed.total_length}")
        print(f"    Chain: {parsed.chain_id or 'mixed/none'}")
        if parsed.segments:
            print(f"    Bounding: {parsed.min_residue}-{parsed.max_residue}")


def demo_overlap_calculation():
    """Demonstrate overlap calculation between ranges."""
    print("\n" + "="*60)
    print("DEMO 2: Overlap Calculation")
    print("="*60)

    test_cases = [
        ("A:10-50", "A:60-100", "No overlap"),
        ("A:10-50", "A:40-80", "Partial overlap"),
        ("A:10-50", "A:10-50", "Identical"),
        ("A:10-100", "A:15-95", "Loose correspondence"),
        ("A:10-100", "A:90-150", "Edge overlap (11 residues)"),
        ("A:10-50,A:100-150", "A:40-110", "Discontinuous overlap"),
    ]

    for range1_str, range2_str, description in test_cases:
        range1 = parse_range(range1_str)
        range2 = parse_range(range2_str)
        metrics = calculate_overlap(range1, range2)
        severity, message = assess_overlap_severity(metrics)

        print(f"\n  {description}:")
        print(f"    Range 1: {range1_str}")
        print(f"    Range 2: {range2_str}")
        print(f"    Overlap: {metrics['residue_overlap']} residues")
        print(f"    Coverage 1 by 2: {metrics['coverage_1_by_2']:.1%}")
        print(f"    Coverage 2 by 1: {metrics['coverage_2_by_1']:.1%}")
        print(f"    Severity: {severity.value}")
        print(f"    Message: {message}")


def demo_database_overlap_check(pdb_id: str, chain_id: str):
    """Check overlaps against existing domains in database."""
    print("\n" + "="*60)
    print(f"DEMO 3: Database Overlap Check for {pdb_id}_{chain_id}")
    print("="*60)

    checker = DomainOverlapChecker()

    # Get existing domains
    existing = checker.get_existing_domains(pdb_id, chain_id)

    if not existing:
        print(f"\n  No existing domains found for {pdb_id}_{chain_id}")
        return

    print(f"\n  Found {len(existing)} existing domain(s):")
    for domain in existing:
        print(f"    {domain['domain_id']}: {domain['range_definition']} (uid={domain['ecod_uid']})")

    # Test a hypothetical new domain
    if existing:
        # Try a range that overlaps with first domain
        first_range = parse_range(existing[0]['range_definition'])
        test_start = first_range.min_residue + 10
        test_end = first_range.max_residue + 50
        test_range = f"{chain_id}:{test_start}-{test_end}"

        print(f"\n  Testing hypothetical new domain: {test_range}")

        can_accession, conflicts = checker.can_auto_accession(pdb_id, chain_id, test_range)

        print(f"  Can auto-accession: {can_accession}")
        if conflicts:
            print(f"  Conflicts:")
            for conflict in conflicts:
                print(f"    - {conflict.existing_domain_id}: {conflict.severity.value}")
                print(f"      {conflict.message}")


def demo_auto_accession_dry_run(pdb_id: str, chain_id: str, test_range: str):
    """Demonstrate auto-accession with dry run."""
    print("\n" + "="*60)
    print(f"DEMO 4: Auto-Accession Dry Run")
    print("="*60)

    loader = AutoAccessionLoader(dry_run=True)

    print(f"\n  Attempting to accession domain:")
    print(f"    PDB: {pdb_id}")
    print(f"    Chain: {chain_id}")
    print(f"    Range: {test_range}")

    result = loader.accession_domain(
        pdb_id=pdb_id,
        chain_id=chain_id,
        range_definition=test_range,
        domain_num=1,
        t_group="1.1.1",
        h_group="1.1.1.1",
        processing_version="demo_script"
    )

    print(f"\n  Result:")
    print(f"    Decision: {result.decision.value}")
    print(f"    Original ID: {result.original_domain_id}")
    print(f"    Final ID: {result.final_domain_id}")
    print(f"    Message: {result.message}")

    if result.conflicts:
        print(f"    Conflicts: {len(result.conflicts)}")
        for conflict in result.conflicts:
            print(f"      - {conflict.existing_domain_id}: {conflict.severity.value}")


def demo_find_duplicate_ranges():
    """Find potential duplicate ranges in ecod_commons (raw vs chain-specified)."""
    print("\n" + "="*60)
    print("DEMO 5: Finding Potential Duplicate Ranges")
    print("="*60)

    import psycopg2

    conn_params = {
        "host": "dione",
        "port": 45000,
        "database": "ecod_protein",
        "user": "ecod",
        "password": "ecod#badmin"
    }

    conn = psycopg2.connect(**conn_params)
    cursor = conn.cursor()

    try:
        # Find domains with raw ranges (no chain prefix)
        cursor.execute("""
            SELECT COUNT(*) as raw_count
            FROM ecod_commons.domains
            WHERE range_definition NOT LIKE '%:%'
              AND is_obsolete = false
        """)
        raw_count = cursor.fetchone()[0]
        print(f"\n  Domains with raw ranges (no chain): {raw_count:,}")

        # Find domains with chain-specified ranges
        cursor.execute("""
            SELECT COUNT(*) as chain_count
            FROM ecod_commons.domains
            WHERE range_definition LIKE '%:%'
              AND is_obsolete = false
        """)
        chain_count = cursor.fetchone()[0]
        print(f"  Domains with chain-specified ranges: {chain_count:,}")

        # Sample raw ranges
        cursor.execute("""
            SELECT d.domain_id, d.range_definition, p.source_type
            FROM ecod_commons.domains d
            JOIN ecod_commons.proteins p ON d.protein_id = p.id
            WHERE d.range_definition NOT LIKE '%:%'
              AND d.is_obsolete = false
            LIMIT 5
        """)
        print(f"\n  Sample raw ranges:")
        for row in cursor.fetchall():
            print(f"    {row[0]}: {row[1]} (source: {row[2]})")

        # Check for potential duplicates (same protein, similar ranges)
        cursor.execute("""
            WITH range_pairs AS (
                SELECT
                    d1.domain_id as domain1,
                    d2.domain_id as domain2,
                    d1.range_definition as range1,
                    d2.range_definition as range2,
                    p.pdb_id,
                    p.chain_id
                FROM ecod_commons.domains d1
                JOIN ecod_commons.domains d2 ON d1.protein_id = d2.protein_id
                    AND d1.id < d2.id
                JOIN ecod_commons.proteins p ON d1.protein_id = p.id
                WHERE d1.is_obsolete = false
                  AND d2.is_obsolete = false
                  AND d1.range_definition NOT LIKE '%:%'
                  AND d2.range_definition LIKE '%:%'
            )
            SELECT * FROM range_pairs
            WHERE range1 = REGEXP_REPLACE(range2, '^[A-Za-z0-9]+:', '')
            LIMIT 10
        """)

        results = cursor.fetchall()
        if results:
            print(f"\n  Found {len(results)} potential duplicates (raw vs chain-specified):")
            for row in results:
                print(f"    {row[4]}_{row[5]}: {row[0]} ({row[2]}) vs {row[1]} ({row[3]})")
        else:
            print(f"\n  No obvious duplicates found")

    finally:
        cursor.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Demonstrate overlap detection and auto-accession"
    )
    parser.add_argument("--pdb", help="PDB ID to test")
    parser.add_argument("--chain", help="Chain ID to test")
    parser.add_argument("--test-range", help="Test range for accession")
    parser.add_argument("--skip-db", action="store_true", help="Skip database tests")

    args = parser.parse_args()

    # Always run basic demos
    demo_range_parsing()
    demo_overlap_calculation()

    if not args.skip_db:
        # Database demos
        pdb_id = args.pdb or "1a0p"
        chain_id = args.chain or "A"

        demo_database_overlap_check(pdb_id, chain_id)

        if args.test_range:
            demo_auto_accession_dry_run(pdb_id, chain_id, args.test_range)
        else:
            # Default test range
            demo_auto_accession_dry_run(pdb_id, chain_id, f"{chain_id}:1-50")

        demo_find_duplicate_ranges()

    print("\n" + "="*60)
    print("Demo complete!")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
