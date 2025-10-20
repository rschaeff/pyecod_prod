#!/usr/bin/env python3
"""
Weekly batch orchestrator for processing PDB updates.

Coordinates the complete workflow:
1. Parse PDB weekly update files
2. Extract chains and sequences
3. Submit BLAST jobs
4. Generate domain summaries
5. Run partitioning
6. Track status in manifest
"""

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pyecod_prod.batch.manifest import BatchManifest
from pyecod_prod.core.partition_runner import PartitionRunner
from pyecod_prod.core.summary_generator import SummaryGenerator
from pyecod_prod.parsers.pdb_status import PDBStatusParser
from pyecod_prod.slurm.blast_runner import BlastRunner
from pyecod_prod.slurm.hhsearch_runner import HHsearchRunner
from pyecod_prod.utils.directories import BatchDirectories, write_fasta
from pyecod_prod.utils.family_lookup import load_family_lookup_for_version


class WeeklyBatch:
    """
    Orchestrate weekly PDB update processing.

    This is the main entry point for processing a weekly batch of
    new PDB structures.
    """

    # Default base path for batches
    DEFAULT_BASE_PATH = "/data/ecod/pdb_updates/batches"

    def __init__(
        self,
        release_date: str,
        pdb_status_dir: str,
        base_path: str = DEFAULT_BASE_PATH,
        reference_version: str = "develop291",
    ):
        """
        Initialize weekly batch processor.

        Args:
            release_date: Release date (YYYY-MM-DD or YYYYMMDD)
            pdb_status_dir: Path to PDB status directory
            base_path: Base path for batch directories
            reference_version: ECOD reference version
        """
        # Normalize release date
        self.release_date = release_date.replace("-", "")  # YYYYMMDD format
        self.pdb_status_dir = pdb_status_dir
        self.reference_version = reference_version

        # Create batch name
        self.batch_name = f"ecod_weekly_{self.release_date}"

        # Setup batch directory
        self.batch_path = Path(base_path) / self.batch_name
        self.dirs = BatchDirectories(str(self.batch_path))

        # Initialize components
        self.pdb_parser = PDBStatusParser()
        self.blast_runner = BlastRunner(reference_version=reference_version)
        self.hhsearch_runner = HHsearchRunner(reference_version=reference_version)

        # Load family lookup for summary generation
        print(f"Loading ECOD family lookup for {reference_version}...")
        try:
            family_lookup = load_family_lookup_for_version(reference_version)
            print(f"  Loaded {len(family_lookup)} domain→family mappings")
        except FileNotFoundError as e:
            print(f"  WARNING: Family lookup not found: {e}")
            family_lookup = {}

        self.summary_generator = SummaryGenerator(
            reference_version=reference_version,
            family_lookup=family_lookup
        )

        # pyecod-mini path (installed in user's .local/bin)
        pyecod_mini_path = "/home/rschaeff/.local/bin/pyecod-mini"
        self.partition_runner = PartitionRunner(pyecod_mini_path=pyecod_mini_path)

        # Initialize or load manifest
        self.manifest = BatchManifest(str(self.batch_path))

    def create_batch(self):
        """Create batch directory structure and initialize manifest"""
        print(f"Creating batch: {self.batch_name}")

        # Create directory structure
        self.dirs.create_structure()

        # Initialize manifest
        self.manifest.initialize_batch(
            batch_name=self.batch_name,
            batch_type="weekly",
            release_date=self.release_date[:4]
            + "-"
            + self.release_date[4:6]
            + "-"
            + self.release_date[6:8],
            pdb_status_path=self.pdb_status_dir,
            reference_version=self.reference_version,
        )

        print(f"Batch directory: {self.batch_path}")

    def process_pdb_updates(self):
        """
        Process PDB weekly update files and extract chains.

        Returns:
            Dict with processing results
        """
        print(f"\nProcessing PDB weekly updates from: {self.pdb_status_dir}")

        # Parse PDB status files
        result = self.pdb_parser.process_weekly_release(self.pdb_status_dir)

        # Copy added.pdb for reference
        added_pdb = Path(self.pdb_status_dir) / "added.pdb"
        if added_pdb.exists():
            shutil.copy(added_pdb, self.batch_path / "pdb_entries.txt")

        # Add chains to manifest
        for chain in result["classifiable"]:
            self.manifest.add_chain(
                pdb_id=chain.pdb_id,
                chain_id=chain.chain_id,
                sequence=chain.sequence,
                sequence_length=chain.sequence_length,
                can_classify=True,
            )

        # Add non-classifiable chains
        for chain in result["peptides"]:
            self.manifest.add_chain(
                pdb_id=chain.pdb_id,
                chain_id=chain.chain_id,
                sequence=chain.sequence,
                sequence_length=chain.sequence_length,
                can_classify=False,
                cannot_classify_reason="peptide",
            )

        for chain in result["other"]:
            self.manifest.add_chain(
                pdb_id=chain.pdb_id,
                chain_id=chain.chain_id,
                sequence=chain.sequence,
                sequence_length=chain.sequence_length,
                can_classify=False,
                cannot_classify_reason=chain.cannot_classify_reason,
            )

        # Save manifest
        self.manifest.save()

        print(f"\nAdded {len(result['classifiable'])} classifiable chains to batch")
        print(f"Filtered out {len(result['peptides'])} peptides")
        print(f"Filtered out {len(result['other'])} other non-classifiable chains")

        return result

    def generate_fastas(self):
        """Generate FASTA files for all classifiable chains"""
        print(f"\nGenerating FASTA files...")

        count = 0
        for chain_key, chain_data in self.manifest.data["chains"].items():
            if not chain_data["can_classify"]:
                continue

            pdb_id = chain_data["pdb_id"]
            chain_id = chain_data["chain_id"]
            sequence = chain_data["sequence"]

            # Write FASTA
            fasta_path = self.dirs.get_fasta_path(pdb_id, chain_id)
            write_fasta(
                str(fasta_path),
                header=f"{pdb_id}_{chain_id}",
                sequence=sequence,
            )

            # Update manifest with file path
            rel_path = self.dirs.get_relative_path(fasta_path)
            self.manifest.update_chain_status(
                pdb_id, chain_id, files={"fasta": rel_path}
            )

            count += 1

        self.manifest.save()
        print(f"Generated {count} FASTA files")

    def run_blast(self, partition: str = "96GB", array_limit: int = 500, wait: bool = True):
        """
        Submit BLAST jobs for all chains.

        Args:
            partition: SLURM partition
            array_limit: Max concurrent array jobs
            wait: Wait for completion

        Returns:
            SLURM job ID
        """
        print(f"\nSubmitting BLAST jobs...")

        job_id = self.blast_runner.submit_blast_jobs(
            batch_dir=str(self.batch_path),
            fasta_dir=str(self.dirs.fastas_dir),
            output_dir=str(self.dirs.blast_dir),
            blast_type="both",  # Chain + domain
            partition=partition,
            array_limit=array_limit,
        )

        # Record job in manifest
        classifiable_chains = [
            key
            for key, data in self.manifest.data["chains"].items()
            if data["can_classify"]
        ]

        self.manifest.add_slurm_job(
            job_id=job_id,
            job_type="blast",
            chains=classifiable_chains,
            partition=partition,
        )
        self.manifest.save()

        if wait:
            print(f"Waiting for BLAST jobs to complete...")
            success = self.blast_runner.wait_for_completion(job_id, verbose=True)

            if success:
                self.manifest.mark_job_complete(job_id, status="completed")
            else:
                self.manifest.mark_job_complete(job_id, status="failed")

            self.manifest.save()

            return job_id, success
        else:
            return job_id, None

    def process_blast_results(self):
        """Process BLAST results and update coverage"""
        print(f"\nProcessing BLAST results...")

        processed = 0
        failed = 0

        for chain_key, chain_data in self.manifest.data["chains"].items():
            if not chain_data["can_classify"]:
                continue

            pdb_id = chain_data["pdb_id"]
            chain_id = chain_data["chain_id"]

            # Get BLAST file paths
            domain_blast_xml = self.dirs.get_domain_blast_path(pdb_id, chain_id)

            if not domain_blast_xml.exists():
                print(f"WARNING: BLAST results missing for {pdb_id}_{chain_id}")
                failed += 1
                continue

            # Parse coverage from domain BLAST
            try:
                coverage = self.blast_runner.parse_blast_coverage(str(domain_blast_xml))

                # Update manifest
                file_paths = {
                    "chain_blast": self.dirs.get_relative_path(
                        self.dirs.get_chain_blast_path(pdb_id, chain_id)
                    ),
                    "domain_blast": self.dirs.get_relative_path(domain_blast_xml),
                }

                self.manifest.mark_blast_complete(
                    pdb_id, chain_id, coverage=coverage, file_paths=file_paths
                )

                processed += 1

            except Exception as e:
                print(f"ERROR processing {pdb_id}_{chain_id}: {e}")
                failed += 1

        self.manifest.save()

        print(f"Processed BLAST results for {processed} chains")
        if failed > 0:
            print(f"WARNING: {failed} chains failed BLAST processing")

        # Report HHsearch needs
        hhsearch_chains = self.manifest.chains_needing_hhsearch()
        if hhsearch_chains:
            print(f"\n{len(hhsearch_chains)} chains need HHsearch (coverage < 90%)")

    def run_hhsearch(self, partition: str = "96GB", array_limit: int = 500, wait: bool = True):
        """
        Submit HHsearch jobs for chains with low BLAST coverage.

        Args:
            partition: SLURM partition
            array_limit: Max concurrent array jobs
            wait: Wait for completion

        Returns:
            SLURM job ID (or None if no chains need HHsearch)
        """
        # Get chains that need HHsearch
        hhsearch_chains = self.manifest.chains_needing_hhsearch()

        if not hhsearch_chains:
            print("\nNo chains need HHsearch (all have coverage >= 90%)")
            return None, None

        print(f"\nSubmitting HHsearch jobs for {len(hhsearch_chains)} chains...")

        # Create temporary FASTA directory for HHsearch-only chains
        hhsearch_fastas_dir = self.batch_path / "hhsearch_fastas"
        hhsearch_fastas_dir.mkdir(parents=True, exist_ok=True)

        # Copy FASTA files for chains needing HHsearch
        # Note: hhsearch_chains is a list of chain data dicts
        chain_keys = []
        for chain_data in hhsearch_chains:
            pdb_id = chain_data["pdb_id"]
            chain_id = chain_data["chain_id"]
            chain_key = f"{pdb_id}_{chain_id}"
            chain_keys.append(chain_key)

            source_fasta = self.dirs.get_fasta_path(pdb_id, chain_id)
            dest_fasta = hhsearch_fastas_dir / f"{pdb_id}_{chain_id}.fa"

            if source_fasta.exists():
                import shutil
                shutil.copy(source_fasta, dest_fasta)

        job_id = self.hhsearch_runner.submit_hhsearch_jobs(
            batch_dir=str(self.batch_path),
            fasta_dir=str(hhsearch_fastas_dir),
            output_dir=str(self.dirs.hhsearch_dir),
            partition=partition,
            array_limit=array_limit,
        )

        # Record job in manifest (need chain keys, not chain data dicts)
        self.manifest.add_slurm_job(
            job_id=job_id,
            job_type="hhsearch",
            chains=chain_keys,
            partition=partition,
        )
        self.manifest.save()

        if wait:
            print(f"Waiting for HHsearch jobs to complete...")
            success = self.hhsearch_runner.wait_for_completion(job_id, verbose=True)

            if success:
                self.manifest.mark_job_complete(job_id, status="completed")
            else:
                self.manifest.mark_job_complete(job_id, status="failed")

            self.manifest.save()

            return job_id, success
        else:
            return job_id, None

    def process_hhsearch_results(self):
        """Process HHsearch results and update coverage"""
        print(f"\nProcessing HHsearch results...")

        processed = 0
        failed = 0
        skipped = 0

        for chain_key, chain_data in self.manifest.data["chains"].items():
            # Only process chains that needed HHsearch
            if not chain_data.get("needs_hhsearch", False):
                skipped += 1
                continue

            if chain_data["hhsearch_status"] == "complete":
                skipped += 1
                continue

            pdb_id = chain_data["pdb_id"]
            chain_id = chain_data["chain_id"]

            # Get HHsearch file path
            hhsearch_hhr = self.dirs.hhsearch_dir / f"{pdb_id}_{chain_id}.hhr"

            if not hhsearch_hhr.exists():
                print(f"WARNING: HHsearch results missing for {pdb_id}_{chain_id}")
                failed += 1
                continue

            # Parse coverage from HHsearch
            try:
                coverage = self.hhsearch_runner.parse_hhsearch_coverage(str(hhsearch_hhr))

                # Update manifest
                file_paths = {
                    "hhsearch": self.dirs.get_relative_path(hhsearch_hhr),
                }

                self.manifest.mark_hhsearch_complete(
                    pdb_id, chain_id, file_paths=file_paths
                )

                processed += 1

            except Exception as e:
                print(f"ERROR processing {pdb_id}_{chain_id}: {e}")
                failed += 1

        self.manifest.save()

        print(f"Processed HHsearch results for {processed} chains")
        if skipped > 0:
            print(f"Skipped {skipped} chains (didn't need HHsearch)")
        if failed > 0:
            print(f"WARNING: {failed} chains failed HHsearch processing")

    def generate_summaries(self):
        """Generate domain summary XML files from BLAST and HHsearch results"""
        print(f"\nGenerating domain summaries...")

        generated = 0
        failed = 0

        for chain_key, chain_data in self.manifest.data["chains"].items():
            if chain_data["blast_status"] != "complete":
                continue

            pdb_id = chain_data["pdb_id"]
            chain_id = chain_data["chain_id"]
            sequence = chain_data["sequence"]
            seq_len = chain_data["sequence_length"]

            # Get BLAST file paths
            chain_blast_xml = str(self.dirs.get_chain_blast_path(pdb_id, chain_id))
            domain_blast_xml = str(self.dirs.get_domain_blast_path(pdb_id, chain_id))

            # Get HHsearch file path (if available)
            hhsearch_hhr = None
            if chain_data.get("hhsearch_status") == "complete":
                hhsearch_file = self.dirs.hhsearch_dir / f"{pdb_id}_{chain_id}.hhr"
                if hhsearch_file.exists():
                    hhsearch_hhr = str(hhsearch_file)

            summary_path = str(self.dirs.get_summary_path(pdb_id, chain_id))

            try:
                self.summary_generator.generate_summary(
                    pdb_id=pdb_id,
                    chain_id=chain_id,
                    sequence=sequence,
                    sequence_length=seq_len,
                    chain_blast_xml=chain_blast_xml,
                    domain_blast_xml=domain_blast_xml,
                    hhsearch_xml=hhsearch_hhr,
                    output_path=summary_path,
                    batch_id=self.batch_name,
                )

                # Update manifest
                rel_path = self.dirs.get_relative_path(Path(summary_path))
                self.manifest.update_chain_status(
                    pdb_id, chain_id, files={"summary": rel_path}
                )

                generated += 1

            except Exception as e:
                print(f"ERROR generating summary for {pdb_id}_{chain_id}: {e}")
                failed += 1

        self.manifest.save()

        print(f"Generated {generated} domain summaries")
        if failed > 0:
            print(f"WARNING: {failed} summaries failed")

    def run_partitioning(self):
        """Run pyecod-mini partitioning on all summaries"""
        print(f"\nRunning domain partitioning...")

        partitioned = 0
        failed = 0

        for chain_key, chain_data in self.manifest.data["chains"].items():
            summary_path = chain_data.get("files", {}).get("summary")
            if not summary_path:
                continue

            pdb_id = chain_data["pdb_id"]
            chain_id = chain_data["chain_id"]

            # Full summary path
            summary_full = self.batch_path / summary_path

            if not summary_full.exists():
                print(f"WARNING: Summary not found for {pdb_id}_{chain_id}")
                failed += 1
                continue

            try:
                result = self.partition_runner.partition(
                    summary_xml=str(summary_full),
                    output_dir=str(self.dirs.partitions_dir),
                    batch_id=self.batch_name,
                )

                if result.error_message:
                    print(f"ERROR partitioning {pdb_id}_{chain_id}: {result.error_message}")
                    failed += 1
                    continue

                # Update manifest
                partition_rel = self.dirs.get_relative_path(Path(result.partition_xml_path))

                self.manifest.mark_partition_complete(
                    pdb_id=pdb_id,
                    chain_id=chain_id,
                    partition_coverage=result.partition_coverage,
                    domain_count=result.domain_count,
                    partition_quality=result.partition_quality,
                    file_paths={"partition": partition_rel},
                )

                partitioned += 1

            except Exception as e:
                print(f"ERROR partitioning {pdb_id}_{chain_id}: {e}")
                failed += 1

        self.manifest.save()

        print(f"Partitioned {partitioned} chains")
        if failed > 0:
            print(f"WARNING: {failed} partitions failed")

    def run_complete_workflow(self, submit_blast: bool = True, submit_hhsearch: bool = True):
        """
        Run the complete weekly workflow.

        Args:
            submit_blast: Whether to submit BLAST jobs (False for testing)
            submit_hhsearch: Whether to submit HHsearch jobs for low-coverage chains
        """
        print("=" * 80)
        print(f"WEEKLY BATCH WORKFLOW: {self.batch_name}")
        print("=" * 80)

        # Step 1: Create batch
        self.create_batch()

        # Step 2: Process PDB updates
        self.process_pdb_updates()

        # Step 3: Generate FASTAs
        self.generate_fastas()

        if submit_blast:
            # Step 4: Run BLAST
            job_id, success = self.run_blast(wait=True)

            if not success:
                print("\nERROR: BLAST jobs failed. Stopping workflow.")
                return

            # Step 5: Process BLAST results
            self.process_blast_results()

            # Step 5b: Run HHsearch for low-coverage chains (Phase 3)
            if submit_hhsearch:
                hhsearch_job_id, hhsearch_success = self.run_hhsearch(wait=True)

                if hhsearch_job_id and not hhsearch_success:
                    print("\nWARNING: HHsearch jobs failed. Continuing with BLAST-only results.")
                elif hhsearch_job_id:
                    # Step 5c: Process HHsearch results
                    self.process_hhsearch_results()

        # Step 6: Generate summaries (includes both BLAST and HHsearch results)
        self.generate_summaries()

        # Step 7: Run partitioning
        self.run_partitioning()

        # Final summary
        print("\n" + "=" * 80)
        print("WORKFLOW COMPLETE")
        print("=" * 80)
        self.manifest.print_summary()


