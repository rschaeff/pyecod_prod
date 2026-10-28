"""Representative pointers: ``ecod_commons.domains.representative_domain_id``.

POLICY (2026-10-27): a non-representative domain's representative must be in the
domain's own F-group. The pointer references ``ecod_commons.domains.id`` -- NOT
``ecod_uid`` and NOT ``ecod_rep.domain.uid``. Read as ``domains.id``, 99.7% of legacy
pointers stay in the member's H-group; read as ``ecod_uid``, almost none do.

Exists because nothing maintained the pointer. Auto-accession left it NULL (14,318
auto-accessioned domains, through the Q4 2026 batch), and every later F-group change
(resolve_fgroups, Pfam passes, curation) left it stale: about 19% of domains pointed at a
rep in another F-group, and about 11,400 at one in another H-group. See
pdb_update_2026/docs/NOTE_2026-10-27_representative_pointers.md.

``f_group_assignments.representative_domain_ecod_uid`` is a different field: provenance
(the domain a label was derived or propagated from), by ``ecod_uid``. It is not touched here.

The current rep of an F-group is an ``ecod_rep.domain`` row with that ``f_id`` and
``manual_rep`` or ``provisional_manual_rep``, mapped to ``ecod_commons`` by ``ecod_uid``,
and only if the rep's own ``ecod_commons`` F-group is that F-group (the two schemas
disagree for some legacy reps; such a rep is not used). With several, the one most
members of the F-group already point at; ties go to manual reps, then lowest ecod_uid.
X.H.T.0 domains get no pointer from here: whether they should have one is unresolved.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Tuple

from .group_ids import is_f_group

logger = logging.getLogger(__name__)

# (f_id, domains.id, manual, ecod_uid) for every rep the two schemas agree on
_REPS_SQL = """
    SELECT rd.f_id, d.id, rd.manual_rep IS TRUE, d.ecod_uid
      FROM ecod_rep.domain rd
      JOIN ecod_commons.domains d ON d.ecod_uid = rd.ecod_uid AND NOT d.is_obsolete
      JOIN ecod_commons.f_group_assignments fa
        ON fa.domain_id = d.id AND fa.f_group_id = rd.f_id
     WHERE (rd.manual_rep OR rd.provisional_manual_rep) AND rd.f_id IS NOT NULL
"""

_VOTES_SQL = """
    SELECT m.representative_domain_id, count(*)
      FROM ecod_commons.f_group_assignments fa
      JOIN ecod_commons.domains m ON m.id = fa.domain_id AND NOT m.is_obsolete
     WHERE fa.f_group_id = %s AND m.representative_domain_id = ANY(%s)
     GROUP BY 1
"""


def is_topology_only(f_group: Optional[str]) -> bool:
    """X.H.T.0: a T-group placeholder, not a real F-group."""
    return bool(f_group) and f_group.endswith(".0")


class FGroupRepResolver:
    """Current rep (``ecod_commons.domains.id``) of each F-group, loaded once and cached.

    ``connect`` returns a DB-API connection; the resolver closes what it opens.
    """

    def __init__(self, connect: Callable):
        self._connect = connect
        self._reps: Optional[Dict[str, List[Tuple[int, bool, int]]]] = None
        self._chosen: Dict[str, Optional[int]] = {}

    def _query(self, fn) -> None:
        conn = self._connect()
        cur = conn.cursor()
        try:
            fn(cur)
        finally:
            cur.close()
            conn.close()

    def _load(self, cur) -> None:
        cur.execute(_REPS_SQL)
        reps: Dict[str, List[Tuple[int, bool, int]]] = {}
        for f_id, dom_pk, manual, uid in cur.fetchall():
            reps.setdefault(f_id, []).append((dom_pk, manual, uid))
        self._reps = reps
        logger.info("Loaded %d current reps in %d F-groups",
                    sum(len(v) for v in reps.values()), len(reps))

    def rep_for(self, f_group: Optional[str]) -> Optional[int]:
        """The rep's ``domains.id``, or None for X.H.T.0, a non-F-group value or no usable rep."""
        if not is_f_group(f_group) or is_topology_only(f_group):
            return None
        if f_group in self._chosen:
            return self._chosen[f_group]
        if self._reps is None:
            self._query(self._load)
        cands = self._reps.get(f_group, [])
        votes: Dict[int, int] = {}
        if len(cands) > 1:     # only then is a round trip needed
            def _votes(cur):
                cur.execute(_VOTES_SQL, (f_group, [c[0] for c in cands]))
                votes.update(cur.fetchall())
            self._query(_votes)
        chosen = None
        if cands:
            chosen = min(cands, key=lambda c: (-votes.get(c[0], 0), not c[1], c[2]))[0]
        else:
            logger.warning("F-group %s has no current rep filed in it; pointer left NULL", f_group)
        self._chosen[f_group] = chosen
        return chosen


