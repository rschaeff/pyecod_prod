"""
Test curation_loader module with sample data.

This test verifies that:
1. Proteins can be loaded to ecod_curation schema
2. Domains and evidence are correctly inserted
3. Queue logic works as expected
4. Helper functions classify partition quality correctly
"""

import pytest
from datetime import date
from pyecod_prod.database.curation_loader import (
    load_partition_to_curation,
    classify_partition_quality,
    can_curate,
    get_cannot_curate_reason,
    should_queue_for_curation,
    calculate_queue_priority,
    get_db_connection,
)


# Sample partition result matching the schema test data
SAMPLE_PARTITION_RESULT = {
    'coverage': 0.95,
    'domains': [
        {
            'start': 10,
            'end': 150,
            'range_string': '10-150',
            't_group': '1.1.13',
            'h_group': '1.1',
            'x_group': '1.1.13',
            'f_group': '1.1.13.29',
            'best_match_ecod_uid': 3066545,
            'assignment_method': 'blast',
            'classification_level': 'f_group_specific',
            'confidence': 0.92,
            'evidence': [
                {
                    'type': 'blast_domain',
                    'hit_ecod_uid': 3066545,
                    'hit_pdb_id': '8s9s',
                    'hit_chain_id': '7',
                    'evalue': 1.5e-45,
                    'score': 189.2,
                    'query_coverage': 0.95,
                    'hit_coverage': 0.92,
                    'query_range': '10-150',
                    'hit_range': '5-145',
                    'ref_t_group': '1.1.13',
                    'ref_h_group': '1.1',
                    'ref_x_group': '1.1.13',
                    'ref_f_group': '1.1.13.29',
                }
            ]
        },
        {
            'start': 160,
            'end': 280,
            'range_string': '160-280',
            't_group': '557.1.1',
            'h_group': None,
            'x_group': None,
            'f_group': None,
            'best_match_ecod_uid': None,
            'assignment_method': 'hhsearch',
            'classification_level': 't_group_only',
            'confidence': 0.65,
            'evidence': [
                {
                    'type': 'hhsearch',
                    'evalue': 0.00012,
                    'score': 52.3,
                    'query_coverage': 0.88,
                    'hit_coverage': 0.85,
                    'query_range': '160-280',
                    'hit_range': '10-125',
                    'ref_t_group': '557.1.1',
                }
            ]
        }
    ]
}

SAMPLE_SEQUENCE = (
    "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKRQTLGQHDFSAGEGLYTHMKALRPDEDRL"
    "SPLHSVYVDQWDWERVMGDGERQFSTLKSTVEAIWAGIKATEAAVSEEFGLAPFLPDQIHFVHSQELLSRYPDLDAKGRERAIAKDLGAVFLVGIGGKLSDGHRHDV"
    "RAPDYDDWSTPSELGHAGLNGDILVWNPVLEDAFELSSMGIRVDADTLKHQLALTGDEDRLELEWHQALLRGEMPQTIGGGIGQSRLTMLLLQLPHIGQVQAGVWPA"
    "AVRESVPSLL"
)


def test_classify_partition_quality_good():
    """Test classification of high-quality partitions"""
    result = {
        'coverage': 0.95,
        'domains': [
            {'confidence': 0.92},
            {'confidence': 0.88}
        ]
    }
    assert classify_partition_quality(result) == 'good'


def test_classify_partition_quality_low_coverage():
    """Test classification of low coverage partitions"""
    result = {
        'coverage': 0.65,
        'domains': [
            {'confidence': 0.92}
        ]
    }
    assert classify_partition_quality(result) == 'low_coverage'


def test_classify_partition_quality_fragmentary():
    """Test classification of fragmentary partitions"""
    result = {
        'coverage': 0.45,
        'domains': [
            {'confidence': 0.92}
        ]
    }
    assert classify_partition_quality(result) == 'fragmentary'


def test_classify_partition_quality_failed():
    """Test classification of failed partitions"""
    result = {
        'coverage': 0.0,
        'domains': []
    }
    assert classify_partition_quality(result) == 'failed'


def test_can_curate_valid_protein():
    """Test that valid proteins can be curated"""
    assert can_curate(SAMPLE_SEQUENCE, SAMPLE_PARTITION_RESULT) is True


def test_can_curate_too_short():
    """Test that short peptides cannot be curated"""
    short_seq = "MKTAYIAKQR"
    assert can_curate(short_seq, SAMPLE_PARTITION_RESULT) is False
    assert get_cannot_curate_reason(short_seq, SAMPLE_PARTITION_RESULT) == 'too_short'


def test_can_curate_nucleic_acid():
    """Test that nucleic acids cannot be curated"""
    nucleic_seq = "ATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCG"
    assert can_curate(nucleic_seq, SAMPLE_PARTITION_RESULT) is False
    assert get_cannot_curate_reason(nucleic_seq, SAMPLE_PARTITION_RESULT) == 'nucleic_acid'


def test_should_queue_low_confidence():
    """Test queueing logic for low confidence"""
    result = {
        'coverage': 0.95,
        'domains': [
            {'confidence': 0.65, 'f_group': '1.1.13.29'}
        ]
    }
    should_queue, reason = should_queue_for_curation(result)
    assert should_queue is True
    assert reason == 'low_confidence'


