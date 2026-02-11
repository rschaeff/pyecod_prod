#!/usr/bin/env python3
"""
Test script for cluster propagation module.

Tests propagation from a single representative to its cluster members.
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
    # Test with 7iep_A which has 2 domains and 143 members
    rep_pdb_id = "7iep"
    rep_chain_id = "A"
    domain_version = "pyecod_prod_ecod_q4_2025_q1_2026"

    print(f"Testing propagation from {rep_pdb_id}_{rep_chain_id}")
    print("=" * 60)

    # Create propagator in dry-run mode first
    propagator = ClusterPropagator(dry_run=True)

    # Get representative's domains
    print("\n1. Getting representative domains...")
    rep_domains = propagator.get_representative_domains(
        rep_pdb_id, rep_chain_id, domain_version
    )
    print(f"   Found {len(rep_domains)} domains:")
    for d in rep_domains:
        print(f"   - {d['domain_id']}: {d['range_definition']} ({d['f_group']})")

    # Get cluster members
    print("\n2. Getting cluster members...")
    members = propagator.get_cluster_members(
        rep_pdb_id, rep_chain_id,
        release_dates=('2025-10-01', '2026-01-31')
    )
    print(f"   Found {len(members)} members")

    # Show first 5 members
    print("\n   First 5 members:")
    for m in members[:5]:
        print(f"   - {m['pdb_id']}_{m['chain_id']}: length={m['sequence_length']}, status={m['ecod_status']}")

    # Test tier classification
    print("\n3. Testing tier classification...")
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

    print(f"   Representative length: {rep_length}")

    tier_counts = {tier: 0 for tier in PropagationTier}
    for m in members:
        tier = propagator.classify_member_tier(m['sequence_length'], rep_length)
        tier_counts[tier] += 1

    print("\n   Tier distribution:")
    for tier, count in tier_counts.items():
        if count > 0:
            print(f"   - {tier.value}: {count}")

    # Test dry-run propagation for first 3 members
    print("\n4. Testing dry-run propagation (first 3 members)...")
    for m in members[:3]:
        tier = propagator.classify_member_tier(m['sequence_length'], rep_length)
        if tier in [PropagationTier.TIER1_AUTO, PropagationTier.TIER2_VERIFY]:
            result = propagator.propagate_to_member(
                m['pdb_id'], m['chain_id'],
                rep_domains, domain_version, tier
            )
            print(f"   - {m['pdb_id']}_{m['chain_id']}: {result.message}")

    # Test full propagation from representative (dry run)
    print("\n5. Testing full propagation from representative (dry run)...")
    results = propagator.propagate_from_representative(
        rep_pdb_id, rep_chain_id,
        domain_version,
        release_dates=('2025-10-01', '2026-01-31')
    )

    # Summarize results
    tier1_success = sum(1 for r in results if r.tier == PropagationTier.TIER1_AUTO and r.success)
    tier2_success = sum(1 for r in results if r.tier == PropagationTier.TIER2_VERIFY and r.success)
    tier3_reclassify = sum(1 for r in results if r.tier == PropagationTier.TIER3_RECLASSIFY)
    already_classified = sum(1 for r in results if r.tier == PropagationTier.ALREADY_CLASSIFIED)

    print(f"\n   Results:")
    print(f"   - Tier 1 (auto): {tier1_success}")
    print(f"   - Tier 2 (verify): {tier2_success}")
    print(f"   - Tier 3 (reclassify): {tier3_reclassify}")
    print(f"   - Already classified: {already_classified}")

    print("\n" + "=" * 60)
    print("Dry-run test complete!")
    print("\nTo run actual propagation, use:")
    print(f"  propagator = ClusterPropagator(dry_run=False)")
    print(f"  results = propagator.propagate_from_representative('{rep_pdb_id}', '{rep_chain_id}', ...)")


if __name__ == "__main__":
    main()