# Non-rep, non-obsolete domains with their F-group and current pointer (+ the pointer's F-group).
# "Rep" means flagged in ecod_rep (manual_rep / provisional_manual_rep), the same test the resolver
# uses. Not merely having an ecod_rep.domain row: a demoted or replaced rep keeps its row with the
# flag cleared and is an ordinary member (978 such domains, 424 with a NULL or out-of-F pointer, were
# invisible to the check). Not ecod_commons.domains.is_representative either: it disagrees with
# ecod_rep both ways (1,271 set without an ecod_rep flag, 3,575 flagged reps without it; 2026-10-28).
_TARGET_SQL = """
    SELECT m.id, m.domain_id, fa.f_group_id, m.representative_domain_id, rfa.f_group_id
      FROM ecod_commons.domains m
      JOIN ecod_commons.f_group_assignments fa ON fa.domain_id = m.id
      LEFT JOIN ecod_commons.f_group_assignments rfa ON rfa.domain_id = m.representative_domain_id
     WHERE NOT m.is_obsolete
       AND NOT EXISTS (SELECT 1 FROM ecod_rep.domain x WHERE x.ecod_uid = m.ecod_uid
                         AND (x.manual_rep OR x.provisional_manual_rep))
       AND {where}
"""


def _where(uid_range=None, assigned_by=None, assigned_since=None, domain_ids=None):
    where, params = [], []
    if uid_range:
        where.append("m.ecod_uid BETWEEN %s AND %s")
        params += list(uid_range)
    if assigned_by:
        where.append("fa.assigned_by LIKE %s")
        params.append(assigned_by)
    if assigned_since:
        where.append("fa.assignment_date >= %s")
        params.append(assigned_since)
    if domain_ids is not None:
        where.append("m.id = ANY(%s)")
        params.append(list(domain_ids))
    if not where:
        raise ValueError("select domains by uid_range, assigned_by, assigned_since or domain_ids")
    return " AND ".join(where), params


def classify(f_group: str, pointer: Optional[int], pointer_f: Optional[str]) -> str:
    """ok / no_pointer / cross_f / cross_h for a domain in a real F-group.

    dot0 for X.H.T.0, not_f_group for a value that is not an F-group id (e.g. an EPP
    accession written by resolve_fgroups); both are reported, not failed.
    """
    if not is_f_group(f_group):
        return "not_f_group"
    if is_topology_only(f_group):
        return "dot0"
    if pointer is None:
        return "no_pointer"
    if pointer_f == f_group:
        return "ok"
    if pointer_f is None or pointer_f.split(".")[:2] != f_group.split(".")[:2]:
        return "cross_h"
    return "cross_f"


def check_rep_pointers(conn, **select) -> Tuple[Dict[str, int], List[tuple]]:
    """QC: counts per class, and the failing rows (domain pk, domain_id, f_group, pointer, class).

    Selection keywords as ``_where``. Read-only.
    """
    where, params = _where(**select)
    cur = conn.cursor()
    try:
        cur.execute(_TARGET_SQL.format(where=where), params)
        rows = cur.fetchall()
    finally:
        cur.close()
    counts = {k: 0 for k in ("ok", "no_pointer", "cross_f", "cross_h", "dot0", "not_f_group")}
    fails = []
    for dom_pk, dom, f, ptr, ptr_f in rows:
        k = classify(f, ptr, ptr_f)
        counts[k] += 1
        if k in ("no_pointer", "cross_f", "cross_h"):
            fails.append((dom_pk, dom, f, ptr, k))
    return counts, fails


def reset_rep_pointers(conn, resolver: FGroupRepResolver, *, dry_run: bool = True,
                       **select) -> Dict[str, int]:
    """Point every selected non-rep domain in a real F-group at its F-group's current rep.

    For any step that changes ``f_group_assignments.f_group_id`` after accession
    (resolve_fgroups, Pfam passes, curation). A pointer already in the domain's own
    F-group is kept (it meets the policy; e.g. a propagated member pointing at its cluster
    rep), so only NULL and out-of-F-group pointers change. Commits unless ``dry_run``.
    """
    where, params = _where(**select)
    cur = conn.cursor()
    counts = {"kept": 0, "set": 0, "no_rep": 0, "dot0": 0, "not_f_group": 0}
    updates = []
    try:
        cur.execute(_TARGET_SQL.format(where=where), params)
        for dom_pk, _dom, f, ptr, ptr_f in cur.fetchall():
            k = classify(f, ptr, ptr_f)
            if k in ("dot0", "not_f_group", "ok"):
                counts["kept" if k == "ok" else k] += 1
                continue
            new = resolver.rep_for(f)
            if new is None:
                counts["no_rep"] += 1
            else:
                updates.append((new, dom_pk))
                counts["set"] += 1
        if updates and not dry_run:
            cur.executemany(
                "UPDATE ecod_commons.domains SET representative_domain_id = %s WHERE id = %s",
                updates)
            conn.commit()
    finally:
        cur.close()
    return counts

