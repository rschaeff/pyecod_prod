"""PartitionRunner reference-caching selection (Gap 2: avoid per-chain reference reload)."""

import pytest

from pyecod_prod.core.partition_runner import PartitionRunner, LIBRARY_AVAILABLE


def test_no_refs_uses_per_call_path():
    """Without reference CSVs, keep the per-call partition_protein path (unchanged)."""
    runner = PartitionRunner()
    assert runner._use_cached is False
    assert runner._partitioner is None


@pytest.mark.skipif(not LIBRARY_AVAILABLE, reason="pyecod_mini library required")
def test_refs_enable_cached_partitioner_lazily():
    """With reference CSVs, select the cached Partitioner path; build it lazily."""
    runner = PartitionRunner(
        domain_definitions_file="/x/domain_definitions.csv",
        reference_lengths_file="/x/domain_lengths.csv",
        protein_lengths_file="/x/protein_lengths.csv",
    )
    assert runner._use_cached is True
    assert runner._partitioner is None  # not built until first partition()


@pytest.mark.skipif(not LIBRARY_AVAILABLE, reason="pyecod_mini library required")
def test_partial_refs_still_select_cached():
    """Any one configured reference file is enough to select the cached path."""
    runner = PartitionRunner(domain_definitions_file="/x/domain_definitions.csv")
    assert runner._use_cached is True
