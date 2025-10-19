#!/usr/bin/env python3
"""
Integration tests for HHsearch workflow.

Tests the Phase 3 HHsearch enhancement:
1. HHsearch result parsing
2. Summary generation with HHsearch
3. Two-pass workflow (BLAST → HHsearch)
"""

import os
import tempfile
from pathlib import Path

import pytest

from pyecod_prod.batch.manifest import BatchManifest
from pyecod_prod.core.summary_generator import SummaryGenerator
from pyecod_prod.parsers.hhsearch_parser import HHsearchParser


class TestHHsearchParser:
    """Tests for HHsearch HHR file parsing"""

    @pytest.fixture
    def mock_hhr_file(self):
        """Create mock HHR file for testing"""
        hhr_content = """Query         test_chain
Match_columns 250
No 1
 No Hit                             Prob E-value P-value  Score    SS Cols Query HMM  Template HMM
  1 e2ia4A1 2ia4.A.1-94            99.9 1.3E-30 1.9E-35  200.5   0.0  100    10-110      1-94 (94)
  2 e3kl8A1 3kl8.A.1-120           98.5 2.5E-25 3.2E-30  180.2   0.0   95    15-105     10-100 (120)
  3 e1abcA1 1abc.A.1-150           95.2 1.2E-20 1.5E-25  160.0   0.0   90    20-100     20-105 (150)

No 1
>e2ia4A1 2ia4.A.1-94
Probab=99.90  E-value=1.3e-30  Score=200.50  Aligned_cols=100  Identities=35%  Similarity=0.589  Sum_probs=0.0  Template_Neff=8.500

Q ss_pred           EEEEEEEE
Q test_chain    10 MKTAYIAK   17 (250)
Q Consensus     10 ~~~~~~~a   17 (250)
                  |||||||||
T Consensus      1 ~~~~~~~a    8 (94)
T e2ia4A1        1 MKTAYIAK    8 (94)
T ss_dssp           EEEEEEEE
T ss_pred           EEEEEEEE

No 2
>e3kl8A1 3kl8.A.1-120
Probab=98.50  E-value=2.5e-25  Score=180.20  Aligned_cols=95  Identities=30%  Similarity=0.520  Sum_probs=0.0  Template_Neff=7.200

Q ss_pred           EEEEEEEE
Q test_chain    15 IAKQRQEP   22 (250)
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.hhr', delete=False) as f:
            f.write(hhr_content)
            temp_path = f.name

        yield temp_path

        # Cleanup
        if os.path.exists(temp_path):
            os.remove(temp_path)

    def test_parse_hhr(self, mock_hhr_file):
        """Test parsing HHR file"""
        parser = HHsearchParser()
        hits = parser.parse_hhr(mock_hhr_file)

        # Should find 3 hits
        assert len(hits) == 3

        # Check first hit
        assert hits[0].hit_id == "e2ia4A1"
        assert hits[0].probability == 99.9
        assert abs(hits[0].evalue - 1.3e-30) < 1e-35
        assert hits[0].score == 200.5
        assert hits[0].query_range == "10-110"
        assert hits[0].template_range == "1-94"

        # Check second hit
        assert hits[1].hit_id == "e3kl8A1"
        assert hits[1].probability == 98.5

        # Check third hit
        assert hits[2].hit_id == "e1abcA1"
        assert hits[2].probability == 95.2

    def test_calculate_coverage(self, mock_hhr_file):
        """Test coverage calculation from HHR hits"""
        parser = HHsearchParser()
        hits = parser.parse_hhr(mock_hhr_file)

        # Query length is 250
        coverage = parser.calculate_coverage(hits, query_length=250)

        # Should cover positions 10-110 (101 positions)
        # Coverage = 101 / 250 = 0.404
        assert coverage > 0.4
        assert coverage < 0.45


class TestSummaryGeneratorWithHHsearch:
    """Tests for summary generation with HHsearch results"""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_blast_xml(self):
        """Create mock BLAST XML"""
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
          <Hit_id>e5xyzA1</Hit_id>
          <Hit_def>e5xyzA1 test domain</Hit_def>
          <Hit_len>100</Hit_len>
          <Hit_hsps>
            <Hsp>
              <Hsp_num>1</Hsp_num>
              <Hsp_bit-score>150.5</Hsp_bit-score>
              <Hsp_evalue>1e-40</Hsp_evalue>
              <Hsp_query-from>5</Hsp_query-from>
              <Hsp_query-to>105</Hsp_query-to>
              <Hsp_hit-from>1</Hsp_hit-from>
              <Hsp_hit-to>95</Hsp_hit-to>
              <Hsp_align-len>101</Hsp_align-len>
            </Hsp>
          </Hit_hsps>
        </Hit>
      </Iteration_hits>
    </Iteration>
  </BlastOutput_iterations>
</BlastOutput>
"""
        return xml_content

    @pytest.fixture
    def mock_hhr_content(self):
        """Create mock HHR content"""
        return """Query         test_chain
Match_columns 250
No 1
 No Hit                             Prob E-value P-value  Score    SS Cols Query HMM  Template HMM
  1 e2ia4A1 2ia4.A.1-94            99.9 1.3E-30 1.9E-35  200.5   0.0  100    110-210      1-94 (94)

No 1
>e2ia4A1 2ia4.A.1-94
Probab=99.90  E-value=1.3e-30  Score=200.50  Aligned_cols=100  Identities=35%  Similarity=0.589  Sum_probs=0.0  Template_Neff=8.500
"""

    def test_summary_with_hhsearch(self, temp_dir, mock_blast_xml, mock_hhr_content):
        """Test generating summary with both BLAST and HHsearch"""
        # Write mock files
        blast_xml = Path(temp_dir) / "test.blast.xml"
        with open(blast_xml, 'w') as f:
            f.write(mock_blast_xml)

        hhr_file = Path(temp_dir) / "test.hhr"
        with open(hhr_file, 'w') as f:
            f.write(mock_hhr_content)

        # Generate summary
        generator = SummaryGenerator()
        summary_path = generator.generate_summary(
            pdb_id="test",
            chain_id="A",
            sequence_length=250,
            domain_blast_xml=str(blast_xml),
            hhsearch_xml=str(hhr_file),
            output_path=str(Path(temp_dir) / "summary.xml"),
        )

        assert Path(summary_path).exists()

        # Verify summary contains both BLAST and HHsearch evidence
        with open(summary_path) as f:
            content = f.read()
            # Should have BLAST hit
            assert "e5xyzA1" in content
            assert "domain_blast" in content
            # Should have HHsearch hit
            assert "e2ia4A1" in content
            assert "hhsearch" in content
            assert "probability" in content


