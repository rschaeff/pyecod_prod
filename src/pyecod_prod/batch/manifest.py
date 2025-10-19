#!/usr/bin/env python3
"""
Batch manifest management using YAML files.

The manifest is the primary source of truth for batch state.
The database (if used) is synchronized from the manifest.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class BatchManifest:
    """
    Manage batch state via YAML manifest files.

    The manifest tracks:
    - Batch metadata (name, type, reference version)
    - Chain processing status (BLAST, HHsearch, partition)
    - File paths (relative to batch directory)
    - SLURM job tracking
    """

    def __init__(self, batch_dir: str):
        """
        Initialize or load a batch manifest.

        Args:
            batch_dir: Path to batch directory
        """
        self.batch_dir = Path(batch_dir)
        self.manifest_path = self.batch_dir / "batch_manifest.yaml"

        if self.manifest_path.exists():
            self.data = self._load()
        else:
            self.data = self._create_empty()

    def _load(self) -> Dict:
        """Load manifest from YAML file"""
        with open(self.manifest_path) as f:
            data = yaml.safe_load(f)

        if data is None:
            data = self._create_empty()

        return data

    def _create_empty(self) -> Dict:
        """Create empty manifest structure"""
        return {
            "batch_info": {},
            "processing_status": {
                "total_structures": 0,
                "blast_complete": 0,
                "hhsearch_needed": 0,
                "hhsearch_complete": 0,
                "partition_complete": 0,
            },
            "chains": {},
            "slurm_jobs": {},
        }

    def save(self):
        """Write manifest to disk"""
        # Ensure batch directory exists
        self.batch_dir.mkdir(parents=True, exist_ok=True)

        # Write YAML with nice formatting
        with open(self.manifest_path, "w") as f:
            yaml.dump(
                self.data,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

    def initialize_batch(
        self,
        batch_name: str,
        batch_type: str,
        release_date: str,
        pdb_status_path: str,
        reference_version: str = "develop291",
    ):
        """
        Initialize a new batch with metadata.

        Args:
            batch_name: Batch name (e.g., ecod_weekly_20251010)
            batch_type: 'weekly' or 'repair'
            release_date: Release date (YYYY-MM-DD)
            pdb_status_path: Path to PDB status directory
            reference_version: ECOD reference version
        """
        self.data["batch_info"] = {
            "batch_name": batch_name,
            "batch_type": batch_type,
            "release_date": release_date,
            "pdb_status_path": pdb_status_path,
            "reference_version": reference_version,
            "created": datetime.now().isoformat(),
        }

    def add_chain(
        self,
        pdb_id: str,
        chain_id: str,
        sequence: str,
        sequence_length: int,
        can_classify: bool = True,
        cannot_classify_reason: Optional[str] = None,
    ):
        """
        Add a chain to the manifest.

        Args:
            pdb_id: PDB ID
            chain_id: Chain ID
            sequence: Amino acid sequence
            sequence_length: Sequence length
            can_classify: Whether chain can be classified
            cannot_classify_reason: Reason if not classifiable
        """
        chain_key = f"{pdb_id}_{chain_id}"

        self.data["chains"][chain_key] = {
            "pdb_id": pdb_id,
            "chain_id": chain_id,
            "sequence": sequence,
            "sequence_length": sequence_length,
            "can_classify": can_classify,
            "cannot_classify_reason": cannot_classify_reason,
            # Processing status
            "blast_status": "pending" if can_classify else "not_needed",
            "blast_coverage": None,
            "needs_hhsearch": False,
            "hhsearch_status": "not_needed",
            "partition_status": "pending" if can_classify else "not_needed",
            # Files (will be populated as processing proceeds)
            "files": {},
        }

        # Update total count
        if can_classify:
            self.data["processing_status"]["total_structures"] += 1

    def update_chain_status(self, pdb_id: str, chain_id: str, **updates):
        """
        Update status fields for a chain.

        Args:
            pdb_id: PDB ID
            chain_id: Chain ID
            **updates: Key-value pairs to update
        """
        chain_key = f"{pdb_id}_{chain_id}"

        if chain_key not in self.data["chains"]:
            raise KeyError(f"Chain {chain_key} not found in manifest")

        # Update fields
        for key, value in updates.items():
            if key == "files":
                # Merge file paths
                self.data["chains"][chain_key]["files"].update(value)
            else:
                self.data["chains"][chain_key][key] = value

    def mark_blast_complete(
        self,
        pdb_id: str,
        chain_id: str,
        coverage: float,
        file_paths: Optional[Dict[str, str]] = None,
    ):
        """
        Mark BLAST as complete for a chain.

        Args:
            pdb_id: PDB ID
            chain_id: Chain ID
            coverage: Query coverage from BLAST (0.0-1.0)
            file_paths: Dict of file paths to add
        """
        chain_key = f"{pdb_id}_{chain_id}"

        updates = {
            "blast_status": "complete",
            "blast_coverage": coverage,
            "blast_complete_time": datetime.now().isoformat(),
        }

        # Determine if needs HHsearch (coverage < 90%)
        if coverage < 0.90:
            updates["needs_hhsearch"] = True
            updates["hhsearch_status"] = "pending"
            self.data["processing_status"]["hhsearch_needed"] += 1

        if file_paths:
            updates["files"] = file_paths

        self.update_chain_status(pdb_id, chain_id, **updates)
        self.data["processing_status"]["blast_complete"] += 1

    def mark_hhsearch_complete(
        self,
        pdb_id: str,
        chain_id: str,
        file_paths: Optional[Dict[str, str]] = None,
    ):
        """
        Mark HHsearch as complete for a chain.

        Args:
            pdb_id: PDB ID
            chain_id: Chain ID
            file_paths: Dict of file paths to add
        """
        updates = {
            "hhsearch_status": "complete",
            "hhsearch_complete_time": datetime.now().isoformat(),
        }

        if file_paths:
            updates["files"] = file_paths

        self.update_chain_status(pdb_id, chain_id, **updates)
        self.data["processing_status"]["hhsearch_complete"] += 1

    def mark_partition_complete(
        self,
        pdb_id: str,
        chain_id: str,
        partition_coverage: float,
        domain_count: int,
        partition_quality: str,
        file_paths: Optional[Dict[str, str]] = None,
    ):
        """
        Mark partitioning as complete for a chain.

        Args:
            pdb_id: PDB ID
            chain_id: Chain ID
            partition_coverage: Fraction covered by domains
            domain_count: Number of domains
            partition_quality: Quality assessment
            file_paths: Dict of file paths to add
        """
        updates = {
            "partition_status": "complete",
            "partition_coverage": partition_coverage,
            "domain_count": domain_count,
            "partition_quality": partition_quality,
            "partition_complete_time": datetime.now().isoformat(),
        }

        if file_paths:
            updates["files"] = file_paths

        self.update_chain_status(pdb_id, chain_id, **updates)
        self.data["processing_status"]["partition_complete"] += 1

    def chains_needing_hhsearch(self) -> List[Dict]:
        """
        Get list of chains that need HHsearch.

        Returns:
            List of chain data dicts
        """
        chains = []

        for chain_key, chain_data in self.data["chains"].items():
            if chain_data.get("needs_hhsearch") and chain_data.get("hhsearch_status") == "pending":
                chains.append(chain_data)

        return chains

    def chains_by_status(self, status_field: str, status_value: str) -> List[Dict]:
        """
        Get chains with a specific status.

        Args:
            status_field: Status field name (e.g., 'blast_status')
            status_value: Status value (e.g., 'failed')

        Returns:
            List of chain data dicts
        """
        chains = []

        for chain_key, chain_data in self.data["chains"].items():
            if chain_data.get(status_field) == status_value:
                chains.append(chain_data)

        return chains

    def add_slurm_job(
        self,
        job_id: str,
        job_type: str,
        chains: List[str],
        partition: str = "96GB",
    ):
        """
        Record a SLURM job in the manifest.

        Args:
            job_id: SLURM job ID
            job_type: Type of job ('blast', 'hhsearch', etc.)
            chains: List of chain keys (pdb_chain format)
            partition: SLURM partition used
        """
        self.data["slurm_jobs"][job_id] = {
            "job_id": job_id,
            "job_type": job_type,
            "chains": chains,
            "partition": partition,
            "submitted": datetime.now().isoformat(),
            "status": "running",
        }

    def mark_job_complete(self, job_id: str, status: str = "completed"):
        """
        Mark a SLURM job as complete.

        Args:
            job_id: SLURM job ID
            status: Final status ('completed' or 'failed')
        """
        if job_id not in self.data["slurm_jobs"]:
            raise KeyError(f"Job {job_id} not found in manifest")

        self.data["slurm_jobs"][job_id]["status"] = status
        self.data["slurm_jobs"][job_id]["completed"] = datetime.now().isoformat()

    def get_summary(self) -> Dict:
        """
        Get summary of batch processing status.

        Returns:
            Dict with summary statistics
        """
        status = self.data["processing_status"]
        batch_info = self.data["batch_info"]

        total = status["total_structures"]
        blast_done = status["blast_complete"]
        hhsearch_needed = status["hhsearch_needed"]
        hhsearch_done = status["hhsearch_complete"]
        partition_done = status["partition_complete"]

        return {
            "batch_name": batch_info.get("batch_name"),
            "batch_type": batch_info.get("batch_type"),
            "reference": batch_info.get("reference_version"),
            "created": batch_info.get("created"),
            "total_chains": total,
            "blast_complete": f"{blast_done}/{total}",
            "blast_pct": round(100.0 * blast_done / total, 1) if total > 0 else 0,
            "hhsearch_needed": hhsearch_needed,
            "hhsearch_complete": f"{hhsearch_done}/{hhsearch_needed}",
            "hhsearch_pct": (
                round(100.0 * hhsearch_done / hhsearch_needed, 1) if hhsearch_needed > 0 else 0
            ),
            "partition_complete": f"{partition_done}/{total}",
            "partition_pct": round(100.0 * partition_done / total, 1) if total > 0 else 0,
        }

    def print_summary(self):
        """Print human-readable summary"""
        summary = self.get_summary()

        print(f"\nBatch Summary: {summary['batch_name']}")
        print("=" * 60)
        print(f"Type: {summary['batch_type']}")
        print(f"Reference: {summary['reference']}")
        print(f"Created: {summary['created']}")
        print(f"\nTotal chains: {summary['total_chains']}")
        print(f"BLAST complete: {summary['blast_complete']} ({summary['blast_pct']}%)")
        print(f"HHsearch needed: {summary['hhsearch_needed']}")
        print(f"HHsearch complete: {summary['hhsearch_complete']} ({summary['hhsearch_pct']}%)")
        print(f"Partition complete: {summary['partition_complete']} ({summary['partition_pct']}%)")


def main():
    """Command-line interface for testing"""
    import argparse

    parser = argparse.ArgumentParser(description="Manage batch manifest files")
    parser.add_argument("batch_dir", help="Path to batch directory")
    parser.add_argument("--summary", action="store_true", help="Print batch summary")

    args = parser.parse_args()

    manifest = BatchManifest(args.batch_dir)

    if args.summary:
        manifest.print_summary()
    else:
        print(f"Loaded manifest from: {manifest.manifest_path}")
        print(f"Chains: {len(manifest.data['chains'])}")
        print(f"SLURM jobs: {len(manifest.data['slurm_jobs'])}")


if __name__ == "__main__":
    main()
