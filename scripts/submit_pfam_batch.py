#!/usr/bin/env python3
"""
Submit Pfam hmmscan batch job for auto-accessioned domains.

This script:
1. Queries domain sequences from the database
2. Writes combined FASTA file
3. Splits into chunks for SLURM array processing
4. Submits the SLURM array job

Usage:
    # Dry run (preview without submitting)
    python scripts/submit_pfam_batch.py --dry-run

    # Submit job
    python scripts/submit_pfam_batch.py

    # With specific batch directory
    python scripts/submit_pfam_batch.py --batch-dir /data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026
"""

import sys
import os
import argparse
import logging
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple

import psycopg2

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database connection parameters
DEFAULT_CONNECTION_PARAMS = {
    'host': os.environ.get('ECOD_DB_HOST', 'dione'),
    'port': int(os.environ.get('ECOD_DB_PORT', '45000')),
    'user': os.environ.get('ECOD_DB_USER', 'ecod'),
    'password': os.environ.get('ECOD_DB_PASSWORD', ''),
    'dbname': os.environ.get('ECOD_DB_NAME', 'ecod_protein'),
}

DEFAULT_BATCH_DIR = Path("/data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026")
SLURM_SCRIPT = Path(__file__).parent / "run_pfam_hmmscan.slurm"


def get_connection(connection_params: Dict = None):
    """Get database connection."""
    params = connection_params or DEFAULT_CONNECTION_PARAMS
    return psycopg2.connect(**params)


def get_domain_sequences(conn, domain_version_pattern: str) -> List[Dict]:
    """
    Get domain sequences for Pfam scanning.

    Returns list of dicts with:
    - domain_id: ECOD domain ID (e.g., "e1suaA1")
    - ecod_uid: Numeric UID
    - domain_version: Domain version string
    - sequence: Domain sequence
    """
    cursor = conn.cursor()

    cursor.execute("""
        SELECT d.domain_id, d.ecod_uid, d.domain_version, ds.sequence
        FROM ecod_commons.domains d
        JOIN ecod_commons.domain_sequences ds ON d.id = ds.domain_id
        WHERE d.domain_version LIKE %s
        AND ds.sequence IS NOT NULL
        AND LENGTH(ds.sequence) > 0
        ORDER BY d.ecod_uid
    """, (domain_version_pattern,))

    results = []
    for domain_id, ecod_uid, domain_version, sequence in cursor:
        results.append({
            'domain_id': domain_id,
            'ecod_uid': ecod_uid,
            'domain_version': domain_version,
            'sequence': sequence
        })

    cursor.close()
    return results


