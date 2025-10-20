#!/usr/bin/env python3
"""
Unit tests for PartitionRunner.

Tests library API integration, CLI fallback, and version tracking
added in October 2025 refactor.
"""

import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import pytest

from pyecod_prod.core.partition_runner import PartitionRunner, LIBRARY_AVAILABLE


class TestPartitionRunnerInitialization:
    """Test PartitionRunner initialization and configuration"""

    def test_library_detection(self):
        """Test that LIBRARY_AVAILABLE is correctly set"""
        # This will be True if pyecod_mini is installed
        assert isinstance(LIBRARY_AVAILABLE, bool)

    def test_init_with_library_available(self):
        """Test initialization when library is available"""
        if not LIBRARY_AVAILABLE:
            pytest.skip("pyecod_mini library not installed")

        runner = PartitionRunner(use_library=True)
        assert runner.use_library is True

    def test_init_force_cli(self):
        """Test forcing CLI usage even when library available"""
        runner = PartitionRunner(use_library=False)
        assert runner.use_library is False

    def test_init_custom_path(self):
        """Test initialization with custom CLI path"""
        runner = PartitionRunner(pyecod_mini_path="/custom/path/pyecod-mini")
        assert runner.pyecod_mini_path == "/custom/path/pyecod-mini"


class TestQualityAssessment:
    """Test ECOD-specific quality assessment"""

    def test_assess_good_quality(self):
        """Test quality assessment: good (>= 80% coverage)"""
        runner = PartitionRunner()

        quality = runner._assess_ecod_quality(
            domain_count=2,
            coverage=0.85,
            sequence_length=200
        )
        assert quality == "good"

        quality = runner._assess_ecod_quality(
            domain_count=1,
            coverage=0.80,  # Exactly 80%
            sequence_length=150
        )
        assert quality == "good"

    def test_assess_low_coverage(self):
        """Test quality assessment: low_coverage (50-80%)"""
        runner = PartitionRunner()

        quality = runner._assess_ecod_quality(
            domain_count=1,
            coverage=0.65,
            sequence_length=200
        )
        assert quality == "low_coverage"

        quality = runner._assess_ecod_quality(
            domain_count=2,
            coverage=0.50,  # Exactly 50%
            sequence_length=150
        )
        assert quality == "low_coverage"

    def test_assess_fragmentary(self):
        """Test quality assessment: fragmentary (< 50%)"""
        runner = PartitionRunner()

        quality = runner._assess_ecod_quality(
            domain_count=1,
            coverage=0.30,
            sequence_length=200
        )
        assert quality == "fragmentary"

        quality = runner._assess_ecod_quality(
            domain_count=2,
            coverage=0.10,
            sequence_length=150
        )
        assert quality == "fragmentary"

    def test_assess_no_domains(self):
        """Test quality assessment: no_domains"""
        runner = PartitionRunner()

        quality = runner._assess_ecod_quality(
            domain_count=0,
            coverage=0.0,
            sequence_length=200
        )
        assert quality == "no_domains"


class TestSummaryMetadataParsing:
    """Test parsing metadata from summary XML"""

    @pytest.fixture
    def mock_summary_xml(self):
        """Create mock summary XML"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write("""<?xml version="1.0"?>
<domain_summary version="1.0">
  <protein pdb_id="8abc" chain_id="A" length="250">
    <sequence>MKTAYIAKQRQ</sequence>
  </protein>
  <evidence>
    <hit type="domain_blast" target="e2ia4A1" target_family="Ras-like GTPase"
         evalue="1.00e-50" bitscore="200.5" identity="0.85"
         coverage="0.95" query_range="10-110" target_range="1-95"/>
  </evidence>
  <metadata>
    <batch_id>test_batch</batch_id>
    <timestamp>2025-10-19T12:00:00Z</timestamp>
  </metadata>
</domain_summary>""")
            temp_path = f.name

        yield temp_path

        if os.path.exists(temp_path):
            os.unlink(temp_path)

    def test_parse_summary_metadata(self, mock_summary_xml):
        """Test parsing PDB ID, chain ID, and length from summary XML"""
        runner = PartitionRunner()

        pdb_id, chain_id, seq_len = runner._parse_summary_metadata(mock_summary_xml)

        assert pdb_id == "8abc"
        assert chain_id == "A"
        assert seq_len == 250


class TestPartitionXMLParsing:
    """Test parsing partition XML output"""

    @pytest.fixture
    def mock_partition_xml(self):
        """Create mock partition XML with version tracking"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write("""<?xml version="1.0"?>
<partition algorithm_version="2.0.0">
  <protein pdb_id="8abc" chain_id="A" length="250">
    <coverage>0.88</coverage>
    <domains>
      <domain id="e8abcA1" range="10-110" size="101"
              source="domain_blast" family="Ras-like GTPase" confidence="0.95"/>
      <domain id="e8abcA2" range="150-250" size="101"
              source="domain_blast" family="GFP-like" confidence="0.89"/>
    </domains>
  </protein>
