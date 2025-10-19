#!/usr/bin/env python3
"""
HHsearch runner with SLURM job submission.

Handles submission and monitoring of HHsearch jobs for chains
with low BLAST coverage (<90%).
"""

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

class HHsearchRunner:
    """
    Run HHsearch via SLURM job arrays.

    HHsearch is used as a second pass for chains with low BLAST coverage,
    providing more sensitive profile-to-profile searches.
    """

    # HHsearch database (v291)
    HHSEARCH_DB = "/data/ecod/database_versions/v291/ecod_v291_hhm"

    # HHsearch parameters
    HHSEARCH_EVALUE = 0.001
    HHSEARCH_MIN_PROB = 50  # Minimum probability threshold
    HHSEARCH_MAX_HITS = 5000

    def __init__(
        self,
        reference_version: str = "develop291",
        hhsearch_db: Optional[str] = None,
    ):
        """
        Initialize HHsearch runner.

        Args:
            reference_version: ECOD reference version
            hhsearch_db: Override default HHsearch database
        """
        self.reference_version = reference_version

        # Allow database override for testing
        self.hhsearch_db = hhsearch_db or self.HHSEARCH_DB

        # Verify database exists
        if not self._check_hhsearch_db(self.hhsearch_db):
            raise FileNotFoundError(f"HHsearch database not found: {self.hhsearch_db}")

    def _check_hhsearch_db(self, db_path: str) -> bool:
        """Check if HHsearch database files exist"""
        # HH-suite3 uses .ffdata and .ffindex files
        return Path(f"{db_path}.ffdata").exists() and Path(f"{db_path}.ffindex").exists()

    def create_hhsearch_script(
        self,
        batch_dir: str,
        fasta_dir: str,
        output_dir: str,
        partition: str = "96GB",
        time_limit: str = "8:00:00",
    ) -> str:
        """
        Create SLURM script for HHsearch job array.

        Args:
            batch_dir: Batch directory
            fasta_dir: Directory containing FASTA files
            output_dir: Directory for HHsearch results
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
        file_list = scripts_dir / "hhsearch_files.txt"
        with open(file_list, "w") as f:
            for fasta_file in fasta_files:
                f.write(f"{fasta_file}\n")

        # Create SLURM script
        script_path = scripts_dir / "hhsearch.sh"

        script_content = f"""#!/bin/bash
#SBATCH --job-name=hhsearch
#SBATCH --partition={partition}
#SBATCH --array=1-{num_files}
#SBATCH --time={time_limit}
#SBATCH --mem=16G
#SBATCH --cpus-per-task=4
#SBATCH --output={batch_dir}/slurm_logs/hhsearch_%A_%a.out
#SBATCH --error={batch_dir}/slurm_logs/hhsearch_%A_%a.err

# Load HH-suite module (adjust for your cluster)
# module load hh-suite

# Get FASTA file for this array task
FASTA_FILE=$(sed -n "${{SLURM_ARRAY_TASK_ID}}p" {file_list})
BASENAME=$(basename "$FASTA_FILE" .fa)

echo "Processing: $BASENAME"
echo "FASTA: $FASTA_FILE"

# Create output directory
mkdir -p {output_dir}

# HHsearch output
HHSEARCH_OUT="{output_dir}/${{BASENAME}}.hhr"

echo "Running HHsearch -> $HHSEARCH_OUT"

# Run HHsearch
hhsearch \\
    -i "$FASTA_FILE" \\
    -d {self.hhsearch_db} \\
    -o "$HHSEARCH_OUT" \\
    -e {self.HHSEARCH_EVALUE} \\
    -p {self.HHSEARCH_MIN_PROB} \\
    -n {self.HHSEARCH_MAX_HITS} \\
    -cpu ${{SLURM_CPUS_PER_TASK}} \\
    -v 2

if [ $? -ne 0 ]; then
    echo "ERROR: HHsearch failed for $BASENAME"
    exit 1
fi