class TestTwoPassWorkflow:
    """Integration tests for two-pass workflow"""

    @pytest.fixture
    def temp_batch_dir(self):
        """Create temporary batch directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_manifest_tracks_hhsearch_needs(self, temp_batch_dir):
        """Test that manifest correctly identifies chains needing HHsearch"""
        manifest = BatchManifest(temp_batch_dir)

        # Initialize batch
        manifest.initialize_batch(
            batch_name="test_batch",
            batch_type="weekly",
            release_date="2025-10-19",
            pdb_status_path="/test",
        )

        # Add chains with different BLAST coverage
        manifest.add_chain(
            pdb_id="high",
            chain_id="A",
            sequence="M" * 100,
            sequence_length=100,
            can_classify=True,
        )

        manifest.add_chain(
            pdb_id="low",
            chain_id="A",
            sequence="M" * 100,
            sequence_length=100,
            can_classify=True,
        )

        # Mark BLAST complete with different coverage
        manifest.mark_blast_complete("high", "A", coverage=0.95)  # >= 90%, no HHsearch needed
        manifest.mark_blast_complete("low", "A", coverage=0.75)   # < 90%, needs HHsearch

        # Check HHsearch needs
        hhsearch_chains = manifest.chains_needing_hhsearch()

        assert len(hhsearch_chains) == 1
        # chains_needing_hhsearch() returns list of chain data dicts
        assert hhsearch_chains[0]["pdb_id"] == "low"
        assert hhsearch_chains[0]["chain_id"] == "A"

        # Verify flags
        assert manifest.data["chains"]["high_A"]["needs_hhsearch"] is False
        assert manifest.data["chains"]["low_A"]["needs_hhsearch"] is True

    def test_hhsearch_completion_tracking(self, temp_batch_dir):
        """Test tracking HHsearch completion in manifest"""
        manifest = BatchManifest(temp_batch_dir)

        manifest.initialize_batch(
            batch_name="test_batch",
            batch_type="weekly",
            release_date="2025-10-19",
            pdb_status_path="/test",
        )

        manifest.add_chain(
            pdb_id="test",
            chain_id="A",
            sequence="M" * 100,
            sequence_length=100,
            can_classify=True,
        )

        # Mark BLAST complete with low coverage
        manifest.mark_blast_complete("test", "A", coverage=0.75)

        # Verify needs HHsearch
        assert manifest.data["chains"]["test_A"]["needs_hhsearch"] is True
        assert manifest.data["chains"]["test_A"]["hhsearch_status"] == "pending"

        # Mark HHsearch complete
        manifest.mark_hhsearch_complete(
            "test", "A",
            file_paths={"hhsearch": "hhsearch/test_A.hhr"}
        )

        # Verify updated
        assert manifest.data["chains"]["test_A"]["hhsearch_status"] == "complete"
        assert "hhsearch" in manifest.data["chains"]["test_A"]["files"]


class TestHHsearchRunner:
    """Tests for HHsearchRunner (without actual SLURM submission)"""

    def test_runner_initialization(self):
        """Test that HHsearchRunner can be initialized"""
        # This will fail if database doesn't exist, but that's expected in test env
        try:
            from pyecod_prod.slurm.hhsearch_runner import HHsearchRunner
            # Try to initialize with test database path
            runner = HHsearchRunner(hhsearch_db="/tmp/test_db")
        except FileNotFoundError as e:
            # Expected if database doesn't exist
            assert "HHsearch database not found" in str(e)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
