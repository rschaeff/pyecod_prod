#!/usr/bin/env python3
"""
Directory structure utilities for batch processing.

Provides helpers for creating and managing the standardized batch directory structure.
"""

from pathlib import Path
from typing import Optional


class BatchDirectories:
    """
    Manage standardized batch directory structure.

    Structure:
        batch_dir/
        ├── batch_manifest.yaml
        ├── pdb_entries.txt
        ├── fastas/
        ├── blast/
        ├── hhsearch/
        ├── summaries/
        ├── partitions/
        ├── slurm_logs/
        └── scripts/
    """

    def __init__(self, batch_dir: str):
        """
        Initialize batch directories.

        Args:
            batch_dir: Path to batch directory
        """
        self.batch_dir = Path(batch_dir)

        # Standard subdirectories
        self.fastas_dir = self.batch_dir / "fastas"
        self.blast_dir = self.batch_dir / "blast"
        self.hhsearch_dir = self.batch_dir / "hhsearch"
        self.summaries_dir = self.batch_dir / "summaries"
        self.partitions_dir = self.batch_dir / "partitions"
        self.slurm_logs_dir = self.batch_dir / "slurm_logs"
        self.scripts_dir = self.batch_dir / "scripts"

    def create_structure(self):
        """Create all standard subdirectories"""
        dirs_to_create = [
            self.batch_dir,
            self.fastas_dir,
            self.blast_dir,
            self.hhsearch_dir,
            self.summaries_dir,
            self.partitions_dir,
            self.slurm_logs_dir,
            self.scripts_dir,
        ]

        for directory in dirs_to_create:
            directory.mkdir(parents=True, exist_ok=True)

    def get_fasta_path(self, pdb_id: str, chain_id: str) -> Path:
        """Get path to FASTA file for a chain"""
        return self.fastas_dir / f"{pdb_id}_{chain_id}.fa"

    def get_chain_blast_path(self, pdb_id: str, chain_id: str) -> Path:
        """Get path to chain BLAST result"""
        return self.blast_dir / f"{pdb_id}_{chain_id}.chain_blast.xml"

    def get_domain_blast_path(self, pdb_id: str, chain_id: str) -> Path:
        """Get path to domain BLAST result"""
        return self.blast_dir / f"{pdb_id}_{chain_id}.domain_blast.xml"

    def get_hhsearch_a3m_path(self, pdb_id: str, chain_id: str) -> Path:
        """Get path to HHsearch MSA (a3m) file"""
        return self.hhsearch_dir / f"{pdb_id}_{chain_id}.a3m"

    def get_hhsearch_hhr_path(self, pdb_id: str, chain_id: str) -> Path:
        """Get path to HHsearch result (hhr) file"""
        return self.hhsearch_dir / f"{pdb_id}_{chain_id}.hhr"

    def get_hhsearch_xml_path(self, pdb_id: str, chain_id: str) -> Path:
        """Get path to HHsearch XML summary"""
        return self.hhsearch_dir / f"{pdb_id}_{chain_id}.hhsearch.xml"

    def get_summary_path(self, pdb_id: str, chain_id: str) -> Path:
        """Get path to domain summary XML"""
        return self.summaries_dir / f"{pdb_id}_{chain_id}.summary.xml"

    def get_partition_path(self, pdb_id: str, chain_id: str) -> Path:
        """Get path to domain partition XML"""
        return self.partitions_dir / f"{pdb_id}_{chain_id}.domains.xml"

    def get_relative_path(self, full_path: Path) -> str:
        """
        Get relative path from batch_dir.

        Args:
            full_path: Full path to file

        Returns:
            Relative path as string
        """
        try:
            return str(full_path.relative_to(self.batch_dir))
        except ValueError:
            # Not relative to batch_dir
            return str(full_path)

    def get_file_paths_dict(self, pdb_id: str, chain_id: str, relative: bool = True) -> dict:
        """
        Get dictionary of all standard file paths for a chain.

        Args:
            pdb_id: PDB ID
            chain_id: Chain ID
            relative: Return relative paths (default: True)

        Returns:
            Dict with file path keys
        """
        paths = {
            "fasta": self.get_fasta_path(pdb_id, chain_id),
            "chain_blast": self.get_chain_blast_path(pdb_id, chain_id),
            "domain_blast": self.get_domain_blast_path(pdb_id, chain_id),
            "hhsearch_a3m": self.get_hhsearch_a3m_path(pdb_id, chain_id),
            "hhsearch_hhr": self.get_hhsearch_hhr_path(pdb_id, chain_id),
            "hhsearch_xml": self.get_hhsearch_xml_path(pdb_id, chain_id),
            "summary": self.get_summary_path(pdb_id, chain_id),
            "partition": self.get_partition_path(pdb_id, chain_id),
        }

        if relative:
            return {key: self.get_relative_path(path) for key, path in paths.items()}
        else:
            return {key: str(path) for key, path in paths.items()}


def create_batch_directory(
    base_path: str,
    batch_name: str,
    create_subdirs: bool = True,
) -> BatchDirectories:
    """
    Create a new batch directory with standard structure.

    Args:
        base_path: Base path for batches (e.g., /data/ecod/pdb_updates/batches)
        batch_name: Batch name (e.g., ecod_weekly_20251010)
        create_subdirs: Create standard subdirectories

    Returns:
        BatchDirectories object
    """
    batch_dir = Path(base_path) / batch_name
    dirs = BatchDirectories(str(batch_dir))

    if create_subdirs:
        dirs.create_structure()

    return dirs


def write_fasta(fasta_path: str, header: str, sequence: str):
    """
    Write a FASTA file.

    Args:
        fasta_path: Path to FASTA file
        header: FASTA header (without ">")
        sequence: Amino acid sequence
    """
    with open(fasta_path, "w") as f:
        f.write(f">{header}\n")

        # Write sequence in 80-character lines
        for i in range(0, len(sequence), 80):
            f.write(sequence[i:i+80] + "\n")


def main():
    """Command-line interface for testing"""
    import argparse

    parser = argparse.ArgumentParser(description="Manage batch directory structure")
    parser.add_argument("batch_dir", help="Path to batch directory")
    parser.add_argument("--create", action="store_true", help="Create directory structure")
    parser.add_argument("--list", action="store_true", help="List structure")

    args = parser.parse_args()

    dirs = BatchDirectories(args.batch_dir)

    if args.create:
        dirs.create_structure()
        print(f"Created batch directory structure: {dirs.batch_dir}")

    if args.list:
        print(f"Batch directory: {dirs.batch_dir}")
        print(f"  fastas: {dirs.fastas_dir}")
        print(f"  blast: {dirs.blast_dir}")
        print(f"  hhsearch: {dirs.hhsearch_dir}")
        print(f"  summaries: {dirs.summaries_dir}")
        print(f"  partitions: {dirs.partitions_dir}")
        print(f"  slurm_logs: {dirs.slurm_logs_dir}")
        print(f"  scripts: {dirs.scripts_dir}")


if __name__ == "__main__":
    main()
