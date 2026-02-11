#!/usr/bin/env python3
"""
Run full production workflow for weekly PDB release with CD-HIT clustering.

This script:
1. Parses PDB release and generates FASTAs
2. Runs CD-HIT at 70% identity to cluster chains
3. Selects representative chains for BLAST/HHsearch
4. Runs BLAST/HHsearch on representatives
5. Propagates results to cluster members
6. Generates summaries and partitions for all chains
"""

import sys
import subprocess
from pathlib import Path
from pyecod_prod.batch.weekly_batch import WeeklyBatch

def main():
    if len(sys.argv) != 2:
        print("Usage: python run_production_week_with_cdhit.py YYYYMMDD")
        print("Example: python run_production_week_with_cdhit.py 20250905")
        sys.exit(1)

    release_date = sys.argv[1]

    # Paths
    pdb_status_dir = f"/usr2/pdb/data/status/{release_date}"
    base_path = "/data/ecod/pdb_updates/batches"
    cdhit_bin = "/sw/apps/cdhit/cd-hit"

    print("="*70)
    print(f"ECOD Production Workflow with CD-HIT")
    print(f"Release: {release_date}")
    print("="*70)

    # Initialize batch
    print("\n[1/11] Initializing batch...")
    batch = WeeklyBatch(
        release_date=release_date,
        pdb_status_dir=pdb_status_dir,
        base_path=base_path,
        reference_version="develop291"
    )

    # Create batch directory structure
    batch.create_batch()

    # Parse PDB and generate FASTAs
    print("\n[2/11] Parsing PDB and generating FASTAs...")
    batch.process_pdb_updates()
    batch.generate_fastas()

    # Run CD-HIT clustering at 70% identity
    print("\n[3/11] Running CD-HIT clustering (70% identity)...")
    fasta_dir = batch.dirs.fastas_dir
    cdhit_input = fasta_dir / "all_chains.fasta"
    cdhit_output = fasta_dir / "representatives_70.fasta"
    cdhit_cluster = fasta_dir / "representatives_70.fasta.clstr"  # CD-HIT appends .clstr to output filename

    # Concatenate all FASTAs
    print(f"  Concatenating FASTAs...")
    with open(cdhit_input, 'w') as outf:
        for fasta_file in sorted(fasta_dir.glob("*.fa")):
            with open(fasta_file) as inf:
                outf.write(inf.read())

    # Generate SLURM script for CD-HIT
    print(f"  Generating SLURM script for CD-HIT...")
    slurm_script = batch.dirs.scripts_dir / "cdhit_clustering.sh"
    slurm_log = batch.dirs.slurm_logs_dir / "cdhit.out"
    slurm_err = batch.dirs.slurm_logs_dir / "cdhit.err"

    with open(slurm_script, 'w') as f:
        f.write(f"""#!/bin/bash
#SBATCH --job-name=cdhit_{release_date}
#SBATCH --output={slurm_log}
#SBATCH --error={slurm_err}
#SBATCH --partition=96GB
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=2:00:00

echo "Starting CD-HIT clustering at 70% identity"
echo "Input: {cdhit_input}"
echo "Output: {cdhit_output}"
echo "Started at: $(date)"

{cdhit_bin} \\
    -i {cdhit_input} \\
    -o {cdhit_output} \\
    -c 0.70 \\
    -n 4 \\
    -M 16000 \\
    -T 8 \\
    -d 0

echo "Completed at: $(date)"
""")

    # Submit CD-HIT job
    print(f"  Submitting CD-HIT job to SLURM...")
    result = subprocess.run(
        ["sbatch", str(slurm_script)],
        capture_output=True,
        text=True,
        check=True
    )

    # Extract job ID
    job_id = result.stdout.strip().split()[-1]
    print(f"  CD-HIT job submitted: {job_id}")

    # Wait for CD-HIT to complete
    print(f"  Waiting for CD-HIT job to complete...")
    while True:
        result = subprocess.run(
            ["squeue", "-j", job_id, "-h"],
            capture_output=True,
            text=True
        )
        if not result.stdout.strip():
            # Job no longer in queue - check if it completed
            result = subprocess.run(
                ["sacct", "-j", job_id, "--format=State", "-n"],
                capture_output=True,
                text=True
            )
            if "COMPLETED" in result.stdout:
                print(f"  CD-HIT completed successfully!")
                break
            else:
                print(f"  ERROR: CD-HIT job failed!")
                print(f"  Check logs: {slurm_err}")
                sys.exit(1)

        import time
        time.sleep(10)  # Check every 10 seconds

    # Parse cluster file to identify representatives
    print(f"  Parsing clusters...")
    representatives = set()
    with open(cdhit_cluster) as f:
        for line in f:
            if line.startswith(">"):
                continue
            if "*" in line:  # Representative sequence
                # Extract ID from: >pdb_chain...
                parts = line.split(">")[1].split("...")[0]
                representatives.add(parts)

    print(f"  Total chains: {len(list(fasta_dir.glob('*.fa')))}")
    print(f"  Representatives (70%): {len(representatives)}")
    print(f"  Reduction: {100 * (1 - len(representatives) / len(list(fasta_dir.glob('*.fa')))):.1f}%")

    # Mark non-representatives in manifest and create filtered FASTA directory
    print(f"  Marking cluster members in manifest...")
    rep_fasta_dir = batch.dirs.batch_dir / "rep_fastas"
    rep_fasta_dir.mkdir(parents=True, exist_ok=True)

    for chain_id in batch.manifest.data["chains"].keys():
        pdb_id, chain = chain_id.rsplit("_", 1)
        fasta_id = f"{pdb_id}_{chain}"
        if fasta_id not in representatives:
            # Mark as cluster member (will copy results from representative)
            batch.manifest.data["chains"][chain_id]["cluster_representative"] = None  # Will be filled later
        else:
            # Copy representative FASTA to filtered directory
            source_fasta = fasta_dir / f"{fasta_id}.fa"
            if source_fasta.exists():
                import shutil
                shutil.copy(source_fasta, rep_fasta_dir / f"{fasta_id}.fa")

    batch.manifest.save()

    print(f"  Copied {len(representatives)} representative FASTAs to {rep_fasta_dir.name}/")

    # Run BLAST on representatives only (357 chains, under 1000 job limit)
    print("\n[4/11] Submitting BLAST jobs (representatives only)...")

    # Submit BLAST using filtered FASTA directory
    job_id = batch.blast_runner.submit_blast_jobs(
        batch_dir=str(batch.dirs.batch_dir),
        fasta_dir=str(rep_fasta_dir),
        output_dir=str(batch.dirs.blast_dir),
        blast_type="both",
        partition="96GB",
        array_limit=500,
    )

    # Wait for completion
    print(f"Waiting for BLAST jobs to complete...")
    success = batch.blast_runner.wait_for_completion(job_id, verbose=True)

    if not success:
        print("\nERROR: BLAST jobs failed. Stopping workflow.")
        sys.exit(1)

    batch.process_blast_results()

    # Run HHsearch on low-coverage representatives
    print("\n[5/11] Submitting HHsearch jobs (low-coverage representatives)...")
    batch.run_hhsearch(partition="96GB", array_limit=500, wait=True)
    batch.process_hhsearch_results()

    # Propagate BLAST/HHsearch results to cluster members
    print("\n[6/11] Propagating results to cluster members...")
    # Parse cluster file to build representative -> members mapping
    cluster_map = {}  # rep_id -> [member_ids]
    current_cluster_rep = None

    with open(cdhit_cluster) as f:
        for line in f:
            if line.startswith(">Cluster"):
                current_cluster_rep = None
                continue

            # Extract sequence ID
            parts = line.split(">")[1].split("...")[0]

            if "*" in line:  # Representative
                current_cluster_rep = parts
                cluster_map[current_cluster_rep] = []
            else:  # Member
                if current_cluster_rep:
                    cluster_map[current_cluster_rep].append(parts)

    # Copy BLAST/HHsearch results from representatives to members
    for rep_id, members in cluster_map.items():
        rep_blast = batch.dirs.blast_dir / f"{rep_id}.chain_blast.xml"
        rep_domain_blast = batch.dirs.blast_dir / f"{rep_id}.domain_blast.xml"

        for member_id in members:
            if rep_blast.exists():
                member_blast = batch.dirs.blast_dir / f"{member_id}.chain_blast.xml"
                if not member_blast.exists():
                    import shutil
                    shutil.copy(rep_blast, member_blast)

            if rep_domain_blast.exists():
                member_domain_blast = batch.dirs.blast_dir / f"{member_id}.domain_blast.xml"
                if not member_domain_blast.exists():
                    import shutil
                    shutil.copy(rep_domain_blast, member_domain_blast)

            # Update manifest
            chain_id = member_id.replace("_", "_")  # pdb_chain format
            if chain_id in batch.manifest.data["chains"]:
                batch.manifest.mark_blast_complete(
                    chain_id.split("_")[0],
                    chain_id.split("_")[1],
                    coverage=batch.manifest.data["chains"].get(rep_id.replace("_", "_"), {}).get("blast_coverage", 0.0)
                )

    batch.manifest.save()

    # Load clustering to database for curation UI
    print("\n[7/11] Loading clustering to curation database...")
    cluster_name = f"ecod_weekly_{release_date}_70pct"
    cluster_result = subprocess.run([
        "python", "scripts/load_clustering.py",
        "--cluster-file", str(cdhit_cluster),
        "--threshold", "0.70",
        "--name", cluster_name
    ], capture_output=True, text=True, check=False)

    if cluster_result.returncode == 0:
        print(f"  Clustering loaded: {cluster_name}")
        # Show stats
        stats_result = subprocess.run([
            "python", "scripts/load_clustering.py", "--stats"
        ], capture_output=True, text=True)
        if stats_result.returncode == 0:
            print(stats_result.stdout)
    else:
        print(f"  WARNING: Clustering load failed (non-fatal):")
        print(f"  {cluster_result.stderr}")

    # Generate summaries for all chains
    print("\n[8/11] Generating domain summaries (all chains)...")
    batch.generate_summaries()

    # Run partitioning for all chains
    print("\n[9/11] Running domain partitioning (all chains)...")
    batch.run_partitioning()

    # Load to curation schema
    print("\n[10/11] Loading to curation schema...")
    load_result = subprocess.run([
        "python", "scripts/load_to_curation.py",
        "--batch-dir", str(batch.dirs.batch_dir),
        "--batch-name", batch.batch_name
    ], capture_output=True, text=True, check=False)

    if load_result.returncode == 0:
        print(f"  Loaded to ecod_curation schema")
    else:
        print(f"  WARNING: Curation load may have issues:")
        print(f"  {load_result.stderr}")

    # Complete
    print("\n[11/11] Workflow complete!")
    batch.manifest.print_summary()

    print(f"\n{'='*70}")
    print(f"Production batch complete: {batch.batch_name}")
    print(f"Location: {batch.dirs.batch_dir}")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
