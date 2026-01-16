#!/usr/bin/env python3
"""
Tests for designed protein detection utilities.
"""

import pytest
from unittest.mock import Mock, patch

from pyecod_prod.utils.designed_proteins import (
    DesignedProteinDetector,
    DesignedProteinResult,
    DesignedProteinConfidence,
    is_designed_protein,
    get_designed_protein_info,
)


class TestDesignedProteinDetector:
    """Tests for DesignedProteinDetector class."""

    def test_detect_synthetic_construct_organism(self):
        """Synthetic construct organism should be high confidence."""
        detector = DesignedProteinDetector()

        # Mock the metadata
        metadata = {
            'title': 'Some protein structure',
            'keywords': 'PROTEIN BINDING',
            'source_organism': 'synthetic construct',
        }

        result = detector.detect('test', metadata=metadata)

        assert result.is_designed is True
        assert result.confidence == DesignedProteinConfidence.HIGH
        assert 'synthetic_construct_organism' in result.reasons
        assert result.score >= 3

    def test_detect_de_novo_keyword(self):
        """DE NOVO PROTEIN keyword should be high confidence."""
        detector = DesignedProteinDetector()

        metadata = {
            'title': 'Crystal structure of protein',
            'keywords': 'DE NOVO PROTEIN',
            'source_organism': 'Escherichia coli',
        }

        result = detector.detect('test', metadata=metadata)

        assert result.is_designed is True
        assert result.confidence == DesignedProteinConfidence.HIGH
        assert 'de_novo_keyword' in result.reasons

    def test_detect_de_novo_title(self):
        """'de novo' in title should be high confidence."""
        detector = DesignedProteinDetector()

        metadata = {
            'title': 'De novo designed protein for catalysis',
            'keywords': 'HYDROLASE',
            'source_organism': 'Escherichia coli',
        }

        result = detector.detect('test', metadata=metadata)

        assert result.is_designed is True
        assert result.confidence == DesignedProteinConfidence.HIGH
        assert 'de_novo_title' in result.reasons

    def test_detect_designed_title_medium(self):
        """'designed' alone in title should be medium confidence."""
        detector = DesignedProteinDetector()

        metadata = {
            'title': 'Crystal structure of designed zinc binding protein',
            'keywords': 'METAL BINDING PROTEIN',
            'source_organism': 'Escherichia coli',
        }

        result = detector.detect('test', metadata=metadata)

        assert result.is_designed is True
        # Just "designed" gives score=1, which is medium
        assert result.confidence == DesignedProteinConfidence.MEDIUM
        assert 'designed_title' in result.reasons

    def test_detect_miniprotein(self):
        """Miniprotein in title should be high confidence."""
        detector = DesignedProteinDetector()

        metadata = {
            'title': 'Structure of a miniprotein binder',
            'keywords': 'PROTEIN BINDING',
            'source_organism': 'Escherichia coli',
        }

        result = detector.detect('test', metadata=metadata)

        assert result.is_designed is True
        assert 'miniprotein' in result.reasons

    def test_detect_design_method_rosetta(self):
        """Rosetta method mention should be high confidence."""
        detector = DesignedProteinDetector()

        metadata = {
            'title': 'Rosetta designed protein scaffold',
            'keywords': 'PROTEIN BINDING',
            'source_organism': 'Escherichia coli',
        }

        result = detector.detect('test', metadata=metadata)

        assert result.is_designed is True
        assert 'rosetta_method' in result.reasons

    def test_detect_natural_protein(self):
        """Natural proteins should not be detected as designed."""
        detector = DesignedProteinDetector()

        metadata = {
            'title': 'Crystal structure of human lysozyme',
            'keywords': 'HYDROLASE',
            'source_organism': 'Homo sapiens',
        }

        result = detector.detect('test', metadata=metadata)

        assert result.is_designed is False
        assert result.confidence == DesignedProteinConfidence.NONE
        assert result.score == 0
        assert len(result.reasons) == 0

    def test_combined_markers(self):
        """Multiple markers should increase score."""
        detector = DesignedProteinDetector()

        metadata = {
            'title': 'De novo designed miniprotein',
            'keywords': 'DE NOVO PROTEIN',
            'source_organism': 'synthetic construct',
        }

        result = detector.detect('test', metadata=metadata)

        assert result.is_designed is True
        assert result.confidence == DesignedProteinConfidence.HIGH
        # Should have multiple reasons
        assert len(result.reasons) >= 3
        assert result.score >= 7  # 3 (synthetic) + 3 (keyword) + 2 (de novo title)

    def test_filter_designed(self):
        """filter_designed should separate designed from natural."""
        detector = DesignedProteinDetector()

        # Mock detect method
        def mock_detect(pdb_id, metadata=None):
            if pdb_id in ['designed1', 'designed2']:
                return DesignedProteinResult(
                    pdb_id=pdb_id,
                    is_designed=True,
                    confidence=DesignedProteinConfidence.HIGH,
                    score=5,
                    reasons=['synthetic_construct_organism'],
                )
            else:
                return DesignedProteinResult(
                    pdb_id=pdb_id,
                    is_designed=False,
                    confidence=DesignedProteinConfidence.NONE,
                    score=0,
                    reasons=[],
                )

        detector.detect = mock_detect

        pdb_ids = ['natural1', 'designed1', 'natural2', 'designed2']
        natural, designed = detector.filter_designed(pdb_ids)

        assert set(natural) == {'natural1', 'natural2'}
        assert set(designed) == {'designed1', 'designed2'}

    def test_should_exclude_property(self):
        """should_exclude should be True only for high confidence."""
        high_result = DesignedProteinResult(
            pdb_id='test',
            is_designed=True,
            confidence=DesignedProteinConfidence.HIGH,
            score=5,
        )
        assert high_result.should_exclude is True

        medium_result = DesignedProteinResult(
            pdb_id='test',
            is_designed=True,
            confidence=DesignedProteinConfidence.MEDIUM,
            score=2,
        )
        assert medium_result.should_exclude is False

        none_result = DesignedProteinResult(
            pdb_id='test',
            is_designed=False,
            confidence=DesignedProteinConfidence.NONE,
            score=0,
        )
        assert none_result.should_exclude is False


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_is_designed_protein(self):
        """Test is_designed_protein helper."""
        # This test requires actual PDB files, so we mock the detector
        with patch('pyecod_prod.utils.designed_proteins.DesignedProteinDetector') as MockDetector:
            mock_instance = MockDetector.return_value
            mock_instance.detect.return_value = DesignedProteinResult(
                pdb_id='test',
                is_designed=True,
                confidence=DesignedProteinConfidence.HIGH,
                score=5,
            )

            # This would normally hit the actual detector
            # For unit testing, we verify the mock is called correctly
            result = is_designed_protein('test')
            assert result is True

    def test_get_designed_protein_info(self):
        """Test get_designed_protein_info helper."""
        with patch('pyecod_prod.utils.designed_proteins.DesignedProteinDetector') as MockDetector:
            expected_result = DesignedProteinResult(
                pdb_id='test',
                is_designed=True,
                confidence=DesignedProteinConfidence.HIGH,
                score=5,
                reasons=['synthetic_construct_organism'],
            )
            mock_instance = MockDetector.return_value
            mock_instance.detect.return_value = expected_result

            result = get_designed_protein_info('test')
            assert result.pdb_id == 'test'
            assert result.is_designed is True


class TestIntegrationWithRealPDB:
    """Integration tests with real PDB files (if available)."""

    @pytest.mark.skipif(
        not pytest.importorskip('pathlib').Path('/usr2/pdb/data/structures/divided/mmCIF').exists(),
        reason="PDB mirror not available"
    )
    def test_real_designed_protein(self):
        """Test detection on a known designed protein."""
        # 9hnh is a known designed protein (synthetic alpha solenoid)
        result = get_designed_protein_info('9hnh')

        assert result.is_designed is True
        assert result.confidence == DesignedProteinConfidence.HIGH

    @pytest.mark.skipif(
        not pytest.importorskip('pathlib').Path('/usr2/pdb/data/structures/divided/mmCIF').exists(),
        reason="PDB mirror not available"
    )
    def test_real_natural_protein(self):
        """Test detection on a known natural protein."""
        # Test with a common natural protein
        result = get_designed_protein_info('9zru')

        assert result.is_designed is False
        assert result.confidence == DesignedProteinConfidence.NONE


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
