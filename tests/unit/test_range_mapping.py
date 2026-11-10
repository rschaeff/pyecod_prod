"""Propagated ranges must be mapped onto the member, not relabelled.

Before 2026-11, ClusterPropagator copied the rep's seqid range onto the member with
only the chain letter changed, and wrote that same seqid range into domain_ranges as
range_type 'pdb'. Both are wrong whenever the member's construct differs from the rep's
(tags, truncations) or author numbering differs from seqid (e.g. 9zl9 A: seqid 3-314 is
author 1079-1390).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pyecod_prod.database import cluster_propagation as cp  # noqa: E402
from pyecod_prod.database.range_mapping import (  # noqa: E402
    ChainScheme,
    RangeMapper,
    RangeMappingError,
    align_positions,
    map_domain_range,
    read_poly_seq_scheme,
)

SEQ = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKRQTLGQHDFSAGEGLYTHMKALRPDEDRLSPLHSVYVDQWDWERVMGDGERQFSTLKSTVEAIWAGIKATEAAVSEEFGLAPFLPDQIHFVHSQELLSRYPDLDAKGRERAIAKDLGAVFLVGIGGKLSDGHRHDVRAPDYDDWUAQYRRP"


def _scheme(seq, first_author=1, ins=None, unobserved=()):
    """ChainScheme with author numbers first_author.. and optional insertion codes."""
    author = {i: str(first_author + i - 1) for i in range(1, len(seq) + 1)}
    for sid, code in (ins or {}).items():
        author[sid] = code
    observed = set(range(1, len(seq) + 1)) - set(unobserved)
    return ChainScheme(sequence=seq, author=author, observed=observed)


class TestAlign:
    def test_identical_sequences_map_one_to_one(self):
        m = align_positions(SEQ, SEQ)
        assert m[1] == 1 and m[len(SEQ)] == len(SEQ)

    def test_n_terminal_tag_shifts_positions(self):
        member = "MGSSHHHHHHSSG" + SEQ  # 13-residue His tag
        m = align_positions(SEQ, member)
        assert m[1] == 14 and m[100] == 113

    def test_truncated_member(self):
        member = SEQ[20:]
        m = align_positions(SEQ, member)
        assert 20 not in m and m[21] == 1


class TestMapDomainRange:
    def test_tagged_member_gets_shifted_seqid_and_its_own_author_numbers(self):
        member_seq = "MGSSHHHHHHSSG" + SEQ
        member = _scheme(member_seq, first_author=-12)  # tag numbered -12..0
        pos = align_positions(SEQ, member_seq)

        seqid, author = map_domain_range("A:10-150", pos, "B", member)

        assert seqid == "B:23-163"
        assert author == "B:10-150"

    def test_author_offset_is_not_mistaken_for_seqid(self):
        """9zl9-style: same sequence, author numbering starts at 1077."""
        member = _scheme(SEQ, first_author=1077)
        pos = align_positions(SEQ, SEQ)
        seqid, author = map_domain_range("A:3-200", pos, "B", member)
        assert seqid == "B:3-200"
        assert author == "B:1079-1276"

    def test_insertion_codes_are_kept(self):
        member = _scheme(SEQ, ins={10: "52A"})
        pos = align_positions(SEQ, SEQ)
        _, author = map_domain_range("A:10-50", pos, "B", member)
        assert author == "B:52A-50"

    def test_discontinuous_range_maps_each_segment(self):
        member_seq = "MGS" + SEQ
        member = _scheme(member_seq)
        pos = align_positions(SEQ, member_seq)
        seqid, _ = map_domain_range("A:10-50,A:100-150", pos, "B", member)
        assert seqid == "B:13-53,B:103-153"

    def test_under_covered_domain_is_rejected(self):
        member_seq = SEQ[60:]  # loses most of a 10-80 domain
        member = _scheme(member_seq)
        pos = align_positions(SEQ, member_seq)
        with pytest.raises(RangeMappingError, match="aligns"):
            map_domain_range("A:10-80", pos, "B", member)

    def test_missing_segment_is_rejected(self):
        member_seq = SEQ[:90]
        member = _scheme(member_seq)
        pos = align_positions(SEQ, member_seq)
        with pytest.raises(RangeMappingError):
            map_domain_range("A:10-80,A:150-200", pos, "B", member)

    def test_unmodeled_range_is_rejected(self):
        member = _scheme(SEQ, unobserved=range(1, 60))
        pos = align_positions(SEQ, SEQ)
        with pytest.raises(RangeMappingError, match="modeled"):
            map_domain_range("A:10-50", pos, "B", member)

    def test_bad_range_is_rejected(self):
        with pytest.raises(RangeMappingError):
            map_domain_range("A:50-10", {}, "B", _scheme(SEQ))


CIF = """data_TEST
#
loop_
_pdbx_poly_seq_scheme.asym_id
_pdbx_poly_seq_scheme.entity_id
_pdbx_poly_seq_scheme.seq_id
_pdbx_poly_seq_scheme.mon_id
_pdbx_poly_seq_scheme.ndb_seq_num
_pdbx_poly_seq_scheme.pdb_seq_num
_pdbx_poly_seq_scheme.auth_seq_num
_pdbx_poly_seq_scheme.pdb_mon_id
_pdbx_poly_seq_scheme.auth_mon_id
_pdbx_poly_seq_scheme.pdb_strand_id
_pdbx_poly_seq_scheme.pdb_ins_code
_pdbx_poly_seq_scheme.hetero
A 1 1 MET 1 99  ?   . . A . n
A 1 2 MSE 2 100 100 MSE MSE A . n
A 1 3 GLY 3 100 100 GLY GLY A A n
A 1 4 LYS 4 101 101 LYS LYS A . n
#
_atom_site.group_PDB
"""


def test_read_poly_seq_scheme(tmp_path):
    path = tmp_path / "test.cif"
    path.write_text(CIF)
    ch = read_poly_seq_scheme(str(path))["A"]
    assert ch.sequence == "MMGK"
    assert ch.author == {1: "99", 2: "100", 3: "100A", 4: "101"}
    assert ch.observed == {2, 3, 4}


def test_mapper_reports_missing_mmcif():
    def locate(pdb_id):
        raise FileNotFoundError(pdb_id)
    with pytest.raises(RangeMappingError, match="no mmCIF"):
        RangeMapper(locate).chain("9xyz", "A")


class TestPropagatorUsesMappedRanges:
    REP = {
        "id": 111, "ecod_uid": 222, "domain_id": "e9abcA1", "range_definition": "A:10-150",
        "is_discontinuous": False, "confidence": 0.9, "representative_domain_id": None,
        "f_group": "2004.1.1.1", "t_group": "2004.1.1", "h_group": "2004.1",
        "x_group": "2004", "representative_uid": None,
    }

    def test_seqid_goes_to_domains_and_author_to_domain_ranges(self):
        executed = []
        cursor = MagicMock()
        cursor.execute.side_effect = lambda sql, params=None: executed.append((sql, params))
        cursor.fetchone.side_effect = [(4242,), (0,), (999999,), (12345,)]
        conn = MagicMock()
        conn.cursor.return_value = cursor
        prop = cp.ClusterPropagator(dry_run=False, range_mapper=MagicMock())
        prop._get_connection = lambda: conn
        prop._get_version_id = lambda *a, **k: 1

        result = prop.propagate_to_member(
            "9xyz", "B", [self.REP], "v_test", cp.PropagationTier.TIER1_AUTO,
            member_ranges=[("B:23-163", "B:1088-1228")])

        assert result.success, result.message
        dom = next(p for s, p in executed if "INSERT INTO ecod_commons.domains" in s)
        rng = next(p for s, p in executed if "INSERT INTO ecod_commons.domain_ranges" in s)
        assert "B:23-163" in dom
        assert rng == (12345, "B:1088-1228")

    def test_unmappable_member_gets_no_domains(self, monkeypatch):
        cursor = MagicMock()
        cursor.fetchone.return_value = (141,)
        conn = MagicMock()
        conn.cursor.return_value = cursor
        mapper = MagicMock()
        mapper.map_member.side_effect = RangeMappingError("only 40% aligns")
        prop = cp.ClusterPropagator(dry_run=False, range_mapper=mapper)
        prop._get_connection = lambda: conn
        monkeypatch.setattr(prop, "get_representative_domains", lambda *a: [self.REP])
        monkeypatch.setattr(prop, "get_cluster_members", lambda *a: [
            {"pdb_id": "9xyz", "chain_id": "B", "sequence_length": 141,
             "ecod_status": "not_in_ecod"}])
        monkeypatch.setattr(prop, "get_chains_with_domains", lambda chains: {})
        monkeypatch.setattr(prop, "propagate_to_member",
                            MagicMock(side_effect=AssertionError("must not write")))

        [r] = prop.propagate_from_representative("9abc", "A", "v_test")

        assert r.tier is cp.PropagationTier.RANGE_UNMAPPABLE
        assert not r.success and "40%" in r.message
