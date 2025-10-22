#!/usr/bin/env python3
"""
Run sequence clustering on FASTA files using mmseqs2 or CD-HIT.

Decoupled from BLAST workflow - can be run independently on any FASTA dataset.

Usage:
    # Cluster with mmseqs2 (recommended for large datasets)
    python scripts/run_clustering.py \\
        all_chains.fasta \\
        clustering_70pct \\
        --method mmseqs2 \\
        --threshold 0.70

    # Cluster with CD-HIT (traditional method)
    python scripts/run_clustering.py \\
        all_chains.fasta \\
        clustering_70pct \\
        --method cd-hit \\
        --threshold 0.70

    # For SLURM submission
    python scripts/run_clustering.py \\
        all_chains.fasta \\
        clustering_70pct \\
        --method mmseqs2 \\
        --submit \\
        --partition 96GB
"""

import argparse
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# mmseqs2 path
MMSEQS_BIN = "/sw/apps/mmseqs/bin/mmseqs"
CDHIT_BIN = "/sw/apps/cdhit/cd-hit"


def run_mmseqs2_clustering(
    fasta_file: str,
    output_prefix: str,
    identity_threshold: float = 0.70,
    coverage: float = 0.8,
    coverage_mode: int = 0,
    threads: int = 16,
    tmp_dir: str = None,
    verbose: bool = True
) -> str:
    """
    Run mmseqs2 easy-cluster.

    Args:
        fasta_file: Input FASTA file
        output_prefix: Output file prefix
        identity_threshold: Minimum sequence identity (0.0-1.0)
        coverage: Minimum coverage (0.0-1.0)
        coverage_mode: 0=query coverage, 1=target, 2=both
        threads: Number of threads
        tmp_dir: Temporary directory (auto-created if None)
        verbose: Print progress

    Returns:
        Path to cluster TSV file
    """
    if tmp_dir is None:
        tmp_dir = f"{output_prefix}_tmp"

    Path(tmp_dir).mkdir(parents=True, exist_ok=True)

    cmd = [
        MMSEQS_BIN, "easy-cluster",
        fasta_file,
        output_prefix,
        tmp_dir,
        "--min-seq-id", str(identity_threshold),
        "-c", str(coverage),
        "--cov-mode", str(coverage_mode),
        "--threads", str(threads),
    ]

    if verbose:
        print(f"Running mmseqs2 clustering...")
        print(f"  Input: {fasta_file}")
        print(f"  Output: {output_prefix}")
        print(f"  Identity: {identity_threshold*100:.0f}%")
        print(f"  Coverage: {coverage*100:.0f}%")
        print(f"  Threads: {threads}")
        print(f"  Command: {' '.join(cmd)}")
        print()

    result = subprocess.run(cmd, check=True, capture_output=not verbose, text=True)

    cluster_file = f"{output_prefix}_cluster.tsv"

    if verbose:
        print(f"\nmmseqs2 clustering complete!")
        print(f"Cluster file: {cluster_file}")

    return cluster_file


