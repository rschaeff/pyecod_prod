"""Seqid range check classes (validation/seqid_ranges.py)."""

import pytest

from pyecod_prod.validation.seqid_ranges import classify, parse_segments

# Chain A: 30-residue construct, seq_ids 11-30 modeled. Chain B: 10 residues, all modeled.
CONSTRUCT_A = "M" * 10 + "K" * 20
SCHEMES = {
    "A": (CONSTRUCT_A, set(range(11, 31))),
    "B": ("G" * 10, set(range(1, 11))),
}
MODELED_A = "K" * 20       # what the buggy parser searched with


@pytest.mark.parametrize("rng,expected", [
    ("A:1-50", [("A", 1, 50)]),
    ("A:1-10,B:3-9", [("A", 1, 10), ("B", 3, 9)]),
    ("A:-4-10", None),         # author-style negative numbering is not seqid
    ("A:10-5", None),
    ("1-50", None),
    ("", None),
])
def test_parse_segments(rng, expected):
    assert parse_segments(rng) == expected


def test_ok():
    assert classify("A:11-30", "A", CONSTRUCT_A, SCHEMES) == "ok"


def test_query_was_modeled_residues():
    # The bug: ranges partitioned against the 20 modeled residues; A:1-20 still parses,
    # stays within the construct and even overlaps coordinates, but is shifted by 10.
    assert classify("A:1-20", "A", MODELED_A, SCHEMES) == "query_not_construct"


def test_unobserved():
    assert classify("A:1-10", "A", CONSTRUCT_A, SCHEMES) == "unobserved"


def test_beyond_construct():
    assert classify("A:20-31", "A", CONSTRUCT_A, SCHEMES) == "beyond_construct"


def test_chain_missing():
    assert classify("C:1-5", "C", None, SCHEMES) == "chain_missing"


def test_bad_range():
    assert classify("A:-1-5", "A", CONSTRUCT_A, SCHEMES) == "bad_range"


def test_no_query_is_reported_not_failed():
    assert classify("A:11-30", "A", None, SCHEMES) == "no_query"


def test_multichain_domain():
    assert classify("A:11-30,B:1-10", "A-B", None, SCHEMES) == "multichain"
    assert classify("A:1-10,A:2-5", "A-B", None, SCHEMES) == "unobserved"
