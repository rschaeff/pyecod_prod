#!/usr/bin/env python3
"""
Run a full-week production test with all chains from a PDB release.

This script validates the complete pipeline at production scale:
1. Creates a batch with ALL chains from a weekly PDB release
2. Runs BLAST jobs for all classifiable chains
3. Processes results and identifies low-coverage chains
4. Runs HHsearch for low-coverage chains
5. Generates summaries with combined evidence
6. Runs domain partitioning

Expected runtime: 4-6 hours (depends on cluster load)
Expected storage: ~8-10GB
Expected chains: ~1,600-1,800 classifiable chains (varies by week)
"""

import sys
import time
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.batch.weekly_batch import WeeklyBatch
from pyecod_prod.batch.manifest import BatchManifest


def main():
    """Run full-week production test"""

    # Configuration
    release_date = "2025-09-05"
    status_dir = "/usr2/pdb/data/status/20250905"
    base_path = "/data/ecod/test_batches"

    start_time = datetime.now()

    print("=" * 70)
    print("Full-Week Production Test")
    print("=" * 70)
    print(f"Release date: {release_date}")
    print(f"Base path: {base_path}")
    print(f"Processing: ALL chains from weekly release")
    print(f"Expected runtime: 4-6 hours")
    print(f"Expected storage: ~8-10GB")
    print(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
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

    # Process PDB updates (NO chain limit - process all)
    print("Step 2: Processing PDB updates...")
    result = batch.process_pdb_updates()

    # Report statistics
    manifest = batch.manifest
    total_chains = len(manifest.data["chains"])
    classifiable = manifest.data["processing_status"]["total_structures"]
    peptide_count = total_chains - classifiable

    print(f"✓ PDB updates processed")
    print(f"  Total chains: {total_chains}")
    print(f"  Classifiable: {classifiable}")
    print(f"  Peptides filtered: {peptide_count} ({(peptide_count/total_chains)*100:.1f}%)")
    print()

    # Generate FASTAs
    print("Step 3: Generating FASTA files...")
    batch.generate_fastas()
    print(f"✓ FASTAs generated for {classifiable} chains")
    print()

    # Run BLAST
    print("Step 4: Submitting BLAST jobs...")
    print(f"  Submitting SLURM array job for {classifiable} chains")
    print("  BLAST database: chainwise100 + ecod100 (develop291)")
    print("  Array limit: 500 concurrent jobs")
    print("  Expected runtime: 1-2 hours")
    blast_start = datetime.now()
    try:
        blast_job_id = batch.run_blast(partition="96GB", array_limit=500, wait=True)
        blast_end = datetime.now()
        blast_duration = (blast_end - blast_start).total_seconds() / 60
        print(f"✓ BLAST jobs completed: {blast_job_id}")
        print(f"  Runtime: {blast_duration:.1f} minutes")
    except Exception as e:
        print(f"✗ BLAST submission failed: {e}")
        import traceback
        traceback.print_exc()
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
        pct_needing_hhsearch = (len(low_cov_chains) / classifiable) * 100

        print(f"  Total chains: {classifiable}")
        print(f"  Chains with good coverage (≥90%): {classifiable - len(low_cov_chains)}")
        print(f"  Chains needing HHsearch (<90%): {len(low_cov_chains)} ({pct_needing_hhsearch:.1f}%)")
    except Exception as e:
        print(f"✗ BLAST processing failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print()

    # Run HHsearch if needed
    if len(low_cov_chains) > 0:
        print("Step 6: Submitting HHsearch jobs for low-coverage chains...")
        print(f"  Submitting SLURM array job for {len(low_cov_chains)} chains")
        print("  HHsearch database: ecod_v291_hhm")
        print("  Array limit: 500 concurrent jobs")
        print(f"  Expected runtime: 2-4 hours")
        hhsearch_start = datetime.now()
        try:
            hhsearch_job_id = batch.run_hhsearch(partition="96GB", array_limit=500, wait=True)
            hhsearch_end = datetime.now()
            hhsearch_duration = (hhsearch_end - hhsearch_start).total_seconds() / 60
            print(f"✓ HHsearch jobs completed: {hhsearch_job_id}")
            print(f"  Runtime: {hhsearch_duration:.1f} minutes")
        except Exception as e:
            print(f"✗ HHsearch submission failed: {e}")
            import traceback
            traceback.print_exc()
            return 1

        print()

        # Process HHsearch results
        print("Step 7: Processing HHsearch results...")
        try:
            batch.process_hhsearch_results()
            print("✓ HHsearch results processed")
        except Exception as e:
            print(f"✗ HHsearch processing failed: {e}")
            import traceback
            traceback.print_exc()
            return 1

        print()
    else:
        print("Step 6: No chains need HHsearch (all have good BLAST coverage)")
        print("  This is unusual for a real release - verify BLAST results!")
        print()

    # Generate summaries
    print("Step 8: Generating domain summaries...")
    summary_start = datetime.now()
    try:
        batch.generate_summaries()
        summary_end = datetime.now()
        summary_duration = (summary_end - summary_start).total_seconds()
        print(f"✓ Domain summaries generated for {classifiable} chains")
        print(f"  Runtime: {summary_duration:.1f} seconds")
    except Exception as e:
        print(f"✗ Summary generation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print()

    # Run partitioning
    print("Step 9: Running domain partitioning...")
    partition_start = datetime.now()
    try:
        batch.run_partitioning()
        partition_end = datetime.now()
        partition_duration = (partition_end - partition_start).total_seconds() / 60
        print(f"✓ Partitioning complete for {classifiable} chains")
        print(f"  Runtime: {partition_duration:.1f} minutes")
    except Exception as e:
        print(f"✗ Partitioning failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print()

    # Print final summary
    end_time = datetime.now()
    total_duration = (end_time - start_time).total_seconds() / 3600

    print("=" * 70)
    print("Final Summary")
    print("=" * 70)
    batch.manifest.print_summary()

    print()
    print("=" * 70)
    print("Performance Statistics")
    print("=" * 70)
    print(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total runtime: {total_duration:.2f} hours")
    print(f"Chains processed: {classifiable}")
    print(f"Chains/hour: {classifiable/total_duration:.1f}")

    print()
    print(f"Batch location: {batch.batch_path}")
    print("✓ Full-week production test complete!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