def run_cdhit_clustering(
    fasta_file: str,
    output_prefix: str,
    identity_threshold: float = 0.70,
    threads: int = 8,
    memory_mb: int = 16000,
    verbose: bool = True
) -> str:
    """
    Run CD-HIT clustering.

    Args:
        fasta_file: Input FASTA file
        output_prefix: Output file prefix
        identity_threshold: Minimum sequence identity (0.0-1.0)
        threads: Number of threads
        memory_mb: Memory limit in MB
        verbose: Print progress

    Returns:
        Path to cluster file (.clstr)
    """
    output_fasta = f"{output_prefix}.fasta"

    # Determine word length based on threshold
    # CD-HIT recommendations:
    # 0.7: n=5, 0.6: n=4, 0.5: n=3, 0.4: n=2
    if identity_threshold >= 0.7:
        word_length = 5
    elif identity_threshold >= 0.6:
        word_length = 4
    elif identity_threshold >= 0.5:
        word_length = 3
    else:
        word_length = 2

    cmd = [
        CDHIT_BIN,
        "-i", fasta_file,
        "-o", output_fasta,
        "-c", str(identity_threshold),
        "-n", str(word_length),
        "-M", str(memory_mb),
        "-T", str(threads),
        "-d", "0",  # Full sequence names in output
    ]

    if verbose:
        print(f"Running CD-HIT clustering...")
        print(f"  Input: {fasta_file}")
        print(f"  Output: {output_fasta}")
        print(f"  Identity: {identity_threshold*100:.0f}%")
        print(f"  Word length: {word_length}")
        print(f"  Threads: {threads}")
        print(f"  Memory: {memory_mb} MB")
        print(f"  Command: {' '.join(cmd)}")
        print()

    result = subprocess.run(cmd, check=True, capture_output=not verbose, text=True)

    cluster_file = f"{output_fasta}.clstr"

    if verbose:
        print(f"\nCD-HIT clustering complete!")
        print(f"Cluster file: {cluster_file}")

    return cluster_file


def generate_slurm_script(
    fasta_file: str,
    output_prefix: str,
    method: str,
    threshold: float,
    threads: int,
    memory_mb: int,
    partition: str,
    time_hours: int = 4
) -> str:
    """Generate SLURM submission script for clustering."""

    script_path = f"{output_prefix}_slurm.sh"
    log_path = f"{output_prefix}.out"
    err_path = f"{output_prefix}.err"

    # Build clustering command
    if method == "mmseqs2":
        cluster_cmd = f"""
{MMSEQS_BIN} easy-cluster \\
    {fasta_file} \\
    {output_prefix} \\
    {output_prefix}_tmp \\
    --min-seq-id {threshold} \\
    -c 0.8 \\
    --cov-mode 0 \\
    --threads {threads}
"""
    else:  # cd-hit
        word_length = 5 if threshold >= 0.7 else 4 if threshold >= 0.6 else 3
        cluster_cmd = f"""
{CDHIT_BIN} \\
    -i {fasta_file} \\
    -o {output_prefix}.fasta \\
    -c {threshold} \\
    -n {word_length} \\
    -M {memory_mb} \\
    -T {threads} \\
    -d 0
"""

    with open(script_path, 'w') as f:
        f.write(f"""#!/bin/bash
#SBATCH --job-name=cluster_{method}
#SBATCH --output={log_path}
#SBATCH --error={err_path}
#SBATCH --partition={partition}
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={threads}
#SBATCH --mem={memory_mb // 1000}G
#SBATCH --time={time_hours}:00:00

echo "Starting {method} clustering"
echo "Input: {fasta_file}"
echo "Output: {output_prefix}"
echo "Threshold: {threshold*100:.0f}%"
echo "Threads: {threads}"
echo "Started at: $(date)"
echo

{cluster_cmd}

echo
echo "Completed at: $(date)"
""")

    return script_path


