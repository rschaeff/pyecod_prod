#!/usr/bin/env python3
"""
Test real propagation on a small subset of cluster members.
"""

import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.database.cluster_propagation import (
    ClusterPropagator,
    PropagationTier,
)

def main():
    # Test with 7iep_A - just propagate to first 3 members
    rep_pdb_id = "7iep"
    rep_chain_id = "A"
    domain_version = "pyecod_prod_ecod_q4_2025_q1_2026"

    print(f"Testing REAL propagation from {rep_pdb_id}_{rep_chain_id}")
    print("=" * 60)

    # Create propagator (NOT dry-run)
    propagator = ClusterPropagator(dry_run=False)

    # Get representative's domains
    print("\n1. Getting representative domains...")
    rep_domains = propagator.get_representative_domains(
        rep_pdb_id, rep_chain_id, domain_version
    )
    print(f"   Found {len(rep_domains)} domains")

    # Get cluster members
    print("\n2. Getting first 3 cluster members...")
    members = propagator.get_cluster_members(
        rep_pdb_id, rep_chain_id,
        release_dates=('2025-10-01', '2026-01-31')
    )
    test_members = members[:3]
    print(f"   Testing with: {[m['pdb_id'] + '_' + m['chain_id'] for m in test_members]}")

    # Get representative length
    conn = propagator._get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sequence_length FROM pdb_update.chain_status
        WHERE pdb_id = %s AND chain_id = %s
    """, (rep_pdb_id, rep_chain_id))
    rep_length = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    # Propagate to each test member
    print("\n3. Propagating to test members...")
    results = []
    for m in test_members:
        tier = propagator.classify_member_tier(m['sequence_length'], rep_length)
        if tier in [PropagationTier.TIER1_AUTO, PropagationTier.TIER2_VERIFY]:
            result = propagator.propagate_to_member(
                m['pdb_id'], m['chain_id'],
                rep_domains, domain_version, tier
            )
            results.append(result)
            status = "✓" if result.success else "✗"
            print(f"   {status} {m['pdb_id']}_{m['chain_id']}: {result.message}")
            if result.error:
                print(f"      Error: {result.error}")

    # Verify in database
    print("\n4. Verifying database entries...")
    conn = propagator._get_connection()
    cursor = conn.cursor()

    for m in test_members:
        cursor.execute("""
            SELECT d.domain_id, d.ecod_uid, d.range_definition, fa.f_group_id
            FROM ecod_commons.domains d
            JOIN ecod_commons.proteins p ON d.protein_id = p.id
            LEFT JOIN ecod_commons.f_group_assignments fa ON d.id = fa.domain_id
            WHERE LOWER(p.pdb_id) = LOWER(%s) AND p.chain_id = %s
            AND d.domain_version LIKE %s
        """, (m['pdb_id'], m['chain_id'], f"{domain_version}%"))

        rows = cursor.fetchall()
        print(f"\n   {m['pdb_id']}_{m['chain_id']}:")
        for row in rows:
            print(f"     - {row[0]} (uid={row[1]}): {row[2]} -> {row[3]}")

    cursor.close()
    conn.close()

    print("\n" + "=" * 60)
    print("Test complete!")
    print("\nTo rollback test propagation:")
    print(f"DELETE FROM ecod_commons.domain_ranges WHERE domain_id IN (SELECT id FROM ecod_commons.domains WHERE domain_version LIKE '{domain_version}_propagated');")
    print(f"DELETE FROM ecod_commons.f_group_assignments WHERE domain_id IN (SELECT id FROM ecod_commons.domains WHERE domain_version LIKE '{domain_version}_propagated');")
    print(f"DELETE FROM ecod_commons.domains WHERE domain_version LIKE '{domain_version}_propagated';")


if __name__ == "__main__":
    main()
