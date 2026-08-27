"""Regression tests for repair item 5 -- non-F-group values reaching f_group_id.

Two production runs (2026-03-29, 2026-06-11) wrote 78 domains whose
``ecod_commons.f_group_assignments.f_group_id`` held something that is not an F-group:
17 distinct T-group ids across 27 domains, and 20 protein accessions across 51. The
cause was a consumer mapping pyecod_mini's ``get_domain_family_name`` -- a *provenance*
label -- straight into ``f_group_id``. Nothing validated the shape, so it surfaced
months later in the hierarchy generator rather than at write time.

Every malformed value used here is one that was actually found in the database, not an
invented example. The T-group ids and accessions come from
/data/ecod/database_versions/v295/HIERARCHY_REPAIR_LIST.md item 5.

The important test in this file is not the validator's return value -- it is
``test_malformed_f_group_routes_to_t_group_only``, which asserts the *behaviour the fix
claims*: a domain carrying a malformed f_group is recorded as topology-only and NOTHING
is written to f_group_assignments.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pyecod_prod.database.group_ids import clean_f_group, is_f_group


# The 20 protein accessions actually found in f_group_id (repair item 5 half B).
REAL_BAD_ACCESSIONS = [
    "EPP00001216", "EPP00002195", "EPP00002397", "EPP00011145", "EPP00017778",
    "EPP00017914", "EPP00019451", "EPP00021323", "EPP00021430", "EPP00021816",
    "EPP00022109", "EPP00026032", "EPP00027137", "EPP00028041", "EPP00028398",
    "EPP00028687",
    "JACRDV010000115.1", "JAHQJS010000004.1", "JAHQJS010000006.1", "JAHQJS010000007.1",
]

# T-group ids actually found in f_group_id (repair item 5 half A).
REAL_BAD_T_GROUPS = ["101.1.9", "2004.1.1", "4275.1.1", "101.1.2", "11.2.1"]

# Values that MUST keep working. The topology-only form is a legitimate f_group_id in
# ecod_commons -- rejecting it would break the very records the fix routes domains to.
VALID_F_GROUPS = ["2004.1.1.1", "1.1.2.7", "109.4.1.2529", "327.11.2.86", "2004.1.1.0"]


class TestValidatorContract:
    @pytest.mark.parametrize("acc", REAL_BAD_ACCESSIONS)
    def test_real_protein_accessions_are_rejected(self, acc):
        assert is_f_group(acc) is False
        assert clean_f_group(acc, context="test", log=MagicMock()) is None

    @pytest.mark.parametrize("t_group", REAL_BAD_T_GROUPS)
    def test_real_t_group_ids_are_rejected(self, t_group):
        assert is_f_group(t_group) is False
        assert clean_f_group(t_group, context="test", log=MagicMock()) is None

    @pytest.mark.parametrize("f_group", VALID_F_GROUPS)
    def test_valid_f_groups_pass_through_unchanged(self, f_group):
        assert is_f_group(f_group) is True
        assert clean_f_group(f_group, context="test", log=MagicMock()) == f_group

    def test_topology_only_form_is_accepted(self):
        """<x>.<h>.<t>.0 is what the fix routes unknown-family domains to.

        If this ever starts failing, the fix eats its own output.
        """
        assert clean_f_group("2004.1.1.0", context="test", log=MagicMock()) == "2004.1.1.0"

    def test_none_passes_through_silently(self):
        """None means 'no F-group', which is legitimate and must not be logged as a bug."""
        log = MagicMock()
        assert clean_f_group(None, context="test", log=log) is None
        log.error.assert_not_called()

    def test_rejection_is_logged_loudly(self):
        """A silent drop would reproduce the original failure mode: wrong data, no signal."""
        log = MagicMock()
        clean_f_group("EPP00001216", context="9k4j_C domain 1", log=log)
        log.error.assert_called_once()
        msg = log.error.call_args[0][0]
        assert "EPP00001216" in msg
        assert "9k4j_C domain 1" in msg

    @pytest.mark.parametrize("value", ["", "unclassified", "e9k4jC1", "2004", "2004.1",
                                       "2004.1.1.1.1", "a", "2004.1.1.x"])
    def test_other_non_group_shapes_are_rejected(self, value):
        """'unclassified' and a domain id are the other two things
        get_domain_family_name can return."""
        assert clean_f_group(value, context="test", log=MagicMock()) is None


class _RecordingCursor:
    """Captures executed SQL so the test can assert which table was written."""

    def __init__(self, uid=999999, domain_db_id=12345):
        self.executed: list[tuple[str, tuple]] = []
        self._uid = uid
        self._domain_db_id = domain_db_id

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return (self._domain_db_id,)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def tables_inserted(self) -> list[str]:
        out = []
        for sql, _ in self.executed:
            low = sql.lower()
            if "insert into" in low:
                out.append(low.split("insert into", 1)[1].split("(")[0].strip())
        return out

    def params_for(self, table: str):
        for sql, params in self.executed:
            if f"insert into {table}" in sql.lower():
                return params
        return None


@pytest.fixture
def loader_with_recording_cursor(monkeypatch):
    """An AutoAccessionLoader stubbed down to the insert block.

    Everything before the insert -- range checks, overlap detection, protein lookup,
    uid allocation -- is stubbed, because none of it is under test here. What is under
    test is which table the f_group value routes the insert to.
    """
    from pyecod_prod.database import auto_accession as aa

    cursor = _RecordingCursor()
    conn = MagicMock()
    conn.cursor.return_value = cursor

    loader = aa.AutoAccessionLoader.__new__(aa.AutoAccessionLoader)
    loader.dry_run = False
    loader.defer_moderate_overlaps = False
    loader.allow_unknown_range_type = True
    loader._domain_id_cache = {}
    loader._reference_cache = {}
    loader.overlap_checker = MagicMock()
    loader.overlap_checker.can_auto_accession.return_value = (True, [])

    monkeypatch.setattr(loader, "_get_connection", lambda: conn, raising=False)
    monkeypatch.setattr(loader, "_check_ranges", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(loader, "_check_reference_active", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(loader, "_get_existing_domain_by_id", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(loader, "_generate_domain_id", lambda p, c, n: f"e{p}{c}{n}", raising=False)
    monkeypatch.setattr(loader, "_find_available_domain_id",
                        lambda *a, **k: (f"e{a[0]}{a[1]}{a[2]}", False), raising=False)
    monkeypatch.setattr(loader, "_get_or_create_protein", lambda *a, **k: 4242, raising=False)
    monkeypatch.setattr(loader, "_get_next_uid", lambda *a, **k: 999999, raising=False)
    return loader, cursor


class TestInsertRouting:
    """The behaviour the fix actually claims."""

    def _accession(self, loader, f_group):
        return loader.accession_domain(
            pdb_id="9k4j", chain_id="C", range_definition="C:10-150", domain_num=1,
            t_group="2004.1.1", h_group="2004.1", x_group="2004",
            f_group=f_group, range_type="author", pdb_range="C:10-150",
        )

    @pytest.mark.parametrize("bad", ["EPP00001216", "JAHQJS010000004.1", "101.1.9"])
    def test_malformed_f_group_routes_to_t_group_only(self, loader_with_recording_cursor, bad):
        """The core regression: a malformed value must NOT reach f_group_assignments.

        Before the fix this wrote f_group_id='EPP00001216'. After it, the domain is
        recorded as topology-only and f_group_assignments is never touched.
        """
        loader, cursor = loader_with_recording_cursor
        self._accession(loader, bad)

        tables = cursor.tables_inserted()
        assert any("t_group_only_assignments" in t for t in tables), (
            f"expected a t_group_only_assignments insert for {bad!r}, got {tables}")
        assert not any("f_group_assignments" in t for t in tables), (
            f"{bad!r} reached f_group_assignments -- item 5 has regressed")

    def test_valid_f_group_still_reaches_f_group_assignments(self, loader_with_recording_cursor):
        """The fix must not suppress legitimate F-group assignments."""
        loader, cursor = loader_with_recording_cursor
        self._accession(loader, "2004.1.1.1")

        tables = cursor.tables_inserted()
        assert any("f_group_assignments" in t for t in tables), tables
        assert not any("t_group_only_assignments" in t for t in tables), tables
        assert "2004.1.1.1" in cursor.params_for("ecod_commons.f_group_assignments")

    def test_topology_only_f_group_is_written_as_an_f_group(self, loader_with_recording_cursor):
        """<t>.0 is a real f_group_id, not a malformed one -- it belongs in the F table."""
        loader, cursor = loader_with_recording_cursor
        self._accession(loader, "2004.1.1.0")

        params = cursor.params_for("ecod_commons.f_group_assignments")
        assert params is not None, cursor.tables_inserted()
        assert "2004.1.1.0" in params

    def test_no_f_group_at_all_routes_to_t_group_only(self, loader_with_recording_cursor):
        """The ordinary unknown-family case, unchanged by the fix."""
        loader, cursor = loader_with_recording_cursor
        self._accession(loader, None)

        tables = cursor.tables_inserted()
        assert any("t_group_only_assignments" in t for t in tables), tables
        assert not any("f_group_assignments" in t for t in tables), tables


# ---------------------------------------------------------------- inheritance path

class _SequencedCursor(_RecordingCursor):
    """Returns a queue of fetchone() values, for the multi-step propagation path."""

    def __init__(self, results):
        super().__init__()
        self._results = list(results)

    def fetchone(self):
        return self._results.pop(0) if self._results else (1,)


def _rep_domain(f_group, t_group="2004.1.1"):
    """A representative row shaped as propagate_to_member expects."""
    return {
        "id": 111, "ecod_uid": 222, "domain_id": "e9k4jC1",
        "range_definition": "C:10-150", "range_type": "seqid",
        "is_discontinuous": False, "confidence": 0.9,
        "f_group": f_group, "t_group": t_group, "h_group": "2004.1", "x_group": "2004",
        "sequence_length": 141, "pdb_range": "C:10-150",
    }


@pytest.fixture
def propagator_with_recording_cursor(monkeypatch):
    from pyecod_prod.database import cluster_propagation as cp

    # protein lookup hit, then uid, then domain insert id -- enough for one member domain
    cursor = _SequencedCursor([(4242,), (999999,), (12345,)])
    conn = MagicMock()
    conn.cursor.return_value = cursor

    prop = cp.ClusterPropagator.__new__(cp.ClusterPropagator)
    prop.dry_run = False
    monkeypatch.setattr(prop, "_get_connection", lambda: conn, raising=False)
    return prop, cursor, cp


class TestInheritanceRouting:
    """26 of the 51 bad rows were inheritance copying a malformed value off a rep.

    Guarding only the blast path would have left the larger half of the defect intact,
    so this is not redundant with TestInsertRouting.
    """

    def _propagate(self, prop, cp, rep_domains):
        return prop.propagate_to_member(
            member_pdb_id="9k4t", member_chain_id="A",
            rep_domains=rep_domains, domain_version="v295",
            tier=list(cp.PropagationTier)[0],
        )

    @pytest.mark.parametrize("bad", ["EPP00022109", "JACRDV010000115.1", "2004.1.1"])
    def test_bad_rep_value_is_not_propagated(self, propagator_with_recording_cursor, bad):
        """A representative carrying garbage must not spread it to every cluster member."""
        prop, cursor, cp = propagator_with_recording_cursor
        self._propagate(prop, cp, [_rep_domain(bad)])

        tables = cursor.tables_inserted()
        assert not any("f_group_assignments" in t for t in tables), (
            f"rep value {bad!r} propagated into f_group_assignments -- item 5 has regressed")
        assert any("t_group_only_assignments" in t for t in tables), tables

    def test_good_rep_value_still_propagates(self, propagator_with_recording_cursor):
        prop, cursor, cp = propagator_with_recording_cursor
        self._propagate(prop, cp, [_rep_domain("2004.1.1.1")])

        params = cursor.params_for("ecod_commons.f_group_assignments")
        assert params is not None, cursor.tables_inserted()
        assert "2004.1.1.1" in params
