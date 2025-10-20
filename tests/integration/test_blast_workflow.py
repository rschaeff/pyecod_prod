#!/usr/bin/env python3
"""
Integration test for BLAST-only workflow.

Tests the complete Phase 2 workflow:
1. Create batch structure
2. Add chains to manifest
3. Generate FASTA files
4. (Skip BLAST submission in test)
5. Process mock BLAST results
6. Generate summaries
7. Run partitioning (with pyecod-mini if available)
"""

import os
import tempfile
from pathlib import Path

import pytest

from pyecod_prod.batch.manifest import BatchManifest
from pyecod_prod.batch.weekly_batch import WeeklyBatch
from pyecod_prod.core.partition_runner import PartitionRunner
from pyecod_prod.core.summary_generator import SummaryGenerator
from pyecod_prod.utils.directories import BatchDirectories, write_fasta


class TestBlastWorkflow:
    """Integration tests for BLAST workflow"""

    @pytest.fixture
    def temp_batch_dir(self):
        """Create temporary batch directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_blast_xml(self):
        """Create mock BLAST XML for testing"""
        xml_content = """<?xml version="1.0"?>
<!DOCTYPE BlastOutput PUBLIC "-//NCBI//NCBI BlastOutput/EN" "http://www.ncbi.nlm.nih.gov/dtd/NCBI_BlastOutput.dtd">
<BlastOutput>
  <BlastOutput_program>blastp</BlastOutput_program>
  <BlastOutput_version>BLASTP 2.12.0+</BlastOutput_version>
  <BlastOutput_iterations>
    <Iteration>
      <Iteration_iter-num>1</Iteration_iter-num>
      <Iteration_query-ID>Query_1</Iteration_query-ID>
      <Iteration_query-def>test_chain</Iteration_query-def>
      <Iteration_query-len>250</Iteration_query-len>
      <Iteration_hits>
        <Hit>
          <Hit_num>1</Hit_num>
          <Hit_id>e2ia4A1</Hit_id>
          <Hit_def>e2ia4A1 test domain</Hit_def>
          <Hit_len>100</Hit_len>
          <Hit_hsps>
            <Hsp>
              <Hsp_num>1</Hsp_num>
              <Hsp_bit-score>200.5</Hsp_bit-score>
              <Hsp_evalue>1e-50</Hsp_evalue>
              <Hsp_query-from>10</Hsp_query-from>
              <Hsp_query-to>110</Hsp_query-to>
              <Hsp_hit-from>1</Hsp_hit-from>
              <Hsp_hit-to>95</Hsp_hit-to>
              <Hsp_align-len>101</Hsp_align-len>
              <Hsp_identity>85</Hsp_identity>
            </Hsp>
          </Hit_hsps>
        </Hit>
      </Iteration_hits>
    </Iteration>
  </BlastOutput_iterations>
