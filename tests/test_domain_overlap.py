"""
Tests for domain overlap detection and auto-accession logic.

These tests verify:
1. Range parsing (chain-specified and raw formats)
2. Overlap calculation between domains
3. Severity assessment based on ECOD policy
4. Discontinuous range handling
"""

import pytest
from pyecod_prod.database.domain_overlap import (
    parse_range,
    calculate_overlap,
    assess_overlap_severity,
    DomainRange,
    RangeSegment,
    OverlapSeverity,
)


class TestRangeParsing:
    """Test range parsing for various formats."""

    def test_parse_chain_specified_single(self):
        """Parse single segment with chain."""
        result = parse_range("A:10-150")
        assert len(result.segments) == 1
        assert result.segments[0].chain_id == "A"
        assert result.segments[0].start == 10
        assert result.segments[0].end == 150
        assert result.total_length == 141

    def test_parse_chain_specified_discontinuous(self):
        """Parse discontinuous range with chain."""
        result = parse_range("A:10-50,A:100-150")
        assert len(result.segments) == 2
        assert result.is_discontinuous
        assert result.total_length == 41 + 51  # 92

    def test_parse_raw_single(self):
        """Parse single segment without chain."""
        result = parse_range("10-150")
        assert len(result.segments) == 1
        assert result.segments[0].chain_id is None
        assert result.segments[0].start == 10
        assert result.segments[0].end == 150

    def test_parse_raw_discontinuous(self):
        """Parse discontinuous range without chain."""
        result = parse_range("10-50,100-150")
        assert len(result.segments) == 2
        assert result.is_discontinuous

    def test_parse_multi_chain(self):
        """Parse range spanning multiple chains."""
        result = parse_range("A:10-50,B:60-100")
        assert len(result.segments) == 2
        assert result.segments[0].chain_id == "A"
        assert result.segments[1].chain_id == "B"
        assert result.chain_id is None  # No single chain

    def test_normalize_raw_to_chain(self):
        """Normalize raw range to chain-specified format."""
        result = parse_range("10-50,100-150")
        normalized = result.normalize(default_chain="A")
        assert all(s.chain_id == "A" for s in normalized.segments)
        assert "A:" in normalized.to_string()

    def test_empty_range(self):
        """Handle empty range."""
        result = parse_range("")
        assert len(result.segments) == 0

    def test_negative_residues(self):
        """Handle negative residue numbers (some PDBs have these)."""
        result = parse_range("A:-5-50")
        assert result.segments[0].start == -5
        assert result.segments[0].end == 50


class TestOverlapCalculation:
    """Test overlap calculation between domains."""

    def test_no_overlap(self):
        """Two domains with no overlap."""
        range1 = parse_range("A:10-50")
        range2 = parse_range("A:60-100")
        metrics = calculate_overlap(range1, range2)

        assert metrics['residue_overlap'] == 0
        assert metrics['coverage_1_by_2'] == 0.0
        assert metrics['coverage_2_by_1'] == 0.0
        assert not metrics['is_identical']

    def test_partial_overlap(self):
        """Two domains with partial overlap."""
        range1 = parse_range("A:10-50")  # 41 residues
        range2 = parse_range("A:40-80")  # 41 residues, overlap 40-50 = 11 residues
        metrics = calculate_overlap(range1, range2)

        assert metrics['residue_overlap'] == 11
        assert 0.25 < metrics['coverage_1_by_2'] < 0.30  # ~27%
        assert 0.25 < metrics['coverage_2_by_1'] < 0.30

    def test_identical_ranges(self):
        """Two identical domains."""
        range1 = parse_range("A:10-50")
        range2 = parse_range("A:10-50")
        metrics = calculate_overlap(range1, range2)

        assert metrics['is_identical']
        assert metrics['coverage_1_by_2'] == 1.0
        assert metrics['coverage_2_by_1'] == 1.0

    def test_one_contains_other(self):
        """One domain completely contains the other."""
        range1 = parse_range("A:10-100")  # 91 residues
        range2 = parse_range("A:30-50")   # 21 residues, fully contained
        metrics = calculate_overlap(range1, range2)

        assert metrics['residue_overlap'] == 21
        assert metrics['coverage_2_by_1'] == 1.0  # range2 fully covered by range1
        assert 0.20 < metrics['coverage_1_by_2'] < 0.25  # range1 partially covered

    def test_high_bidirectional_overlap(self):
        """High overlap in both directions (loose correspondence)."""
        range1 = parse_range("A:10-100")  # 91 residues
        range2 = parse_range("A:15-95")   # 81 residues, overlap = 81
        metrics = calculate_overlap(range1, range2)

        assert metrics['coverage_1_by_2'] > 0.80  # >80% of range1 covered
        assert metrics['coverage_2_by_1'] == 1.0  # 100% of range2 covered

    def test_discontinuous_overlap(self):
        """Overlap between discontinuous domains."""
        range1 = parse_range("A:10-50,A:100-150")  # 92 residues
        range2 = parse_range("A:40-110")           # 71 residues, overlaps both segments
        metrics = calculate_overlap(range1, range2)

        # Overlaps 40-50 (11) and 100-110 (11) = 22 residues
        assert metrics['residue_overlap'] == 22

    def test_chain_mismatch_treated_as_overlap(self):
        """Different chains - currently treated as potentially overlapping."""
        # Note: This is a design decision. We're comparing residue numbers
        # regardless of chain. The caller should filter by chain if needed.
        range1 = parse_range("A:10-50")
        range2 = parse_range("B:10-50")
        metrics = calculate_overlap(range1, range2)

        # Same residue numbers, different chains - currently counts as overlap
        # This matches how the legacy script tracks per-chain
        assert metrics['residue_overlap'] == 41


