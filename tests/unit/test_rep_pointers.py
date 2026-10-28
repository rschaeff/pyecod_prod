"""Representative pointers: domains.representative_domain_id must name the current rep of
the domain's own F-group, by ecod_commons.domains.id.

Regression for pdb_update_2026/docs/NOTE_2026-10-27_representative_pointers.md: auto-accession
left the pointer NULL on every new domain (the production path passed derived_from_uid=None),
and when derived_from_uid was given it wrote an ecod_uid into a domains.id column.
"""

from unittest.mock import MagicMock

import pytest

from pyecod_prod.database.rep_pointers import (
    FGroupRepResolver,
    classify,
    is_topology_only,
    reset_rep_pointers,
)

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
        ("EPP00022109", None, None, "not_f_group"),
    ])
    def test_classes(self, f, ptr, ptr_f, want):
        assert classify(f, ptr, ptr_f) == want

    def test_topology_only(self):
        assert is_topology_only("101.1.2.0") and not is_topology_only("101.1.2.10")


class _ResetCursor:
    """Returns canned target rows; records the UPDATE batch."""

    def __init__(self, rows):
        self.rows, self.updates = rows, None

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self.rows

    def executemany(self, sql, seq):
        self.updates = list(seq)

    def close(self):
        pass


class TestTargetSelection:
    """Who counts as a rep (and so is skipped) -- regression for former reps going unchecked."""

    def test_skips_only_reps_flagged_in_ecod_rep(self):
        from pyecod_prod.database.rep_pointers import _TARGET_SQL
        sql = " ".join(_TARGET_SQL.split())
        assert "x.manual_rep OR x.provisional_manual_rep" in sql
        where = sql.split(" WHERE ", 1)[1]
        assert "is_representative" not in where     # selected for reporting, never a filter


class TestReset:
    # (domain pk, domain_id, f_group, pointer, pointer's f_group, ecod_commons is_representative)
    ROWS = [
        (1, "a", "2004.1.1.1", None, None, False),           # NULL          -> set
        (2, "b", "2004.1.1.1", 900, "2004.1.1.7", False),    # other F       -> set
        (3, "c", "2004.1.1.1", 901, "2004.1.1.1", False),    # same F        -> kept
        (4, "d", "2004.1.1.0", None, None, False),           # .0            -> untouched
        (5, "e", "EPP00022109", None, None, False),          # not F         -> untouched
        (6, "f", "2004.1.1.9", None, None, False),           # F has no rep  -> no_rep
        (7, "g", "2004.1.1.1", None, None, True),            # commons-only rep -> skipped
    ]

    def _run(self, dry_run):
        cur = _ResetCursor(list(self.ROWS))
        conn = MagicMock()
        conn.cursor.return_value = cur
        resolver, _ = _resolver([("2004.1.1.1", 11, False, 500)])
        counts = reset_rep_pointers(conn, resolver, dry_run=dry_run, domain_ids=[1])
        return counts, cur, conn

    def test_only_null_and_out_of_f_pointers_change(self):
        counts, cur, conn = self._run(dry_run=False)
        assert counts == {"kept": 1, "set": 2, "no_rep": 1, "commons_only_rep": 1, "dot0": 1,
                          "not_f_group": 1}
        assert cur.updates == [(11, 1), (11, 2)]
        conn.commit.assert_called_once()

    def test_dry_run_writes_nothing(self):
        counts, cur, conn = self._run(dry_run=True)
        assert counts["set"] == 2 and cur.updates is None
        conn.commit.assert_not_called()

    def test_check_labels_commons_only_rep(self):
        from pyecod_prod.database.rep_pointers import check_rep_pointers
        cur = _ResetCursor(list(self.ROWS))
        conn = MagicMock()
        conn.cursor.return_value = cur
        counts, fails = check_rep_pointers(conn, domain_ids=[1])
        assert counts["commons_only_rep"] == 1 and counts["no_pointer"] == 2
        assert [f[4] for f in fails if f[0] == 7] == ["commons_only_rep"]

    def test_selection_required(self):
        with pytest.raises(ValueError):
            reset_rep_pointers(MagicMock(), MagicMock())


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