</BlastOutput>
"""
        return xml_content

    def test_batch_directory_creation(self, temp_batch_dir):
        """Test creating batch directory structure"""
        dirs = BatchDirectories(temp_batch_dir)
        dirs.create_structure()

        assert dirs.batch_dir.exists()
        assert dirs.fastas_dir.exists()
        assert dirs.blast_dir.exists()
        assert dirs.summaries_dir.exists()
        assert dirs.partitions_dir.exists()

    def test_manifest_workflow(self, temp_batch_dir):
        """Test manifest creation and updates"""
        manifest = BatchManifest(temp_batch_dir)

        # Initialize batch
        manifest.initialize_batch(
            batch_name="test_batch",
            batch_type="weekly",
            release_date="2025-10-19",
            pdb_status_path="/test",
            reference_version="develop291",
        )

        # Add chain
        manifest.add_chain(
            pdb_id="8abc",
            chain_id="A",
            sequence="MKTAYIAKQRQ" * 20,  # 220 residues
            sequence_length=220,
            can_classify=True,
        )

        # Mark BLAST complete
        manifest.mark_blast_complete("8abc", "A", coverage=0.95)

        # Verify updates
        chain = manifest.data["chains"]["8abc_A"]
        assert chain["blast_status"] == "complete"
        assert chain["blast_coverage"] == 0.95
        assert chain["needs_hhsearch"] is False  # coverage > 0.90

    def test_summary_generation(self, temp_batch_dir, mock_blast_xml):
        """Test generating summary XML from BLAST results"""
        # Write mock BLAST XML
        blast_xml = Path(temp_batch_dir) / "test.blast.xml"
        with open(blast_xml, "w") as f:
            f.write(mock_blast_xml)

        # Generate summary (with empty family_lookup for testing)
        generator = SummaryGenerator(family_lookup={})
        test_sequence = "M" * 250
        summary_path = generator.generate_summary(
            pdb_id="8abc",
            chain_id="A",
            sequence=test_sequence,
            sequence_length=250,
            domain_blast_xml=str(blast_xml),
            output_path=str(Path(temp_batch_dir) / "summary.xml"),
        )

        assert Path(summary_path).exists()

        # Verify summary content
        with open(summary_path) as f:
            content = f.read()
            assert "domain_summary" in content
            assert "8abc" in content
            assert "e2ia4A1" in content

    def test_complete_workflow_no_blast(self, temp_batch_dir, mock_blast_xml):
        """Test complete workflow without BLAST submission"""
        # Create batch directories
        dirs = BatchDirectories(temp_batch_dir)
        dirs.create_structure()

        # Initialize manifest
        manifest = BatchManifest(temp_batch_dir)
        manifest.initialize_batch(
            batch_name="test_batch",
            batch_type="weekly",
            release_date="2025-10-19",
            pdb_status_path="/test",
        )

        # Add test chain
        test_sequence = "MKTAYIAKQRQ" * 20  # 220 residues
        manifest.add_chain(
            pdb_id="8abc",
            chain_id="A",
            sequence=test_sequence,
            sequence_length=len(test_sequence),
            can_classify=True,
        )

        # Generate FASTA
        fasta_path = dirs.get_fasta_path("8abc", "A")
        write_fasta(str(fasta_path), "8abc_A", test_sequence)

        # Create mock BLAST results
        domain_blast_path = dirs.get_domain_blast_path("8abc", "A")
        domain_blast_path.parent.mkdir(parents=True, exist_ok=True)
        with open(domain_blast_path, "w") as f:
            f.write(mock_blast_xml)

        chain_blast_path = dirs.get_chain_blast_path("8abc", "A")
        with open(chain_blast_path, "w") as f:
            f.write(mock_blast_xml)

        # Mark BLAST complete
        manifest.mark_blast_complete(
            "8abc",
            "A",
            coverage=0.95,
            file_paths={
                "chain_blast": dirs.get_relative_path(chain_blast_path),
                "domain_blast": dirs.get_relative_path(domain_blast_path),
            },
        )

        # Generate summary (with empty family_lookup for testing)
        generator = SummaryGenerator(family_lookup={})
        summary_path = dirs.get_summary_path("8abc", "A")
        summary_path.parent.mkdir(parents=True, exist_ok=True)

        generator.generate_summary(
            pdb_id="8abc",
            chain_id="A",
            sequence=test_sequence,
            sequence_length=len(test_sequence),
            chain_blast_xml=str(chain_blast_path),
            domain_blast_xml=str(domain_blast_path),
            output_path=str(summary_path),
        )

        manifest.update_chain_status(
            "8abc", "A", files={"summary": dirs.get_relative_path(summary_path)}
        )

        # Verify workflow
        assert fasta_path.exists()
        assert domain_blast_path.exists()
        assert summary_path.exists()

        # Verify manifest state
        chain = manifest.data["chains"]["8abc_A"]
        assert chain["blast_status"] == "complete"
        assert "summary" in chain["files"]

        # Print summary
        manifest.print_summary()


@pytest.mark.integration
class TestWeeklyBatchIntegration:
    """Integration tests requiring pyecod-mini"""

    def test_partition_runner_requires_pyecod_mini(self):
        """Test that PartitionRunner can be initialized"""
        # This test just verifies the class can be instantiated
        # Actual partitioning tests require pyecod-mini to be installed
        runner = PartitionRunner(pyecod_mini_path="pyecod-mini")
        assert runner.pyecod_mini_path == "pyecod-mini"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