class TestSeverityAssessment:
    """Test overlap severity assessment based on ECOD policy."""

    def test_no_overlap_severity(self):
        """No overlap should be NONE severity."""
        metrics = {'residue_overlap': 0, 'coverage_1_by_2': 0.0,
                   'coverage_2_by_1': 0.0, 'is_identical': False}
        severity, message = assess_overlap_severity(metrics)
        assert severity == OverlapSeverity.NONE

    def test_identical_severity(self):
        """Identical ranges should be IDENTICAL severity."""
        metrics = {'residue_overlap': 100, 'coverage_1_by_2': 1.0,
                   'coverage_2_by_1': 1.0, 'is_identical': True}
        severity, message = assess_overlap_severity(metrics)
        assert severity == OverlapSeverity.IDENTICAL

    def test_severe_bidirectional(self):
        """High bidirectional overlap (>80% both) should be SEVERE."""
        metrics = {'residue_overlap': 85, 'coverage_1_by_2': 0.85,
                   'coverage_2_by_1': 0.90, 'is_identical': False}
        severity, message = assess_overlap_severity(metrics)
        assert severity == OverlapSeverity.SEVERE
        assert "bidirectional" in message.lower()

    def test_severe_residue_conflict(self):
        """More than 10 residue overlap should be SEVERE."""
        metrics = {'residue_overlap': 15, 'coverage_1_by_2': 0.15,
                   'coverage_2_by_1': 0.15, 'is_identical': False}
        severity, message = assess_overlap_severity(metrics)
        assert severity == OverlapSeverity.SEVERE
        assert "residue conflict" in message.lower()

    def test_minor_overlap(self):
        """Small overlap (≤5% both directions) should be MINOR."""
        metrics = {'residue_overlap': 5, 'coverage_1_by_2': 0.03,
                   'coverage_2_by_1': 0.04, 'is_identical': False}
        severity, message = assess_overlap_severity(metrics)
        assert severity == OverlapSeverity.MINOR

    def test_moderate_overlap(self):
        """Medium overlap should be MODERATE."""
        metrics = {'residue_overlap': 8, 'coverage_1_by_2': 0.10,
                   'coverage_2_by_1': 0.15, 'is_identical': False}
        severity, message = assess_overlap_severity(metrics)
        assert severity == OverlapSeverity.MODERATE

    def test_custom_thresholds(self):
        """Test with custom thresholds."""
        metrics = {'residue_overlap': 8, 'coverage_1_by_2': 0.10,
                   'coverage_2_by_1': 0.10, 'is_identical': False}

        # With default threshold (10), this is MINOR
        severity1, _ = assess_overlap_severity(metrics, max_allowed_residue_overlap=10)
        assert severity1 == OverlapSeverity.MODERATE

        # With stricter threshold (5), this becomes SEVERE
        severity2, _ = assess_overlap_severity(metrics, max_allowed_residue_overlap=5)
        assert severity2 == OverlapSeverity.SEVERE


