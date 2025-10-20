#!/usr/bin/env python3
"""
Run a medium-scale production test with 100 chains.

This script validates the complete pipeline at moderate scale:
1. Creates a test batch with 100 chains from a real PDB release
2. Runs BLAST jobs
3. Processes results and identifies low-coverage chains
4. Runs HHsearch for low-coverage chains
5. Generates summaries with combined evidence
6. Runs domain partitioning

Expected runtime: 1-2 hours
Expected storage: ~500MB
"""

import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.batch.weekly_batch import WeeklyBatch
from pyecod_prod.batch.manifest import BatchManifest


def main():
    """Run medium-scale production test"""

    # Configuration
    release_date = "2025-09-05"
    status_dir = "/usr2/pdb/data/status/20250905"
    base_path = "/data/ecod/test_batches"
    max_chains = 100

    print("=" * 70)
    print("Medium-Scale Production Test")
    print("=" * 70)
    print(f"Release date: {release_date}")
    print(f"Max chains: {max_chains}")
    print(f"Base path: {base_path}")
    print(f"Expected runtime: 1-2 hours")
    print()

    # Create batch
    print("Step 1: Creating batch...")
    batch = WeeklyBatch(
        release_date=release_date,
        pdb_status_dir=status_dir,
        base_path=base_path,
        reference_version="develop291",
    )

    batch.create_batch()
    print(f"✓ Batch created: {batch.batch_path}")
    print()

    # Process PDB updates (with chain limit)
    print("Step 2: Processing PDB updates...")
    result = batch.process_pdb_updates()

    # Limit to first N chains
    manifest = batch.manifest
    chain_keys = list(manifest.data["chains"].keys())
    classifiable_chains = [k for k in chain_keys if manifest.data["chains"][k]["can_classify"]]

    if len(classifiable_chains) > max_chains:
        print(f"Limiting to first {max_chains} classifiable chains...")
        chains_to_remove = classifiable_chains[max_chains:]

        for chain_key in chains_to_remove:
            del manifest.data["chains"][chain_key]

        manifest.data["processing_status"]["total_structures"] = max_chains
        manifest.save()

    print(f"✓ Test batch contains {len(manifest.data['chains'])} chains")
    print(f"  Classifiable: {manifest.data['processing_status']['total_structures']}")
    peptide_count = len([k for k in manifest.data["chains"].keys()
                        if not manifest.data["chains"][k]["can_classify"]])
    if peptide_count > 0:
        print(f"  Peptides filtered: {peptide_count}")
    print()

    # Generate FASTAs
    print("Step 3: Generating FASTA files...")
    batch.generate_fastas()
    print("✓ FASTAs generated")
    print()

    # Run BLAST
    print("Step 4: Submitting BLAST jobs...")
    print("  This will submit SLURM jobs for domain and chain BLAST...")
    print("  Expected runtime: 15-20 minutes")
    try:
        blast_job_id = batch.run_blast(partition="96GB", array_limit=500, wait=True)
        print(f"✓ BLAST jobs submitted: {blast_job_id}")
        print("  Waiting for jobs to complete...")
    except Exception as e:
        print(f"✗ BLAST submission failed: {e}")
        return 1

    print()

    # Process BLAST results
    print("Step 5: Processing BLAST results...")
    try:
        batch.process_blast_results()
        print("✓ BLAST results processed")

        # Show coverage stats
        manifest.save()
        low_cov_chains = manifest.chains_needing_hhsearch()
        print(f"  Chains needing HHsearch (coverage < 90%): {len(low_cov_chains)}")
        if len(low_cov_chains) > 0:
            pct = (len(low_cov_chains) / max_chains) * 100
            print(f"  Percentage needing HHsearch: {pct:.1f}%")
    except Exception as e:
        print(f"✗ BLAST processing failed: {e}")
        return 1

    print()

    # Run HHsearch if needed
    if len(low_cov_chains) > 0:
        print("Step 6: Submitting HHsearch jobs for low-coverage chains...")
        print(f"  Expected runtime: 30-45 minutes for ~{len(low_cov_chains)} chains")
        try:
            hhsearch_job_id = batch.run_hhsearch(partition="96GB", array_limit=500, wait=True)
            print(f"✓ HHsearch jobs submitted: {hhsearch_job_id}")
            print("  Waiting for jobs to complete...")
        except Exception as e:
            print(f"✗ HHsearch submission failed: {e}")
            return 1

        print()

        # Process HHsearch results
        print("Step 7: Processing HHsearch results...")
        try:
            batch.process_hhsearch_results()
            print("✓ HHsearch results processed")
        except Exception as e:
            print(f"✗ HHsearch processing failed: {e}")
            return 1

        print()
    else:
        print("Step 6: No chains need HHsearch (all have good BLAST coverage)")
        print()

    # Generate summaries
    print("Step 8: Generating domain summaries...")
    try:
        batch.generate_summaries()
        print("✓ Domain summaries generated")
    except Exception as e:
        print(f"✗ Summary generation failed: {e}")
        return 1

    print()

    # Run partitioning
    print("Step 9: Running domain partitioning...")
    try:
        batch.run_partitioning()
        print("✓ Partitioning complete")
    except Exception as e:
        print(f"✗ Partitioning failed: {e}")
        return 1

    print()

    # Print final summary
    print("=" * 70)
    print("Final Summary")
    print("=" * 70)
    batch.manifest.print_summary()

    print()
    print(f"Batch location: {batch.batch_path}")
    print("✓ Medium-scale production test complete!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
