#!/usr/bin/env python3
"""
Unit tests for BatchManifest class.
"""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from pyecod_prod.batch.manifest import BatchManifest


class TestBatchManifest:
    """Tests for BatchManifest"""

    def test_create_empty_manifest(self):
        """Test creating an empty manifest"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = BatchManifest(tmpdir)

            assert manifest.batch_dir == Path(tmpdir)
            assert "batch_info" in manifest.data
            assert "chains" in manifest.data
            assert "slurm_jobs" in manifest.data

    def test_initialize_batch(self):
        """Test batch initialization"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = BatchManifest(tmpdir)

            manifest.initialize_batch(
                batch_name="ecod_weekly_20251010",
                batch_type="weekly",
                release_date="2025-10-10",
                pdb_status_path="/usr2/pdb/data/status/20251010",
                reference_version="develop291",
            )

            batch_info = manifest.data["batch_info"]
            assert batch_info["batch_name"] == "ecod_weekly_20251010"
            assert batch_info["batch_type"] == "weekly"
            assert batch_info["reference_version"] == "develop291"

    def test_add_chain(self):
        """Test adding a chain to manifest"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = BatchManifest(tmpdir)

            manifest.add_chain(
                pdb_id="8abc",
                chain_id="A",
                sequence="MKTAYIAKQRQ",
                sequence_length=11,
                can_classify=True,
            )

            assert "8abc_A" in manifest.data["chains"]
            chain = manifest.data["chains"]["8abc_A"]
            assert chain["pdb_id"] == "8abc"
            assert chain["chain_id"] == "A"
            assert chain["sequence_length"] == 11
            assert chain["blast_status"] == "pending"

    def test_add_peptide_chain(self):
        """Test adding a non-classifiable peptide chain"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = BatchManifest(tmpdir)

            manifest.add_chain(
                pdb_id="8pep",
                chain_id="A",
                sequence="MKTAY",
                sequence_length=5,
                can_classify=False,
                cannot_classify_reason="peptide",
            )

            chain = manifest.data["chains"]["8pep_A"]
            assert chain["can_classify"] is False
            assert chain["cannot_classify_reason"] == "peptide"
            assert chain["blast_status"] == "not_needed"
            assert chain["partition_status"] == "not_needed"

    def test_mark_blast_complete(self):
        """Test marking BLAST as complete"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = BatchManifest(tmpdir)

            manifest.add_chain("8abc", "A", "MKTAYIAKQRQ", 11, True)

            manifest.mark_blast_complete(
                "8abc",
                "A",
                coverage=0.95,
                file_paths={
                    "chain_blast": "blast/8abc_A.chain_blast.xml",
                    "domain_blast": "blast/8abc_A.domain_blast.xml",
                },
            )

            chain = manifest.data["chains"]["8abc_A"]
            assert chain["blast_status"] == "complete"
            assert chain["blast_coverage"] == 0.95
            assert chain["needs_hhsearch"] is False  # coverage > 0.90
            assert "blast_complete_time" in chain

    def test_mark_blast_complete_low_coverage(self):
        """Test marking BLAST complete with low coverage triggers HHsearch"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = BatchManifest(tmpdir)

            manifest.add_chain("8abc", "A", "MKTAYIAKQRQ", 11, True)

            manifest.mark_blast_complete("8abc", "A", coverage=0.65)

            chain = manifest.data["chains"]["8abc_A"]
            assert chain["needs_hhsearch"] is True  # coverage < 0.90
            assert chain["hhsearch_status"] == "pending"
            assert manifest.data["processing_status"]["hhsearch_needed"] == 1

    def test_chains_needing_hhsearch(self):
        """Test getting chains that need HHsearch"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = BatchManifest(tmpdir)

            # Add chains with different coverage
            manifest.add_chain("8high", "A", "MKTAY", 5, True)
            manifest.add_chain("8low", "A", "MKTAY", 5, True)

            manifest.mark_blast_complete("8high", "A", coverage=0.95)
            manifest.mark_blast_complete("8low", "A", coverage=0.65)

            hhsearch_chains = manifest.chains_needing_hhsearch()

            assert len(hhsearch_chains) == 1
            assert hhsearch_chains[0]["pdb_id"] == "8low"

    def test_save_and_load(self):
        """Test saving and loading manifest"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and populate manifest
            manifest1 = BatchManifest(tmpdir)
            manifest1.initialize_batch(
                batch_name="test_batch",
                batch_type="weekly",
                release_date="2025-10-10",
                pdb_status_path="/test",
            )
            manifest1.add_chain("8abc", "A", "MKTAY", 5, True)
            manifest1.save()

            # Load manifest in new instance
            manifest2 = BatchManifest(tmpdir)

            assert manifest2.data["batch_info"]["batch_name"] == "test_batch"
            assert "8abc_A" in manifest2.data["chains"]

    def test_get_summary(self):
        """Test getting batch summary"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = BatchManifest(tmpdir)
            manifest.initialize_batch(
                batch_name="test_batch",
                batch_type="weekly",
                release_date="2025-10-10",
                pdb_status_path="/test",
            )

            # Add chains
            manifest.add_chain("8abc", "A", "MKTAY", 5, True)
            manifest.add_chain("8xyz", "B", "MKTAY", 5, True)

            # Mark one complete
            manifest.mark_blast_complete("8abc", "A", coverage=0.95)

            summary = manifest.get_summary()

            assert summary["total_chains"] == 2
            assert summary["blast_complete"] == "1/2"
            assert summary["blast_pct"] == 50.0

    def test_mark_partition_complete_with_version(self):
        """Test marking partition complete with algorithm version tracking"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = BatchManifest(tmpdir)

            manifest.add_chain("8abc", "A", "MKTAYIAKQRQ" * 20, 220, True)
            manifest.mark_blast_complete("8abc", "A", coverage=0.95)

            # Mark partition complete with version
            manifest.mark_partition_complete(
                "8abc",
                "A",
                partition_coverage=0.88,
                domain_count=2,
                partition_quality="good",
                file_paths={"partition": "partitions/8abc_A.partition.xml"},
                algorithm_version="2.0.0",
            )

            chain = manifest.data["chains"]["8abc_A"]

            assert chain["partition_status"] == "complete"
            assert chain["partition_coverage"] == 0.88
            assert chain["domain_count"] == 2
            assert chain["partition_quality"] == "good"
            assert chain["algorithm_version"] == "2.0.0"
            assert "partition_complete_time" in chain
            assert "partition" in chain["files"]

    def test_mark_partition_complete_without_version(self):
        """Test marking partition complete without algorithm version (backward compat)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = BatchManifest(tmpdir)

            manifest.add_chain("8abc", "A", "MKTAYIAKQRQ" * 20, 220, True)
            manifest.mark_blast_complete("8abc", "A", coverage=0.95)

            # Mark partition complete without version (should still work)
            manifest.mark_partition_complete(
                "8abc",
                "A",
                partition_coverage=0.75,
                domain_count=1,
                partition_quality="low_coverage",
            )

            chain = manifest.data["chains"]["8abc_A"]

            assert chain["partition_status"] == "complete"
            assert chain["partition_coverage"] == 0.75
            assert chain["domain_count"] == 1
            assert chain["partition_quality"] == "low_coverage"
            assert "algorithm_version" not in chain  # Not provided

    def test_partition_quality_values(self):
        """Test different partition quality values"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = BatchManifest(tmpdir)

            # Test all quality levels
            test_cases = [
                ("8good", "A", 0.90, 2, "good"),
                ("8low", "A", 0.65, 1, "low_coverage"),
                ("8frag", "A", 0.30, 1, "fragmentary"),
                ("8none", "A", 0.00, 0, "no_domains"),
            ]

            for pdb_id, chain_id, coverage, count, quality in test_cases:
                manifest.add_chain(pdb_id, chain_id, "M" * 200, 200, True)
                manifest.mark_blast_complete(pdb_id, chain_id, coverage=0.95)
                manifest.mark_partition_complete(
                    pdb_id,
                    chain_id,
                    partition_coverage=coverage,
                    domain_count=count,
                    partition_quality=quality,
                    algorithm_version="2.0.0",
                )

                chain_key = f"{pdb_id}_{chain_id}"
                assert manifest.data["chains"][chain_key]["partition_quality"] == quality


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