</partition>""")
            temp_path = f.name

        yield temp_path

        if os.path.exists(temp_path):
            os.unlink(temp_path)

    def test_parse_partition_xml(self, mock_partition_xml):
        """Test parsing domains, coverage, and version from partition XML"""
        runner = PartitionRunner()

        domains, coverage, algo_version = runner._parse_partition_xml(mock_partition_xml)

        assert len(domains) == 2
        assert coverage == 0.88
        assert algo_version == "2.0.0"

        # Verify first domain
        d1 = domains[0]
        assert d1.domain_id == "e8abcA1"
        assert d1.range == "10-110"
        assert d1.size == 101
        assert d1.source == "domain_blast"
        assert d1.family == "Ras-like GTPase"
        assert d1.confidence == 0.95

        # Verify second domain
        d2 = domains[1]
        assert d2.domain_id == "e8abcA2"
        assert d2.range == "150-250"
        assert d2.size == 101


@pytest.mark.skipif(not LIBRARY_AVAILABLE, reason="pyecod_mini library not installed")
class TestLibraryAPIIntegration:
    """Test library API integration (requires pyecod_mini installed)"""

    def test_library_api_available(self):
        """Verify library API can be imported"""
        from pyecod_mini import partition_protein, PartitionError
        assert callable(partition_protein)

    @mock.patch('pyecod_prod.core.partition_runner.partition_protein')
    def test_partition_via_library(self, mock_partition):
        """Test partitioning via library API (mocked)"""
        # Mock the library response
        from dataclasses import dataclass
        from typing import List

        @dataclass
        class MockDomain:
            domain_id: str
            range_string: str
            residue_count: int
            source: str
            family_name: str
            confidence: float

        @dataclass
        class MockResult:
            pdb_id: str
            chain_id: str
            sequence_length: int
            domains: List
            coverage: float
            algorithm_version: str
            success: bool
            error_message: str = None

        mock_domain = MockDomain(
            domain_id="e8abcA1",
            range_string="10-110",
            residue_count=101,
            source="domain_blast",
            family_name="Ras-like GTPase",
            confidence=0.95
        )

        mock_result = MockResult(
            pdb_id="8abc",
            chain_id="A",
            sequence_length=250,
            domains=[mock_domain],
            coverage=0.88,
            algorithm_version="2.0.0",
            success=True
        )

        mock_partition.return_value = mock_result

        # Create mock summary XML
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write("""<?xml version="1.0"?>
<domain_summary version="1.0">
  <protein pdb_id="8abc" chain_id="A" length="250">
    <sequence>MKTAYIAKQRQ</sequence>
  </protein>
  <evidence/>
</domain_summary>""")
            summary_xml = f.name

        try:
            with tempfile.TemporaryDirectory() as output_dir:
                runner = PartitionRunner(use_library=True)
                result = runner.partition(
                    summary_xml=summary_xml,
                    output_dir=output_dir,
                    batch_id="test_batch"
                )

                # Verify result
                assert result.pdb_id == "8abc"
                assert result.chain_id == "A"
                assert result.domain_count == 1
                assert result.partition_coverage == 0.88
                assert result.partition_quality == "good"  # 88% >= 80%
                assert result.algorithm_version == "2.0.0"

                # Verify library was called
                mock_partition.assert_called_once()

        finally:
            os.unlink(summary_xml)


class TestCLIFallback:
    """Test CLI fallback when library not available"""

    @mock.patch('pyecod_prod.core.partition_runner.subprocess.run')
    def test_partition_via_cli(self, mock_subprocess):
        """Test partitioning via CLI (mocked)"""
        # Mock successful subprocess run
        mock_subprocess.return_value = mock.Mock(returncode=0)

        # Create mock summary XML
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write("""<?xml version="1.0"?>
<domain_summary version="1.0">
  <protein pdb_id="8abc" chain_id="A" length="250">
    <sequence>MKTAYIAKQRQ</sequence>
  </protein>
  <evidence/>
</domain_summary>""")
            summary_xml = f.name

        try:
            with tempfile.TemporaryDirectory() as output_dir:
                # Create mock partition output
                partition_xml = Path(output_dir) / "8abc_A.partition.xml"
                with open(partition_xml, "w") as f:
                    f.write("""<?xml version="1.0"?>
<partition algorithm_version="2.0.0">
  <protein pdb_id="8abc" chain_id="A" length="250">
    <coverage>0.75</coverage>
    <domains>
      <domain id="e8abcA1" range="10-110" size="101"
              source="domain_blast" family="Ras-like GTPase"/>
    </domains>
  </protein>
</partition>""")

                runner = PartitionRunner(use_library=False)  # Force CLI
                result = runner.partition(
                    summary_xml=summary_xml,
                    output_dir=output_dir,
                    batch_id="test_batch"
                )

                # Verify result
                assert result.pdb_id == "8abc"
                assert result.chain_id == "A"
                assert result.domain_count == 1
                assert result.partition_coverage == 0.75
                assert result.partition_quality == "low_coverage"  # 50-80%
                assert result.algorithm_version == "2.0.0"

                # Verify subprocess was called (once for --version, once for partition)
                assert mock_subprocess.call_count == 2

                # Check the second call (actual partition)
                partition_call = mock_subprocess.call_args_list[1]
                assert "pyecod-mini" in partition_call[0][0]
                assert "8abc_A" in partition_call[0][0]

        finally:
            os.unlink(summary_xml)

    @mock.patch('pyecod_prod.core.partition_runner.subprocess.run')
    def test_cli_timeout(self, mock_subprocess):
        """Test CLI timeout handling"""
        import subprocess as sp

        # Mock timeout
        mock_subprocess.side_effect = sp.TimeoutExpired("pyecod-mini", 300)

        # Create mock summary XML
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write("""<?xml version="1.0"?>
<domain_summary version="1.0">
  <protein pdb_id="8abc" chain_id="A" length="250">
    <sequence>MKTAYIAKQRQ</sequence>
  </protein>
  <evidence/>
</domain_summary>""")
            summary_xml = f.name

        try:
            with tempfile.TemporaryDirectory() as output_dir:
                runner = PartitionRunner(use_library=False)
                result = runner.partition(
                    summary_xml=summary_xml,
                    output_dir=output_dir,
                    batch_id="test_batch"
                )

                # Verify error handling
                assert result.domain_count == 0
                assert result.partition_quality == "failed"
                assert "timed out" in result.error_message.lower()

        finally:
            os.unlink(summary_xml)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
