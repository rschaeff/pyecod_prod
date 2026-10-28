"""Representative pointers: domains.representative_domain_id must name the current rep of
the domain's own F-group, by ecod_commons.domains.id.

Regression for pdb_update_2026/docs/NOTE_2026-10-27_representative_pointers.md: auto-accession
left the pointer NULL on every new domain (the production path passed derived_from_uid=None),
and when derived_from_uid was given it wrote an ecod_uid into a domains.id column.
"""

from unittest.mock import MagicMock

import pytest

from pyecod_prod.database.rep_pointers import FGroupRepResolver, classify, is_topology_only

from test_f_group_id_validation import (  # noqa: F401  (fixtures)
    TEST_REP_DOMAIN_ID,
    TestInsertRouting as _InsertRouting,  # aliased so pytest doesn't re-collect
    loader_with_recording_cursor,
)


class _Cursor:
    """Answers the resolver's two queries from canned rows and counts round trips."""

    def __init__(self, reps, votes):
        self.reps, self.votes, self.calls, self._last = reps, votes, [], None

    def execute(self, sql, params=None):
        self.calls.append(params)
        self._last = "votes" if "count(*)" in sql else "reps"

    def fetchall(self):
        return self.votes if self._last == "votes" else self.reps

    def close(self):
        pass


def _resolver(reps, votes=()):
    cur = _Cursor(list(reps), list(votes))
    conn = MagicMock()
    conn.cursor.return_value = cur
    return FGroupRepResolver(lambda: conn), cur


class TestResolver:
    def test_single_rep(self):
        r, _ = _resolver([("2004.1.1.1", 11, False, 500)])
        assert r.rep_for("2004.1.1.1") == 11

    def test_topology_only_and_missing_get_none(self):
        r, cur = _resolver([("2004.1.1.1", 11, False, 500)])
        assert r.rep_for("2004.1.1.0") is None
        assert r.rep_for(None) is None
        assert cur.calls == []                      # no query for .0 / None
        assert r.rep_for("2004.1.1.9") is None      # no rep filed in it

    def test_several_reps_most_votes_wins(self):
        r, _ = _resolver([("5.1.4.1", 21, True, 100), ("5.1.4.1", 22, False, 200)],
                         votes=[(21, 3), (22, 40)])
        assert r.rep_for("5.1.4.1") == 22

    def test_tie_goes_to_manual_then_lowest_uid(self):
        r, _ = _resolver([("5.1.4.1", 21, False, 100), ("5.1.4.1", 22, True, 200),
                          ("5.1.4.1", 23, True, 150)])
        assert r.rep_for("5.1.4.1") == 23

    def test_reps_loaded_once_and_choice_cached(self):
        r, cur = _resolver([("2004.1.1.1", 11, False, 500), ("2004.1.1.2", 12, False, 501)])
        r.rep_for("2004.1.1.1")
        r.rep_for("2004.1.1.1")
        r.rep_for("2004.1.1.2")
        assert len(cur.calls) == 1


class TestClassify:
    @pytest.mark.parametrize("f, ptr, ptr_f, want", [
        ("2004.1.1.1", 5, "2004.1.1.1", "ok"),
        ("2004.1.1.1", None, None, "no_pointer"),
        ("2004.1.1.1", 5, "2004.1.1.7", "cross_f"),
        ("2004.1.1.1", 5, "2004.1.2.3", "cross_f"),   # same H, other T
        ("2004.1.1.1", 5, "2005.1.1.1", "cross_h"),
        ("2004.1.1.0", None, None, "dot0"),
    ])
    def test_classes(self, f, ptr, ptr_f, want):
        assert classify(f, ptr, ptr_f) == want

    def test_topology_only(self):
        assert is_topology_only("101.1.2.0") and not is_topology_only("101.1.2.10")


class TestAccessionWritesPointer:
    def _domains_params(self, cursor):
        params = cursor.params_for("ecod_commons.domains")
        assert params is not None, cursor.tables_inserted()
        return params

    def test_real_f_group_gets_current_rep(self, loader_with_recording_cursor):
        loader, cursor = loader_with_recording_cursor
        _InsertRouting()._accession(loader, "2004.1.1.1")
        assert TEST_REP_DOMAIN_ID in self._domains_params(cursor)

    def test_derived_from_uid_is_not_written_as_domain_pointer(self, loader_with_recording_cursor):
        """An ecod_uid must never land in representative_domain_id (a domains.id column)."""
        loader, cursor = loader_with_recording_cursor
        loader.accession_domain(
            pdb_id="9k4j", chain_id="C", range_definition="C:10-150", domain_num=1,
            t_group="2004.1.1", h_group="2004.1", x_group="2004", f_group="2004.1.1.1",
            derived_from_uid=5340001, range_type="author", pdb_range="C:10-150",
        )
        assert 5340001 not in self._domains_params(cursor)
        assert TEST_REP_DOMAIN_ID in self._domains_params(cursor)
        assert 5340001 in cursor.params_for("ecod_commons.f_group_assignments")

    @pytest.mark.parametrize("f_group", [None, "EPP00001216"])
    def test_topology_only_gets_no_pointer(self, loader_with_recording_cursor, f_group):
        loader, cursor = loader_with_recording_cursor
        _InsertRouting()._accession(loader, f_group)
        assert TEST_REP_DOMAIN_ID not in self._domains_params(cursor)
