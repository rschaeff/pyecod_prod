#!/usr/bin/env python3
"""
Resume processing of an existing batch.
"""

import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.batch.weekly_batch import WeeklyBatch

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def main():
    # Load existing batch
    batch = WeeklyBatch(
        release_date="2025-09-05",
        pdb_status_dir="/usr2/pdb/data/status/20250905",
        base_path="/data/ecod/pdb_updates/batches",
        reference_version="develop291"
    )

    print("\n" + "="*60)
    print("Resuming batch: ecod_weekly_20250905")
    print("="*60)

    # Print current status
    batch.manifest.print_summary()

    print("\n" + "="*60)
    print("Step 1: Process existing BLAST results")
    print("="*60)
    batch.process_blast_results()

    print("\n" + "="*60)
    print("Step 2: Process existing HHsearch results")
    print("="*60)
    batch.process_hhsearch_results()

    print("\n" + "="*60)
    print("Step 3: Generate summaries")
    print("="*60)
    batch.generate_summaries()

    print("\n" + "="*60)
    print("Step 4: Check if new BLAST jobs needed")
    print("="*60)
    batch.manifest.print_summary()

    # Check how many chains still need BLAST
    blast_needed = [
        f"{chain_data['pdb_id']}_{chain_data['chain_id']}"
        for chain_data in batch.manifest.data['chains'].values()
        if chain_data['blast_status'] != 'complete' and chain_data['can_classify']
    ]

    if blast_needed:
        print(f"\n{len(blast_needed)} chains still need BLAST. Submit jobs? (y/n)")
        response = input().strip().lower()
        if response == 'y':
            print(f"\nSubmitting BLAST jobs for {len(blast_needed)} chains...")
            job_id = batch.blast_runner.submit_blast_jobs(
                batch_dir=str(batch.batch_path),
                fasta_dir=str(batch.dirs.fastas_dir),
                output_dir=str(batch.dirs.blast_dir),
                blast_type="both",
                partition="96GB",
                array_limit=500,
                chain_filter=blast_needed,
            )
            print(f"BLAST job submitted: {job_id}")
            print(f"Monitor with: squeue -j {job_id}")
    else:
        print("\n✅ All chains have completed BLAST")

    # Check how many chains still need HHsearch
    hhsearch_needed = [
        f"{chain_data['pdb_id']}_{chain_data['chain_id']}"
        for chain_data in batch.manifest.data['chains'].values()
        if chain_data.get('needs_hhsearch', False) and chain_data.get('hhsearch_status') != 'complete'
    ]

    if hhsearch_needed:
        print(f"\n{len(hhsearch_needed)} chains still need HHsearch. Submit jobs? (y/n)")
        response = input().strip().lower()
        if response == 'y':
            print(f"\nSubmitting HHsearch jobs for {len(hhsearch_needed)} chains...")
            job_id, success = batch.run_hhsearch(
                partition="96GB",
                array_limit=500,
                wait=False
            )
            if job_id:
                print(f"HHsearch job submitted: {job_id}")
                print(f"Monitor with: squeue -j {job_id}")
    else:
        print("\n✅ All needed chains have completed HHsearch")

    print("\n" + "="*60)
    print("Resume script complete")
    print("="*60)
    batch.manifest.print_summary()

if __name__ == "__main__":
    main()
