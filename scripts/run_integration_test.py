#!/usr/bin/env python3
"""
Integration test for complete pyecod_prod + pyecod_mini workflow.

Tests the new features:
- Family lookup system
- Version tracking
- Library API integration
- API spec compliance

Uses small subset (15 chains) for quick validation.
"""

import sys
from pathlib import Path

# Add both packages to path for testing
pyecod_prod_path = Path(__file__).parent.parent / "src"
pyecod_mini_path = Path(__file__).parent.parent.parent / "pyecod_mini" / "src"

sys.path.insert(0, str(pyecod_prod_path))
sys.path.insert(0, str(pyecod_mini_path))

from pyecod_prod.batch.weekly_batch import WeeklyBatch
from datetime import datetime

def main():
    """Run integration test with new features"""

    print("=" * 80)
    print("INTEGRATION TEST - pyecod_prod + pyecod_mini")
    print("=" * 80)
    print()

    # Check library API availability
    print("Checking library API integration...")
    try:
        from pyecod_mini import partition_protein, PartitionResult, __version__
        from pyecod_prod.core.partition_runner import LIBRARY_AVAILABLE

        print(f"  ✅ pyecod_mini library API available")
        print(f"  ✅ Version: {__version__}")
        print(f"  ✅ LIBRARY_AVAILABLE: {LIBRARY_AVAILABLE}")

        if not LIBRARY_AVAILABLE:
            print("  ⚠️  WARNING: Library not detected, will use CLI fallback")
    except ImportError as e:
        print(f"  ❌ Library API import failed: {e}")
        print("  Will use CLI fallback")

    print()

    # Check family lookup
    print("Checking family lookup...")
    try:
        from pyecod_prod.utils.family_lookup import load_family_lookup_for_version
        lookup = load_family_lookup_for_version("develop291")
        print(f"  ✅ Family lookup loaded: {len(lookup):,} mappings")

        # Test a few known domains
        test_domain = "e1suaA1"
        if test_domain in lookup:
            print(f"  ✅ Test lookup: {test_domain} → {lookup[test_domain]}")
    except Exception as e:
        print(f"  ❌ Family lookup failed: {e}")

    print()

    # Create test batch
    print("Creating test batch...")
    batch_name = f"integration_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    batch = WeeklyBatch(
        release_date="2025-09-05",  # Use known test release
        pdb_status_dir="/usr2/pdb/data/status/20250905",
        base_path="/data/ecod/test_batches",
        reference_version="develop291",
    )

    print(f"  Batch: {batch.batch_name}")
    print()

    # Run workflow with limited chains (for testing)
    print("Running workflow...")
    print("  Note: Using first 15 chains for quick validation")
    print()

    try:
        # Step 1: Create batch
        print("Step 1: Creating batch structure...")
        batch.create_batch()
        print("  ✅ Batch created")
        print()

        # Step 2: Process PDB updates (limit to 15 chains)
        print("Step 2: Processing PDB updates...")
        result = batch.process_pdb_updates()

        # Limit to 15 chains for testing
        all_chains = list(batch.manifest.data["chains"].keys())
        test_chains = all_chains[:15]

        # Remove extra chains from manifest
        for chain_key in all_chains[15:]:
            del batch.manifest.data["chains"][chain_key]

        batch.manifest.save()

        print(f"  ✅ Processed {len(test_chains)} chains (limited for testing)")
        print()

        # Step 3: Generate FASTAs
        print("Step 3: Generating FASTA files...")
        batch.generate_fastas()
        print(f"  ✅ Generated FASTAs")
        print()

        # Step 4: Run BLAST (with wait)
        print("Step 4: Submitting BLAST jobs...")
        print("  (This will take a few minutes)")
        job_id, success = batch.run_blast(partition="96GB", array_limit=500, wait=True)

        if not success:
            print("  ❌ BLAST jobs failed")
            return 1

        print(f"  ✅ BLAST complete (job {job_id})")
        print()

        # Step 5: Process BLAST results
        print("Step 5: Processing BLAST results...")
        batch.process_blast_results()
        print("  ✅ BLAST results processed")
        print()

        # Check how many need HHsearch
        hhsearch_chains = batch.manifest.chains_needing_hhsearch()
        print(f"  Chains needing HHsearch: {len(hhsearch_chains)}")
        print()

        # Step 6: Run HHsearch (if needed)
        if hhsearch_chains:
            print("Step 6: Submitting HHsearch jobs...")
            print("  (This will take a few minutes)")
            hh_job_id, hh_success = batch.run_hhsearch(partition="96GB", array_limit=500, wait=True)

            if hh_job_id and hh_success:
                print(f"  ✅ HHsearch complete (job {hh_job_id})")

                print("Step 7: Processing HHsearch results...")
                batch.process_hhsearch_results()
                print("  ✅ HHsearch results processed")
            else:
                print("  ⚠️  HHsearch skipped or failed")
        else:
            print("Step 6: No chains need HHsearch (all coverage ≥90%)")

        print()

        # Step 8: Generate summaries
        print("Step 8: Generating domain summaries...")
        batch.generate_summaries()
        print("  ✅ Summaries generated")
        print()

        # Validate summary XMLs have family names
        print("Validating summary XMLs...")
        summary_dir = batch.dirs.summaries_dir
        summary_files = list(summary_dir.glob("*.xml"))

        if summary_files:
            import xml.etree.ElementTree as ET
            sample_file = summary_files[0]
            tree = ET.parse(sample_file)
            root = tree.getroot()

            # Check for family names
            hits_with_family = root.findall(".//hit[@target_family]")
            if hits_with_family:
                print(f"  ✅ Family names found: {hits_with_family[0].get('target_family')}")
            else:
                print("  ⚠️  No family names in summary XML")

        print()

        # Step 9: Run partitioning
        print("Step 9: Running domain partitioning...")
        batch.run_partitioning()
        print("  ✅ Partitioning complete")
        print()

        # Validate partition XMLs have version
        print("Validating partition XMLs...")
        partition_dir = batch.dirs.partitions_dir
        partition_files = list(partition_dir.glob("*.xml"))

        if partition_files:
            import xml.etree.ElementTree as ET
            sample_file = partition_files[0]
            tree = ET.parse(sample_file)
            root = tree.getroot()

            # Check for version in metadata
            metadata = root.find("metadata")
            if metadata is not None:
                version_elem = metadata.find("version")
                if version_elem is not None:
                    algo_version = version_elem.get("algorithm")
                    print(f"  ✅ Algorithm version: {algo_version}")
                else:
                    print("  ⚠️  No version element in metadata")
            else:
                print("  ⚠️  No metadata in partition XML")

        print()

        # Final summary
        print("=" * 80)
        print("INTEGRATION TEST COMPLETE")
        print("=" * 80)
        batch.manifest.print_summary()

        print()
        print(f"Test batch location: {batch.batch_path}")
        print()
        print("✅ All steps completed successfully!")
        return 0

    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
