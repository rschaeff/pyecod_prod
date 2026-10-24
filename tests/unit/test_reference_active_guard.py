"""Regression tests for the inactive-reference gate (_check_reference_active).

The gate originally rejected any reference whose ``classification_status`` was not
'classified'. That column is 'unclassified' for every archaea_dpam_v294 domain and
almost every *_propagated domain, yet the published v295.2 release carries them fully
classified through their F-group assignments. The Q4 2026 dry run (2026-10-24) rejected
353 domains from 305 such references, every one of which had an F-group assignment
matching its published v295.2 label. Two real ones are used below.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def _loader(row):
    """An AutoAccessionLoader whose reference lookup returns ``row``."""
    from pyecod_prod.database import auto_accession as aa

    loader = aa.AutoAccessionLoader.__new__(aa.AutoAccessionLoader)
    loader._reference_status_cache = {}
    cur = MagicMock()
    cur.fetchone.return_value = row
    conn = MagicMock()
    conn.cursor.return_value = cur
    loader._get_connection = lambda: conn
    return loader


@pytest.mark.parametrize("ref", ["G4RPU5_F1_nD1", "e25yvB1"])
def test_unclassified_status_with_assignment_is_accepted(ref):
    # archaea_dpam / propagated reference: status 'unclassified', live F-group assignment
    assert _loader((False, "unclassified", None, True))._check_reference_active(ref) is None


def test_classified_without_assignment_is_accepted():
    assert _loader((False, "classified", None, False))._check_reference_active("e1abcA1") is None


def test_unclassified_without_assignment_is_rejected():
    msg = _loader((False, "unclassified", None, False))._check_reference_active("e1abcA1")
    assert msg and "no hierarchy assignment" in msg


@pytest.mark.parametrize("row, reason", [
    ((True, "classified", None, True), "OBSOLETE"),
    ((False, "classified", "e1xyzA1", True), "SUPERSEDED"),
])
def test_dead_reference_still_rejected_despite_assignment(row, reason):
    msg = _loader(row)._check_reference_active("e1abcA1")
    assert msg and reason in msg


def test_missing_reference_rejected():
    msg = _loader(None)._check_reference_active("e1abcA1")
    assert msg and "not present" in msg


def test_no_reference_id_allowed():
    assert _loader(None)._check_reference_active(None) is None
