#!/usr/bin/env python3
"""
BLAST search runner with SLURM job submission.

Handles submission and monitoring of BLAST jobs on HPC cluster.
"""

import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class BlastRunner:
    """
    Run BLAST searches via SLURM job arrays.

    Submits parallel BLAST jobs for both chain and domain searches,
    monitors completion, and parses coverage from results.
    """

    # BLAST databases (v291)
    CHAIN_DB = "/data/ecod/database_versions/v291/chainwise100.develop291"
    DOMAIN_DB = "/data/ecod/database_versions/v291/ecod100.develop291"

    # BLAST parameters
    BLAST_EVALUE = 0.002
    BLAST_MAX_ALIGNMENTS = 5000
    BLAST_OUTFMT = 5  # XML format

    def __init__(
        self,
        reference_version: str = "develop291",
        chain_db: Optional[str] = None,
        domain_db: Optional[str] = None,
    ):
        """
        Initialize BLAST runner.

        Args:
            reference_version: ECOD reference version
            chain_db: Override default chain BLAST database
            domain_db: Override default domain BLAST database
        """
        self.reference_version = reference_version

        # Allow database override for testing
        self.chain_db = chain_db or self.CHAIN_DB
        self.domain_db = domain_db or self.DOMAIN_DB

        # Verify databases exist
        if not self._check_blast_db(self.chain_db):
            raise FileNotFoundError(f"Chain BLAST database not found: {self.chain_db}")
        if not self._check_blast_db(self.domain_db):
            raise FileNotFoundError(f"Domain BLAST database not found: {self.domain_db}")

    def _check_blast_db(self, db_path: str) -> bool:
        """Check if BLAST database files exist"""
        return Path(f"{db_path}.psq").exists()

    def create_blast_script(
        self,
        batch_dir: str,
        fasta_dir: str,
        output_dir: str,
        blast_type: str = "both",
        partition: str = "96GB",
        time_limit: str = "4:00:00",
        array_limit: int = 500,
    ) -> str:
        """
        Create SLURM script for BLAST job array.

        Args:
            batch_dir: Batch directory
            fasta_dir: Directory containing FASTA files
            output_dir: Directory for BLAST results
            blast_type: 'chain', 'domain', or 'both'
            partition: SLURM partition
            time_limit: Time limit per job

        Returns:
            Path to created script
        """
        batch_dir = Path(batch_dir)
        fasta_dir = Path(fasta_dir)
        output_dir = Path(output_dir)

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create scripts directory
        scripts_dir = batch_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        # Count FASTA files
        fasta_files = sorted(fasta_dir.glob("*.fa"))
        num_files = len(fasta_files)

        if num_files == 0:
            raise ValueError(f"No FASTA files found in {fasta_dir}")

        # Create file list for array indexing
        file_list = scripts_dir / "blast_files.txt"
        with open(file_list, "w") as f:
            for fasta_file in fasta_files:
                f.write(f"{fasta_file}\n")

        # Create SLURM script
        script_path = scripts_dir / f"blast_{blast_type}.sh"

        script_content = f"""#!/bin/bash
#SBATCH --job-name=blast_{blast_type}
#SBATCH --partition={partition}
#SBATCH --array=1-{num_files}%{array_limit}
#SBATCH --time={time_limit}
#SBATCH --mem=8G
#SBATCH --cpus-per-task=1
#SBATCH --output={batch_dir}/slurm_logs/blast_%A_%a.out
#SBATCH --error={batch_dir}/slurm_logs/blast_%A_%a.err

# Add BLAST to PATH
export PATH="/sw/apps/ncbi-blast-2.15.0+/bin:$PATH"

# Get FASTA file for this array task
FASTA_FILE=$(sed -n "${{SLURM_ARRAY_TASK_ID}}p" {file_list})
BASENAME=$(basename "$FASTA_FILE" .fa)

echo "Processing: $BASENAME"
echo "FASTA: $FASTA_FILE"

# Create output directory
mkdir -p {output_dir}

# Run chain BLAST
if [[ "{blast_type}" == "both" ]] || [[ "{blast_type}" == "chain" ]]; then
    CHAIN_OUT="{output_dir}/${{BASENAME}}.chain_blast.xml"
    echo "Running chain BLAST -> $CHAIN_OUT"

    blastp \\
        -query "$FASTA_FILE" \\
        -db {self.chain_db} \\
        -outfmt {self.BLAST_OUTFMT} \\
        -num_alignments {self.BLAST_MAX_ALIGNMENTS} \\
        -evalue {self.BLAST_EVALUE} \\
        -out "$CHAIN_OUT"

    if [ $? -ne 0 ]; then
        echo "ERROR: Chain BLAST failed for $BASENAME"
        exit 1
    fi
fi

# Run domain BLAST
if [[ "{blast_type}" == "both" ]] || [[ "{blast_type}" == "domain" ]]; then
    DOMAIN_OUT="{output_dir}/${{BASENAME}}.domain_blast.xml"
    echo "Running domain BLAST -> $DOMAIN_OUT"

    blastp \\
        -query "$FASTA_FILE" \\
        -db {self.domain_db} \\
        -outfmt {self.BLAST_OUTFMT} \\
        -num_alignments {self.BLAST_MAX_ALIGNMENTS} \\
        -evalue {self.BLAST_EVALUE} \\
        -out "$DOMAIN_OUT"

    if [ $? -ne 0 ]; then
        echo "ERROR: Domain BLAST failed for $BASENAME"
        exit 1
    fi
fi

echo "BLAST complete for $BASENAME"
"""

        with open(script_path, "w") as f:
            f.write(script_content)

        # Make executable
        os.chmod(script_path, 0o755)

        return str(script_path)

    def submit_blast_jobs(
        self,
        batch_dir: str,
        fasta_dir: str,
        output_dir: str,
        blast_type: str = "both",
        partition: str = "96GB",
        array_limit: int = 500,
    ) -> str:
        """
        Submit BLAST job array to SLURM.

        Args:
            batch_dir: Batch directory
            fasta_dir: Directory containing FASTA files
            output_dir: Directory for BLAST results
            blast_type: 'chain', 'domain', or 'both'
            partition: SLURM partition
            array_limit: Max concurrent array jobs

        Returns:
            SLURM job ID
        """
        # Create SLURM logs directory
        logs_dir = Path(batch_dir) / "slurm_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # Create script
        script_path = self.create_blast_script(
            batch_dir=batch_dir,
            fasta_dir=fasta_dir,
            output_dir=output_dir,
            blast_type=blast_type,
            partition=partition,
            array_limit=array_limit,
        )

        # Submit to SLURM with array limit
        # Format: --array=1-N%LIMIT means max LIMIT jobs running concurrently
        # Note: Don't override array range here, it's in the script
        cmd = ["sbatch", script_path]

        print(f"Submitting BLAST jobs: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"sbatch failed: {result.stderr}")

        # Extract job ID from output
        # Expected format: "Submitted batch job 12345678"
        match = re.search(r"Submitted batch job (\d+)", result.stdout)
        if not match:
            raise RuntimeError(f"Failed to parse job ID from: {result.stdout}")

        job_id = match.group(1)
        print(f"BLAST job submitted: {job_id}")

        return job_id

    def check_job_status(self, job_id: str) -> Dict[str, int]:
        """
        Check SLURM job array status.

        Args:
            job_id: SLURM job ID

        Returns:
            Dict with counts: {'running': N, 'pending': N, 'completed': N, 'failed': N}
        """
        cmd = ["squeue", "-j", job_id, "-h", "-o", "%T"]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            # Job not in queue - check sacct for completion
            return self._check_completed_job(job_id)

        # Count states
        states = {"RUNNING": 0, "PENDING": 0, "COMPLETED": 0, "FAILED": 0}

        for line in result.stdout.strip().split("\n"):
            state = line.strip()
            if state in states:
                states[state] += 1

        return {
            "running": states["RUNNING"],
            "pending": states["PENDING"],
            "completed": states["COMPLETED"],
            "failed": states["FAILED"],
        }

    def _check_completed_job(self, job_id: str) -> Dict[str, int]:
        """Check completed job status using sacct"""
        cmd = ["sacct", "-j", job_id, "--format=State", "--noheader", "--parsable2"]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return {"running": 0, "pending": 0, "completed": 0, "failed": 0}

        # Count states
        completed = 0
        failed = 0

        for line in result.stdout.strip().split("\n"):
            state = line.strip()
            if "COMPLETED" in state:
                completed += 1
            elif "FAILED" in state or "CANCELLED" in state:
                failed += 1

        return {"running": 0, "pending": 0, "completed": completed, "failed": failed}

    def wait_for_completion(
        self, job_id: str, poll_interval: int = 60, verbose: bool = True
    ) -> bool:
        """
        Wait for BLAST job to complete.

        Args:
            job_id: SLURM job ID
            poll_interval: Seconds between status checks
            verbose: Print status updates

        Returns:
            True if all jobs completed successfully, False if any failed
        """
        if verbose:
            print(f"Waiting for BLAST job {job_id} to complete...")

        while True:
            status = self.check_job_status(job_id)

            running = status["running"]
            pending = status["pending"]
            completed = status["completed"]
            failed = status["failed"]

            total = running + pending + completed + failed

            if verbose and total > 0:
                print(
                    f"  Status: {completed}/{total} completed, "
                    f"{running} running, {pending} pending, {failed} failed"
                )

            # Check if done
            if running == 0 and pending == 0:
                if failed > 0:
                    print(f"WARNING: {failed} jobs failed!")
                    return False
                else:
                    if verbose:
                        print(f"All {completed} BLAST jobs completed successfully!")
                    return True

            time.sleep(poll_interval)

    def parse_blast_coverage(self, blast_xml: str) -> float:
        """
        Parse query coverage from BLAST XML output.

        Args:
            blast_xml: Path to BLAST XML file

        Returns:
            Query coverage (0.0-1.0)
        """
        if not os.path.exists(blast_xml):
            raise FileNotFoundError(f"BLAST XML not found: {blast_xml}")

        try:
            tree = ET.parse(blast_xml)
            root = tree.getroot()

            # Get query length
            query_len_elem = root.find(".//Iteration_query-len")
            if query_len_elem is None:
                return 0.0

            query_len = int(query_len_elem.text)

            if query_len == 0:
                return 0.0

            # Track covered positions
            covered = set()

            # Iterate through all HSPs (high-scoring pairs)
            for hsp in root.findall(".//Hsp"):
                query_from = int(hsp.find("Hsp_query-from").text)
                query_to = int(hsp.find("Hsp_query-to").text)

                # Add positions to covered set
                for pos in range(query_from, query_to + 1):
                    covered.add(pos)

            # Calculate coverage
            coverage = len(covered) / query_len

            return coverage

        except Exception as e:
            print(f"Warning: Failed to parse {blast_xml}: {e}")
            return 0.0


def main():
    """Command-line interface for testing"""
    import argparse

    parser = argparse.ArgumentParser(description="Run BLAST searches via SLURM")
    parser.add_argument("batch_dir", help="Batch directory")
    parser.add_argument("--fasta-dir", default="fastas", help="FASTA directory (relative to batch)")
    parser.add_argument("--output-dir", default="blast", help="Output directory (relative to batch)")
    parser.add_argument("--blast-type", choices=["chain", "domain", "both"], default="both")
    parser.add_argument("--partition", default="96GB", help="SLURM partition")
    parser.add_argument("--submit", action="store_true", help="Submit jobs")
    parser.add_argument("--wait", action="store_true", help="Wait for completion")
    parser.add_argument("--check-coverage", help="Check coverage for BLAST XML file")

    args = parser.parse_args()

    runner = BlastRunner()

    if args.check_coverage:
        coverage = runner.parse_blast_coverage(args.check_coverage)
        print(f"Query coverage: {coverage:.1%}")

    elif args.submit:
        fasta_dir = Path(args.batch_dir) / args.fasta_dir
        output_dir = Path(args.batch_dir) / args.output_dir

        job_id = runner.submit_blast_jobs(
            batch_dir=args.batch_dir,
            fasta_dir=str(fasta_dir),
            output_dir=str(output_dir),
            blast_type=args.blast_type,
            partition=args.partition,
        )

        print(f"Job submitted: {job_id}")

        if args.wait:
            runner.wait_for_completion(job_id)


if __name__ == "__main__":
    main()
