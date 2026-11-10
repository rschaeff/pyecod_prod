"""Cluster propagation must be safe to rerun.

Before this fix, ClusterPropagator skipped a member only when
pdb_update.chain_status.ecod_status == 'in_current_ecod'. That flag is stale, and
nothing checked ecod_commons for existing domains, so a 2026-11-10 dry-run showed a
rerun of q3_2026_v294_2 would have re-inserted all 2,187 already-propagated chains,
and a q2_2026_v294 run would have doubled 1,186 chains that had develop294 domains.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pyecod_prod.database import cluster_propagation as cp  # noqa: E402


class _QueueCursor:
    """Records SQL; fetchone() pops from a queue, fetchall() returns a fixed list."""

    def __init__(self, fetchone=(), fetchall=()):
        self.executed: list[str] = []
        self._one = list(fetchone)
        self._all = list(fetchall)

    def execute(self, sql, params=None):
        self.executed.append(" ".join(sql.split()))

    def fetchone(self):
        return self._one.pop(0) if self._one else (1,)

    def fetchall(self):
        return self._all

    def close(self):
        pass

    def inserts(self) -> list[str]:
        return [s for s in self.executed if s.upper().startswith("INSERT")]


def _propagator(cursor, dry_run=False):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    prop = cp.ClusterPropagator(dry_run=dry_run)
    prop._get_connection = lambda: conn
    prop._get_version_id = lambda *a, **k: 1
    return prop, conn


REP_DOMAIN = {
    "id": 111, "ecod_uid": 222, "domain_id": "e9abcA1", "range_definition": "A:1-100",
    "is_discontinuous": False, "confidence": 0.9, "representative_domain_id": None,
    "f_group": "2004.1.1.1", "t_group": "2004.1.1", "h_group": "2004.1",
    "x_group": "2004", "representative_uid": None,
}


class TestPropagateToMember:
    def test_member_with_active_domains_is_not_written(self):
        # protein found (id 4242), then 2 active domains already on the chain
        cursor = _QueueCursor(fetchone=[(4242,), (2,)])
        prop, conn = _propagator(cursor)

        result = prop.propagate_to_member(
            "9xyz", "B", [REP_DOMAIN], "v_test", cp.PropagationTier.TIER1_AUTO,
            member_ranges=[("B:1-100", "B:1-100")])

        assert result.tier is cp.PropagationTier.ALREADY_CLASSIFIED
        assert result.success and result.domains_propagated == 0
        assert cursor.inserts() == []
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_protein_row_is_locked_before_the_check(self):
        cursor = _QueueCursor(fetchone=[(4242,), (2,)])
        prop, _ = _propagator(cursor)
        prop.propagate_to_member(
            "9xyz", "B", [REP_DOMAIN], "v_test", cp.PropagationTier.TIER1_AUTO,
            member_ranges=[("B:1-100", "B:1-100")])
        assert "FOR UPDATE" in cursor.executed[0]

    def test_member_without_domains_is_written(self):
        # protein found, 0 existing domains, uid, domain insert id
        cursor = _QueueCursor(fetchone=[(4242,), (0,), (999999,), (12345,)])
        prop, conn = _propagator(cursor)

        result = prop.propagate_to_member(
            "9xyz", "B", [REP_DOMAIN], "v_test", cp.PropagationTier.TIER1_AUTO,
            member_ranges=[("B:1-100", "B:1-100")])

        assert result.success and result.domains_propagated == 1
        assert any("ecod_commons.domains" in s for s in cursor.inserts())
        conn.commit.assert_called_once()


class TestPropagateFromRepresentative:
    @pytest.fixture
    def prop(self, monkeypatch):
        # rep sequence_length lookup returns 100
        cursor = _QueueCursor(fetchone=[(100,)])
        prop, _ = _propagator(cursor, dry_run=True)
        monkeypatch.setattr(prop, "get_representative_domains", lambda *a: [REP_DOMAIN])
        monkeypatch.setattr(prop, "get_cluster_members", lambda *a: [
            # already has domains, flag says otherwise -> must be skipped
            {"pdb_id": "9aaa", "chain_id": "A", "sequence_length": 100,
             "ecod_status": "not_in_ecod"},
            # stale flag says classified but it has no domains -> must be propagated
            {"pdb_id": "9bbb", "chain_id": "A", "sequence_length": 100,
             "ecod_status": "in_current_ecod"},
        ])
        monkeypatch.setattr(prop, "get_chains_with_domains",
                            lambda chains: {("9aaa", "A"): 3})
        prop.range_mapper = MagicMock()
        prop.range_mapper.map_member.return_value = [("A:1-100", "A:1-100")]
        return prop

    def test_skips_on_existing_domains_not_on_status_flag(self, prop):
        results = {r.member_pdb_id: r for r in
                   prop.propagate_from_representative("9rep", "A", "v_test")}

        assert results["9aaa"].tier is cp.PropagationTier.ALREADY_CLASSIFIED
        assert results["9bbb"].tier is cp.PropagationTier.TIER1_AUTO
        assert results["9bbb"].domains_propagated == 1


def test_get_chains_with_domains_empty_input_skips_db():
    prop = cp.ClusterPropagator(dry_run=True)
    prop._get_connection = MagicMock(side_effect=AssertionError("should not connect"))
    assert prop.get_chains_with_domains([]) == {}