echo "HHsearch complete for $BASENAME"
"""

        with open(script_path, "w") as f:
            f.write(script_content)

        # Make executable
        os.chmod(script_path, 0o755)

        return str(script_path)

    def submit_hhsearch_jobs(
        self,
        batch_dir: str,
        fasta_dir: str,
        output_dir: str,
        partition: str = "96GB",
        array_limit: int = 500,
    ) -> str:
        """
        Submit HHsearch job array to SLURM.

        Args:
            batch_dir: Batch directory
            fasta_dir: Directory containing FASTA files
            output_dir: Directory for HHsearch results
            partition: SLURM partition
            array_limit: Max concurrent array jobs

        Returns:
            SLURM job ID
        """
        # Create SLURM logs directory
        logs_dir = Path(batch_dir) / "slurm_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # Create script
        script_path = self.create_hhsearch_script(
            batch_dir=batch_dir,
            fasta_dir=fasta_dir,
            output_dir=output_dir,
            partition=partition,
        )

        # Submit to SLURM with array limit
        cmd = ["sbatch", f"--array=%{array_limit}", script_path]

        print(f"Submitting HHsearch jobs: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"sbatch failed: {result.stderr}")

        # Extract job ID from output
        match = re.search(r"Submitted batch job (\d+)", result.stdout)
        if not match:
            raise RuntimeError(f"Failed to parse job ID from: {result.stdout}")

        job_id = match.group(1)
        print(f"HHsearch job submitted: {job_id}")

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
        Wait for HHsearch job to complete.

        Args:
            job_id: SLURM job ID
            poll_interval: Seconds between status checks
            verbose: Print status updates

        Returns:
            True if all jobs completed successfully, False if any failed
        """
        if verbose:
            print(f"Waiting for HHsearch job {job_id} to complete...")

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
                        print(f"All {completed} HHsearch jobs completed successfully!")
                    return True

            time.sleep(poll_interval)

    def parse_hhsearch_coverage(self, hhr_file: str) -> float:
        """
        Parse query coverage from HHsearch HHR output.

        Args:
            hhr_file: Path to HHR file

        Returns:
            Query coverage (0.0-1.0)
        """
        if not os.path.exists(hhr_file):
            raise FileNotFoundError(f"HHR file not found: {hhr_file}")

        try:
            query_len = None
            covered = set()

            with open(hhr_file) as f:
                for line in f:
                    # Extract query length from Match_columns line
                    if line.startswith("Match_columns"):
                        match = re.search(r"Match_columns\s+(\d+)", line)
                        if match:
                            query_len = int(match.group(1))

                    # Parse alignment regions
                    # Format: "Q ss_pred           10 EEEEEEEE   17 (220)"
                    if line.startswith("Q ") and "(" in line:
                        parts = line.split()
                        if len(parts) >= 4:
                            try:
                                start = int(parts[2])
                                end = int(parts[4])
                                for pos in range(start, end + 1):
                                    covered.add(pos)
                            except (ValueError, IndexError):
                                continue

            if query_len and query_len > 0:
                coverage = len(covered) / query_len
                return coverage
            else:
                return 0.0

        except Exception as e:
            print(f"Warning: Failed to parse {hhr_file}: {e}")
            return 0.0


def main():
    """Command-line interface for testing"""
    import argparse

    parser = argparse.ArgumentParser(description="Run HHsearch via SLURM")
    parser.add_argument("batch_dir", help="Batch directory")
    parser.add_argument("--fasta-dir", default="fastas", help="FASTA directory (relative to batch)")
    parser.add_argument("--output-dir", default="hhsearch", help="Output directory (relative to batch)")
    parser.add_argument("--partition", default="96GB", help="SLURM partition")
    parser.add_argument("--submit", action="store_true", help="Submit jobs")
    parser.add_argument("--wait", action="store_true", help="Wait for completion")
    parser.add_argument("--check-coverage", help="Check coverage for HHR file")

    args = parser.parse_args()

    runner = HHsearchRunner()

    if args.check_coverage:
        coverage = runner.parse_hhsearch_coverage(args.check_coverage)
        print(f"Query coverage: {coverage:.1%}")

    elif args.submit:
        fasta_dir = Path(args.batch_dir) / args.fasta_dir
        output_dir = Path(args.batch_dir) / args.output_dir

        job_id = runner.submit_hhsearch_jobs(
            batch_dir=args.batch_dir,
            fasta_dir=str(fasta_dir),
            output_dir=str(output_dir),
            partition=args.partition,
        )

        print(f"Job submitted: {job_id}")

        if args.wait:
            runner.wait_for_completion(job_id)


if __name__ == "__main__":
    main()