def main():
    """Command-line interface"""
    import argparse

    parser = argparse.ArgumentParser(description="Process weekly PDB updates")
    parser.add_argument("release_date", help="Release date (YYYYMMDD or YYYY-MM-DD)")
    parser.add_argument(
        "--status-dir",
        help="PDB status directory (default: /usr2/pdb/data/status/{release_date})",
    )
    parser.add_argument(
        "--base-path", default=WeeklyBatch.DEFAULT_BASE_PATH, help="Base path for batches"
    )
    parser.add_argument("--reference", default="develop291", help="Reference version")
    parser.add_argument("--no-blast", action="store_true", help="Skip BLAST submission (testing)")
    parser.add_argument("--resume", action="store_true", help="Resume existing batch")

    args = parser.parse_args()

    # Determine status directory
    release_normalized = args.release_date.replace("-", "")
    status_dir = args.status_dir or f"/usr2/pdb/data/status/{release_normalized}"

    # Create batch processor
    batch = WeeklyBatch(
        release_date=args.release_date,
        pdb_status_dir=status_dir,
        base_path=args.base_path,
        reference_version=args.reference,
    )

    if args.resume:
        print(f"Resuming batch: {batch.batch_name}")
        batch.manifest.print_summary()
        # Could add resume logic here
    else:
        # Run complete workflow
        batch.run_complete_workflow(submit_blast=not args.no_blast)


if __name__ == "__main__":
    main()