def write_combined_fasta(sequences: List[Dict], output_path: Path) -> int:
    """
    Write sequences to combined FASTA file.

    Header format: >domain_id|ecod_uid|domain_version
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        f.write(f"# Domain sequences for Pfam v38.1 scanning\n")
        f.write(f"# Generated: {datetime.now().isoformat()}\n")
        f.write(f"# Sequences: {len(sequences)}\n")

        for seq in sequences:
            header = f">{seq['domain_id']}|{seq['ecod_uid']}|{seq['domain_version']}"
            f.write(f"{header}\n")

            # Write sequence in 80-character lines
            sequence = seq['sequence']
            for i in range(0, len(sequence), 80):
                f.write(sequence[i:i+80] + '\n')

    return len(sequences)


def split_fasta_into_chunks(input_fasta: Path, chunk_dir: Path,
                            seqs_per_chunk: int = 1000) -> int:
    """
    Split combined FASTA into chunks for SLURM array processing.

    Returns number of chunks created.
    """
    chunk_dir.mkdir(parents=True, exist_ok=True)

    # Count sequences first
    total_seqs = 0
    with open(input_fasta, 'r') as f:
        for line in f:
            if line.startswith('>'):
                total_seqs += 1

    num_chunks = (total_seqs + seqs_per_chunk - 1) // seqs_per_chunk
    logger.info(f"Splitting {total_seqs} sequences into {num_chunks} chunks of ~{seqs_per_chunk} sequences")

    # Split into chunks
    current_chunk = 0
    current_seqs = 0
    current_file = None

    with open(input_fasta, 'r') as f:
        for line in f:
            # Skip comment lines at start
            if line.startswith('#'):
                continue

            if line.startswith('>'):
                # New sequence
                if current_file is None or current_seqs >= seqs_per_chunk:
                    if current_file:
                        current_file.close()

                    chunk_path = chunk_dir / f"chunk_{current_chunk:04d}.fasta"
                    current_file = open(chunk_path, 'w')
                    current_chunk += 1
                    current_seqs = 0

                current_seqs += 1

            if current_file:
                current_file.write(line)

    if current_file:
        current_file.close()

    logger.info(f"Created {current_chunk} chunk files in {chunk_dir}")
    return current_chunk


def submit_slurm_job(batch_dir: Path, num_chunks: int, dry_run: bool = False) -> str:
    """
    Submit SLURM array job for Pfam scanning.

    Returns job ID.
    """
    # Change to batch directory for relative paths in SLURM script
    os.chdir(batch_dir)

    cmd = [
        'sbatch',
        f'--array=1-{num_chunks}',
        f'--export=ALL,BATCH_DIR={batch_dir}',
        str(SLURM_SCRIPT)
    ]

    logger.info(f"SLURM command: {' '.join(cmd)}")

    if dry_run:
        logger.info("DRY RUN - not submitting job")
        return "DRY_RUN"

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error(f"SLURM submission failed: {result.stderr}")
        raise RuntimeError(f"SLURM submission failed: {result.stderr}")

    # Parse job ID from sbatch output
    # Expected format: "Submitted batch job 12345"
    job_id = result.stdout.strip().split()[-1]
    logger.info(f"Submitted job {job_id}")

    return job_id


def main():
    parser = argparse.ArgumentParser(
        description="Submit Pfam hmmscan batch job for auto-accessioned domains"
    )
    parser.add_argument(
        "--batch-dir", type=Path, default=DEFAULT_BATCH_DIR,
        help=f"Batch directory (default: {DEFAULT_BATCH_DIR})"
    )
    parser.add_argument(
        "--domain-version-pattern", default="pyecod_prod_ecod_q4_2025_q1_2026%",
        help="Domain version pattern (LIKE syntax)"
    )
    parser.add_argument(
        "--seqs-per-chunk", type=int, default=1000,
        help="Sequences per chunk (default: 1000)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview without submitting job"
    )
    parser.add_argument(
        "--skip-fasta", action="store_true",
        help="Skip FASTA generation (use existing files)"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Pfam v38.1 Batch Submission")
    logger.info("=" * 60)
    logger.info(f"Batch directory: {args.batch_dir}")
    logger.info(f"Domain version pattern: {args.domain_version_pattern}")
    logger.info(f"Sequences per chunk: {args.seqs_per_chunk}")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'REAL RUN'}")
    logger.info("=" * 60)

    # Paths
    combined_fasta = args.batch_dir / "domains" / "all_domains.fasta"
    chunk_dir = args.batch_dir / "domains" / "chunks"

    if not args.skip_fasta:
        # Connect to database and get sequences
        logger.info("Connecting to database...")
        conn = get_connection()

        logger.info("Querying domain sequences...")
        sequences = get_domain_sequences(conn, args.domain_version_pattern)
        logger.info(f"Found {len(sequences)} sequences")

        if not sequences:
            logger.error("No sequences found! Check domain_version pattern.")
            conn.close()
            return 1

        conn.close()

        # Write combined FASTA
        logger.info(f"Writing combined FASTA to {combined_fasta}...")
        write_combined_fasta(sequences, combined_fasta)
    else:
        logger.info(f"Skipping FASTA generation, using existing {combined_fasta}")
        if not combined_fasta.exists():
            logger.error(f"Combined FASTA not found: {combined_fasta}")
            return 1

    # Split into chunks
    logger.info("Splitting into chunks...")
    num_chunks = split_fasta_into_chunks(combined_fasta, chunk_dir, args.seqs_per_chunk)

    # Submit SLURM job
    logger.info("Submitting SLURM job...")
    job_id = submit_slurm_job(args.batch_dir, num_chunks, dry_run=args.dry_run)

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)
    logger.info(f"Combined FASTA: {combined_fasta}")
    logger.info(f"Chunks created: {num_chunks}")
    logger.info(f"Chunk directory: {chunk_dir}")
    if job_id != "DRY_RUN":
        logger.info(f"Job ID: {job_id}")
        logger.info(f"Monitor with: squeue -j {job_id}")
        logger.info(f"Logs: {args.batch_dir}/slurm_logs/pfam_*.out")

    return 0


if __name__ == "__main__":
    sys.exit(main())