def test_should_queue_low_coverage():
    """Test queueing logic for low coverage"""
    result = {
        'coverage': 0.65,
        'domains': [
            {'confidence': 0.92, 'f_group': '1.1.13.29'}
        ]
    }
    should_queue, reason = should_queue_for_curation(result)
    assert should_queue is True
    assert reason == 'low_coverage'


def test_should_queue_incomplete_classification():
    """Test queueing logic for incomplete classification"""
    result = {
        'coverage': 0.95,
        'domains': [
            {'confidence': 0.92, 'f_group': None}  # No f-group
        ]
    }
    should_queue, reason = should_queue_for_curation(result)
    assert should_queue is True
    assert reason == 'incomplete_classification'


def test_should_not_queue_high_quality():
    """Test that high quality partitions are auto-accepted"""
    result = {
        'coverage': 0.95,
        'domains': [
            {'confidence': 0.92, 'f_group': '1.1.13.29'}
        ]
    }
    should_queue, reason = should_queue_for_curation(result)
    assert should_queue is False
    assert reason == 'auto_accepted'


def test_calculate_priority_very_urgent():
    """Test priority calculation for very urgent cases"""
    result = {
        'coverage': 0.45,
        'domains': [
            {'confidence': 0.45}
        ]
    }
    assert calculate_queue_priority(result) == 10


def test_calculate_priority_medium():
    """Test priority calculation for medium priority cases"""
    result = {
        'coverage': 0.85,
        'domains': [
            {'confidence': 0.65}
        ]
    }
    assert calculate_queue_priority(result) == 5


def test_calculate_priority_low():
    """Test priority calculation for low priority cases"""
    result = {
        'coverage': 0.95,
        'domains': [
            {'confidence': 0.92}
        ]
    }
    assert calculate_queue_priority(result) == 1


@pytest.mark.integration
def test_load_partition_to_curation_integration():
    """
    Integration test: Load a partition to ecod_curation and verify.

    This test:
    1. Loads a test protein to ecod_curation
    2. Verifies the protein, domains, and evidence were inserted
    3. Verifies queue logic worked correctly
    4. Cleans up test data

    NOTE: Requires database connection to dione:45000/ecod_protein
    """
    import psycopg2.extras

    # Load partition
    protein_id = load_partition_to_curation(
        pdb_id='9xyz',
        chain_id='A',
        release_date=date(2025, 1, 20),
        sequence=SAMPLE_SEQUENCE,
        partition_result=SAMPLE_PARTITION_RESULT,
        processing_version='pyecod_prod_test'
    )

    assert protein_id is not None
    print(f"Loaded protein with ID: {protein_id}")

    # Verify the protein was inserted correctly
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Check protein
        cursor.execute(
            "SELECT * FROM ecod_curation.protein WHERE id = %s",
            (protein_id,)
        )
        protein = cursor.fetchone()
        assert protein is not None
        assert protein['source_id'] == '9xyz_A'
        assert protein['pdb_id'] == '9xyz'
        assert protein['chain_id'] == 'A'
        assert protein['partition_coverage'] == 0.95
        assert protein['domain_count'] == 2
        assert protein['partition_quality'] == 'good'
        assert protein['can_curate'] is True
        print(f"✓ Protein verified: {protein['source_id']}")

        # Check domains
        cursor.execute(
            "SELECT * FROM ecod_curation.domain_assignment WHERE protein_id = %s ORDER BY domain_number",
            (protein_id,)
        )
        domains = cursor.fetchall()
        assert len(domains) == 2
        assert domains[0]['assigned_f_group'] == '1.1.13.29'
        assert domains[1]['assigned_f_group'] is None  # T-group only
        print(f"✓ Domains verified: {len(domains)} domains")

        # Check evidence
        cursor.execute(
            """
            SELECT de.* FROM ecod_curation.domain_evidence de
            JOIN ecod_curation.domain_assignment da ON de.domain_id = da.id
            WHERE da.protein_id = %s
            ORDER BY de.id
            """,
            (protein_id,)
        )
        evidence = cursor.fetchall()
        assert len(evidence) == 2  # One evidence per domain
        assert evidence[0]['evidence_type'] == 'blast_domain'
        assert evidence[1]['evidence_type'] == 'hhsearch'
        print(f"✓ Evidence verified: {len(evidence)} evidence records")

        # Check queue
        cursor.execute(
            "SELECT * FROM ecod_curation.curation_queue WHERE protein_id = %s",
            (protein_id,)
        )
        queue = cursor.fetchone()
        # Should be queued due to incomplete classification (domain 2 has no f-group)
        assert queue is not None
        assert queue['priority_reason'] == 'incomplete_classification'
        print(f"✓ Queue verified: priority={queue['priority']}, reason={queue['priority_reason']}")

        # Check queue_view
        cursor.execute(
            "SELECT * FROM ecod_curation.queue_view WHERE protein_id = %s",
            (protein_id,)
        )
        queue_view = cursor.fetchone()
        assert queue_view is not None
        assert queue_view['source_id'] == '9xyz_A'
        print(f"✓ Queue view verified")

    finally:
        # Cleanup
        cursor.execute("DELETE FROM ecod_curation.protein WHERE id = %s", (protein_id,))
        conn.commit()
        print(f"✓ Test data cleaned up")

        cursor.close()
        conn.close()


if __name__ == '__main__':
    # Run integration test directly
    print("Running integration test...")
    test_load_partition_to_curation_integration()
    print("\n✓ All integration tests passed!")