def main():
    parser = argparse.ArgumentParser(
        description="Run sequence clustering with mmseqs2 or CD-HIT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Cluster with mmseqs2 (fast, recommended for large datasets)
    python scripts/run_clustering.py \\
        all_chains.fasta \\
        clustering_70pct \\
        --method mmseqs2 \\
        --threshold 0.70 \\
        --threads 32

    # Cluster with CD-HIT (traditional)
    python scripts/run_clustering.py \\
        all_chains.fasta \\
        clustering_70pct \\
        --method cd-hit \\
        --threshold 0.70 \\
        --threads 8

    # Submit to SLURM
    python scripts/run_clustering.py \\
        all_chains.fasta \\
        clustering_70pct \\
        --method mmseqs2 \\
        --submit \\
        --partition 96GB

Next steps after clustering:
    python scripts/load_clustering.py \\
        --cluster-file clustering_70pct_cluster.tsv \\
        --release-date 2025-10-21 \\
        --threshold 0.70 \\
        --method mmseqs2
        """
    )

    parser.add_argument("fasta_file", help="Input FASTA file")
    parser.add_argument("output_prefix", help="Output file prefix")

    parser.add_argument("--method", choices=['mmseqs2', 'cd-hit'],
                       default='mmseqs2',
                       help="Clustering method (default: mmseqs2)")

    parser.add_argument("--threshold", type=float, default=0.70,
                       help="Sequence identity threshold (default: 0.70)")

    parser.add_argument("--coverage", type=float, default=0.8,
                       help="Coverage threshold for mmseqs2 (default: 0.8)")

    parser.add_argument("--threads", type=int, default=16,
                       help="Number of threads (default: 16)")

    parser.add_argument("--memory", type=int, default=16000,
                       help="Memory in MB (default: 16000)")

    # SLURM options
    parser.add_argument("--submit", action="store_true",
                       help="Submit to SLURM instead of running directly")

    parser.add_argument("--partition", default="96GB",
                       help="SLURM partition (default: 96GB)")

    parser.add_argument("--time", type=int, default=4,
                       help="SLURM time limit in hours (default: 4)")

    parser.add_argument("--quiet", action="store_true",
                       help="Suppress progress output")

    args = parser.parse_args()

    # Validate inputs
    fasta_path = Path(args.fasta_file)
    if not fasta_path.exists():
        print(f"ERROR: FASTA file not found: {args.fasta_file}")
        return 1

    print("=" * 70)
    print(f"Sequence Clustering - {args.method.upper()}")
    print("=" * 70)
    print(f"Input: {args.fasta_file}")
    print(f"Output: {args.output_prefix}")
    print(f"Method: {args.method}")
    print(f"Threshold: {args.threshold*100:.0f}%")
    print(f"Threads: {args.threads}")
    print("=" * 70)
    print()

    if args.submit:
        # Generate and submit SLURM script
        script_path = generate_slurm_script(
            fasta_file=args.fasta_file,
            output_prefix=args.output_prefix,
            method=args.method,
            threshold=args.threshold,
            threads=args.threads,
            memory_mb=args.memory,
            partition=args.partition,
            time_hours=args.time
        )

        print(f"Generated SLURM script: {script_path}")
        print("Submitting to SLURM...")

        result = subprocess.run(
            ["sbatch", script_path],
            capture_output=True,
            text=True,
            check=True
        )

        job_id = result.stdout.strip().split()[-1]
        print(f"\n✓ Job submitted: {job_id}")
        print(f"  Monitor with: squeue -j {job_id}")
        print(f"  Logs: {args.output_prefix}.out / {args.output_prefix}.err")

    else:
        # Run clustering directly
        try:
            if args.method == "mmseqs2":
                cluster_file = run_mmseqs2_clustering(
                    fasta_file=args.fasta_file,
                    output_prefix=args.output_prefix,
                    identity_threshold=args.threshold,
                    coverage=args.coverage,
                    threads=args.threads,
                    verbose=not args.quiet
                )
            else:  # cd-hit
                cluster_file = run_cdhit_clustering(
                    fasta_file=args.fasta_file,
                    output_prefix=args.output_prefix,
                    identity_threshold=args.threshold,
                    threads=args.threads,
                    memory_mb=args.memory,
                    verbose=not args.quiet
                )

            print(f"\n{'=' * 70}")
            print("Clustering Complete!")
            print(f"{'=' * 70}")
            print(f"Cluster file: {cluster_file}")
            print()
            print("Next step: Load to database with:")
            print(f"  python scripts/load_clustering.py \\")
            print(f"    --cluster-file {cluster_file} \\")
            print(f"    --release-date YYYY-MM-DD \\")
            print(f"    --threshold {args.threshold} \\")
            print(f"    --method {args.method}")
            print()

        except subprocess.CalledProcessError as e:
            print(f"\nERROR: Clustering failed!")
            print(f"  {e}")
            return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
