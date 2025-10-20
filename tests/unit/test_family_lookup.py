#!/usr/bin/env python3
"""
Unit tests for family lookup functionality.

Tests the new family lookup system added in October 2025 refactor.
"""

import os
import tempfile
from pathlib import Path

import pytest

from pyecod_prod.utils.family_lookup import (
    load_family_lookup,
    get_default_lookup_path,
    load_family_lookup_for_version,
)


class TestFamilyLookup:
    """Tests for family lookup utilities"""

    @pytest.fixture
    def mock_lookup_tsv(self):
        """Create a mock family lookup TSV file"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            f.write("# ECOD domain → family name mapping\n")
            f.write("ecod_domain_id\tfamily_name\n")
            f.write("e1suaA1\tGFP-like\n")
            f.write("e2ia4A1\tRas-like GTPase\n")
            f.write("e3gidA1\tSH3-like barrel\n")
            f.write("e4hznA1\tImmunoglobulin-like beta-sandwich\n")
            f.write("\n")  # blank line
            f.write("# Comment line\n")
            f.write("e5xyzB2\tAlpha-beta plaits\n")
            temp_path = f.name

        yield temp_path

        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    def test_load_family_lookup(self, mock_lookup_tsv):
        """Test loading family lookup from TSV"""
        lookup = load_family_lookup(mock_lookup_tsv)

        assert len(lookup) == 5
        assert lookup["e1suaA1"] == "GFP-like"
        assert lookup["e2ia4A1"] == "Ras-like GTPase"
        assert lookup["e3gidA1"] == "SH3-like barrel"
        assert lookup["e4hznA1"] == "Immunoglobulin-like beta-sandwich"
        assert lookup["e5xyzB2"] == "Alpha-beta plaits"

    def test_load_empty_file(self):
        """Test loading from empty file"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            f.write("# Just comments\n")
            temp_path = f.name

        try:
            lookup = load_family_lookup(temp_path)
            assert len(lookup) == 0
        finally:
            os.unlink(temp_path)

    def test_load_file_not_found(self):
        """Test loading from non-existent file raises error"""
        with pytest.raises(FileNotFoundError):
            load_family_lookup("/tmp/nonexistent_file.tsv")

    def test_get_default_lookup_path(self):
        """Test getting default lookup path for version"""
        path = get_default_lookup_path("develop291")
        assert path == "/data/ecod/database_versions/v291/domain_family_lookup.tsv"

        path = get_default_lookup_path("develop300")
        assert path == "/data/ecod/database_versions/v300/domain_family_lookup.tsv"

    def test_lookup_with_malformed_lines(self):
        """Test that malformed lines are skipped gracefully"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            f.write("ecod_domain_id\tfamily_name\n")
            f.write("e1suaA1\tGFP-like\n")
            f.write("malformed_line_no_tab\n")  # Should be skipped
            f.write("e2ia4A1\tRas-like GTPase\n")
            f.write("too\tmany\ttabs\there\n")  # Should be skipped (>2 fields)
            temp_path = f.name

        try:
            lookup = load_family_lookup(temp_path)
            assert len(lookup) == 2  # Only 2 valid entries
            assert lookup["e1suaA1"] == "GFP-like"
            assert lookup["e2ia4A1"] == "Ras-like GTPase"
        finally:
            os.unlink(temp_path)


class TestFamilyLookupIntegration:
    """Integration tests with SummaryGenerator"""

    def test_summary_generator_uses_family_lookup(self):
        """Test that SummaryGenerator uses family_lookup to populate target_family"""
        import xml.etree.ElementTree as ET
        from pyecod_prod.core.summary_generator import SummaryGenerator

        # Create mock family lookup
        family_lookup = {
            "e2ia4A1": "Ras-like GTPase",
            "e1suaA1": "GFP-like",
        }

        # Create mock BLAST XML with e2ia4A1 hit
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write("""<?xml version="1.0"?>
<!DOCTYPE BlastOutput PUBLIC "-//NCBI//NCBI BlastOutput/EN" "http://www.ncbi.nlm.nih.gov/dtd/NCBI_BlastOutput.dtd">
<BlastOutput>
  <BlastOutput_program>blastp</BlastOutput_program>
  <BlastOutput_version>BLASTP 2.12.0+</BlastOutput_version>
  <BlastOutput_iterations>
    <Iteration>
      <Iteration_iter-num>1</Iteration_iter-num>
      <Iteration_query-ID>Query_1</Iteration_query-ID>
      <Iteration_query-def>8abc_A</Iteration_query-def>
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
</BlastOutput>""")
            blast_xml = f.name

        try:
            # Generate summary with family lookup
            generator = SummaryGenerator(family_lookup=family_lookup)

            with tempfile.TemporaryDirectory() as tmpdir:
                summary_path = generator.generate_summary(
                    pdb_id="8abc",
                    chain_id="A",
                    sequence="M" * 250,
                    sequence_length=250,
                    domain_blast_xml=blast_xml,
                    output_path=f"{tmpdir}/summary.xml",
                )

                # Parse summary XML and verify target_family attribute
                tree = ET.parse(summary_path)
                root = tree.getroot()

                hits = root.findall(".//hit")
                assert len(hits) == 1

                hit = hits[0]
                assert hit.get("target") == "e2ia4A1"
                assert hit.get("target_family") == "Ras-like GTPase"

        finally:
            os.unlink(blast_xml)

    def test_summary_generator_handles_missing_domain(self):
        """Test that unknown domains get 'Unknown' family name"""
        import xml.etree.ElementTree as ET
        from pyecod_prod.core.summary_generator import SummaryGenerator

        # Create mock family lookup (without e9999X1)
        family_lookup = {
            "e2ia4A1": "Ras-like GTPase",
        }

        # Create mock BLAST XML with unknown domain e9999X1
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write("""<?xml version="1.0"?>
<!DOCTYPE BlastOutput PUBLIC "-//NCBI//NCBI BlastOutput/EN" "http://www.ncbi.nlm.nih.gov/dtd/NCBI_BlastOutput.dtd">
<BlastOutput>
  <BlastOutput_program>blastp</BlastOutput_program>
  <BlastOutput_version>BLASTP 2.12.0+</BlastOutput_version>
  <BlastOutput_iterations>
    <Iteration>
      <Iteration_iter-num>1</Iteration_iter-num>
      <Iteration_query-ID>Query_1</Iteration_query-ID>
      <Iteration_query-def>8abc_A</Iteration_query-def>
      <Iteration_query-len>250</Iteration_query-len>
      <Iteration_hits>
        <Hit>
          <Hit_num>1</Hit_num>
          <Hit_id>e9999X1</Hit_id>
          <Hit_def>e9999X1 unknown domain</Hit_def>
          <Hit_len>100</Hit_len>
          <Hit_hsps>
            <Hsp>
              <Hsp_num>1</Hsp_num>
              <Hsp_bit-score>150.0</Hsp_bit-score>
              <Hsp_evalue>1e-30</Hsp_evalue>
              <Hsp_query-from>10</Hsp_query-from>
              <Hsp_query-to>110</Hsp_query-to>
              <Hsp_hit-from>1</Hsp_hit-from>
              <Hsp_hit-to>95</Hsp_hit-to>
              <Hsp_align-len>101</Hsp_align-len>
              <Hsp_identity>75</Hsp_identity>
            </Hsp>
          </Hit_hsps>
        </Hit>
      </Iteration_hits>
    </Iteration>
  </BlastOutput_iterations>
</BlastOutput>""")
            blast_xml = f.name

        try:
            # Generate summary with family lookup
            generator = SummaryGenerator(family_lookup=family_lookup)

            with tempfile.TemporaryDirectory() as tmpdir:
                summary_path = generator.generate_summary(
                    pdb_id="8abc",
                    chain_id="A",
                    sequence="M" * 250,
                    sequence_length=250,
                    domain_blast_xml=blast_xml,
                    output_path=f"{tmpdir}/summary.xml",
                )

                # Parse summary XML and verify unknown domain gets "Unknown"
                tree = ET.parse(summary_path)
                root = tree.getroot()

                hits = root.findall(".//hit")
                assert len(hits) == 1

                hit = hits[0]
                assert hit.get("target") == "e9999X1"
                assert hit.get("target_family") == "Unknown"

        finally:
            os.unlink(blast_xml)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