class TestRealWorldCases:
    """Test with real-world ECOD range patterns."""

    def test_multi_domain_chain_no_overlap(self):
        """Multiple domains on same chain without overlap (common case)."""
        domains = [
            parse_range("A:1-98"),
            parse_range("A:109-237"),
            parse_range("A:238-290")
        ]

        # Check all pairs
        for i, d1 in enumerate(domains):
            for j, d2 in enumerate(domains):
                if i >= j:
                    continue
                metrics = calculate_overlap(d1, d2)
                assert metrics['residue_overlap'] == 0, f"Domains {i} and {j} should not overlap"

    def test_neighboring_domains_small_gap(self):
        """Neighboring domains with small gap."""
        domain1 = parse_range("A:1-100")
        domain2 = parse_range("A:103-200")  # 2 residue gap
        metrics = calculate_overlap(domain1, domain2)
        assert metrics['residue_overlap'] == 0

    def test_insertion_domain_pattern(self):
        """Discontinuous domain with insertion (domain within domain)."""
        # Outer domain: A:1-50 and A:150-200
        # Inner domain: A:60-140
        outer = parse_range("A:1-50,A:150-200")
        inner = parse_range("A:60-140")

        metrics = calculate_overlap(outer, inner)
        assert metrics['residue_overlap'] == 0  # No actual overlap

    def test_legacy_perl_script_scenario(self):
        """
        Simulate the legacy Perl script's overlap detection.

        The Perl script would skip if:
        - Identical range
        - c1 > 0.8 AND c2 > 0.8 (loose correspondence)
        - total_res_conflict > 10
        """
        # Case 1: Should be accepted (no overlap)
        existing = parse_range("A:1-100")
        new = parse_range("A:110-200")
        metrics = calculate_overlap(existing, new)
        severity, _ = assess_overlap_severity(metrics)
        assert severity == OverlapSeverity.NONE

        # Case 2: Should be skipped (identical)
        new_identical = parse_range("A:1-100")
        metrics = calculate_overlap(existing, new_identical)
        severity, _ = assess_overlap_severity(metrics)
        assert severity == OverlapSeverity.IDENTICAL

        # Case 3: Should be skipped (loose correspondence)
        new_loose = parse_range("A:5-95")
        metrics = calculate_overlap(existing, new_loose)
        severity, _ = assess_overlap_severity(metrics)
        assert severity == OverlapSeverity.SEVERE

        # Case 4: Should be skipped (>10 residue conflict)
        new_conflict = parse_range("A:90-200")  # 11 residue overlap
        metrics = calculate_overlap(existing, new_conflict)
        severity, _ = assess_overlap_severity(metrics)
        assert severity == OverlapSeverity.SEVERE


class TestSegmentOperations:
    """Test segment-level operations for PostgreSQL integration."""

    def test_segment_to_pg_range(self):
        """Convert segment to PostgreSQL range format."""
        segment = RangeSegment("A", 10, 50)
        pg_range = segment.to_pg_range()
        assert pg_range == "[10, 50]"

    def test_segment_overlap_check(self):
        """Check segment-level overlap."""
        seg1 = RangeSegment("A", 10, 50)
        seg2 = RangeSegment("A", 40, 80)
        seg3 = RangeSegment("A", 60, 100)

        assert seg1.overlaps(seg2)  # 40-50 overlap
        assert not seg1.overlaps(seg3)  # No overlap
        assert seg2.overlaps(seg3)  # 60-80 overlap

    def test_segment_overlap_residues(self):
        """Get specific overlapping residues."""
        seg1 = RangeSegment("A", 10, 50)
        seg2 = RangeSegment("A", 40, 80)

        overlap = seg1.overlap_residues(seg2)
        assert overlap == set(range(40, 51))  # 40-50 inclusive


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
