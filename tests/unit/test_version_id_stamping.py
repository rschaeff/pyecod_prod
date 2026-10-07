"""version_id must be stamped on every domain and assignment row pyecod_prod inserts.

Regression for active_issues/2026-10-06_pyecod_prod_version_id.md: rows inserted with
version_id NULL vanished from ecod_commons.current_ecod, which inner-joins versions.
f_group_assignments now rejects NULL (fga_version_id_not_null); domains and
t_group_only_assignments have no such guard, so these tests are their only one.
"""

from unittest.mock import MagicMock

import pytest

from pyecod_prod.database.versions import (
    NoDevelopmentReleaseError,
    current_development_version_id,
)

from test_f_group_id_validation import (  # noqa: F401  (fixtures)
    TEST_VERSION_ID,
    TestInheritanceRouting as _InheritanceRouting,  # aliased so pytest doesn't re-collect
    TestInsertRouting as _InsertRouting,
    _rep_domain,
    loader_with_recording_cursor,
    propagator_with_recording_cursor,
)

STAMPED_TABLES = (
    "ecod_commons.domains",
    "ecod_commons.f_group_assignments",
    "ecod_commons.t_group_only_assignments",
)


def _assert_stamped(cursor):
    seen = 0
    for sql, params in cursor.executed:
        low = sql.lower()
        for table in STAMPED_TABLES:
            if f"insert into {table} " in low or f"insert into {table}(" in low:
                seen += 1
                cols = low.split("(", 1)[1].split(")", 1)[0]
                assert "version_id" in cols, f"{table} insert omits version_id: {sql}"
                assert TEST_VERSION_ID in params, f"{table} insert not given version_id"
    assert seen >= 2, cursor.tables_inserted()


class TestAutoAccessionStampsVersion:
    @pytest.mark.parametrize("f_group", ["2004.1.1.1", None])
    def test_all_inserts_carry_version_id(self, loader_with_recording_cursor, f_group):
        loader, cursor = loader_with_recording_cursor
        _InsertRouting()._accession(loader, f_group)
        _assert_stamped(cursor)


class TestPropagationStampsVersion:
    @pytest.mark.parametrize("f_group", ["2004.1.1.1", "EPP00022109"])
    def test_all_inserts_carry_version_id(self, propagator_with_recording_cursor, f_group):
        prop, cursor, cp = propagator_with_recording_cursor
        _InheritanceRouting()._propagate(prop, cp, [_rep_domain(f_group)])
        _assert_stamped(cursor)


def _conn_returning(row):
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


class TestResolveVersion:
    def test_returns_versions_id_of_current_development_release(self):
        assert current_development_version_id(_conn_returning(("v295.2", 7, 7))) == 7

    def test_no_development_release_raises(self):
        with pytest.raises(NoDevelopmentReleaseError):
            current_development_version_id(_conn_returning(None))

    def test_release_without_versions_row_raises(self):
        with pytest.raises(NoDevelopmentReleaseError, match="v296"):
            current_development_version_id(_conn_returning(("v296", None, None)))
