"""Seqid range check: PDB domain ranges must be positions in the chain's construct sequence.

``ecod_commons.domains.range_definition`` holds seqid ranges: position i of a chain is
``_pdbx_poly_seq_scheme.seq_id`` i, modeled or not (parsers/pdb_status.chain_schemes).
Twice (June 2026, ~33k domains; Q4 2026) a batch was searched and partitioned against
the chain's MODELED residues instead, so ranges on chains with an unmodeled N-terminus
were modeled ordinals shifted by the offset. Shifted ranges still parse and usually
still land on modeled residues, so nothing downstream failed until a structure cut came
back empty. This check catches it at accession.

Per non-obsolete PDB domain, against the parent mmCIF (first failing class wins):

  bad_range           range does not parse as CHAIN:lo-hi segments with lo >= 1
  chain_missing       a segment names a chain with no observed protein residue
  beyond_construct    a position past the end of the chain's construct sequence
  query_not_construct the chain's search sequence (pdb_update.sequence) is not its
                      construct sequence -- the root cause; the batch's ranges for that
                      chain are in some other numbering
  unobserved          not one residue of the range has coordinates
  ok

Reported, not failed: cif_missing (entry not on the mirror), no_query (no
pdb_update.sequence row for the chain; older domains), multichain (protein chain_id
'A-B', so no single search sequence to compare).
"""

import gzip
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from Bio.PDB.MMCIF2Dict import MMCIF2Dict

from pyecod_prod.parsers.pdb_status import PDBStatusParser, chain_schemes

FAIL_CLASSES = ("bad_range", "chain_missing", "beyond_construct", "query_not_construct", "unobserved")

_SEG = re.compile(r"^([^:]+):(\d+)-(\d+)$")

_DOMAINS_SQL = """
    SELECT d.id, d.domain_id, d.ecod_uid, p.pdb_id, p.chain_id, d.range_definition, q.sequence
      FROM ecod_commons.domains d
      JOIN ecod_commons.proteins p ON p.id = d.protein_id AND p.source_type = 'pdb'
      LEFT JOIN pdb_update.sequence q ON q.pdb_id = p.pdb_id AND q.chain_id = p.chain_id
     WHERE NOT d.is_obsolete AND {where}
     ORDER BY p.pdb_id, d.ecod_uid
"""


def parse_segments(range_def: str) -> Optional[List[Tuple[str, int, int]]]:
    """'A:1-50,B:3-9' -> [('A', 1, 50), ('B', 3, 9)]; None if any segment is not seqid-shaped."""
    segs = []
    for part in (range_def or "").split(","):
        m = _SEG.match(part.strip())
        if not m:
            return None
        lo, hi = int(m.group(2)), int(m.group(3))
        if lo < 1 or hi < lo:
            return None
        segs.append((m.group(1), lo, hi))
    return segs or None


def classify(range_def: str, chain_id: str, query: Optional[str],
             schemes: Dict[str, Tuple[str, set]]) -> str:
    """One domain's class (see module docstring). ``schemes`` is chain_schemes() of its entry."""
    segs = parse_segments(range_def)
    if segs is None:
        return "bad_range"
    n_obs = 0
    for chain, lo, hi in segs:
        if chain not in schemes:
            return "chain_missing"
        seq, obs = schemes[chain]
        if hi > len(seq):
            return "beyond_construct"
        n_obs += sum(1 for i in range(lo, hi + 1) if i in obs)
    if "-" in chain_id:
        return "multichain" if n_obs else "unobserved"
    if query is not None and chain_id in schemes and query != schemes[chain_id][0]:
        return "query_not_construct"
    if not n_obs:
        return "unobserved"
    return "ok" if query is not None else "no_query"


def _where(uid_range=None, domain_version=None):
    where, params = [], []
    if uid_range:
        where.append("d.ecod_uid BETWEEN %s AND %s")
        params += list(uid_range)
    if domain_version:
        where.append("d.domain_version LIKE %s")
        params.append(domain_version)
    if not where:
        raise ValueError("select domains by uid_range or domain_version")
    return " AND ".join(where), params


def _read_cif(path) -> Dict[str, list]:
    if str(path).endswith(".gz"):
        with gzip.open(path, "rt") as fh:
            return MMCIF2Dict(fh)
    return MMCIF2Dict(str(path))


def check_seqid_ranges(conn, pdb_mirror_path: str = "/usr2/pdb/data/structures/divided/mmCIF",
                       shard: int = 0, nshards: int = 1, **select):
    """QC: counts per class, and the failing rows (domain pk, domain_id, ecod_uid, pdb_id,
    chain_id, range, class). Read-only. Each entry's mmCIF is parsed once; ``shard`` /
    ``nshards`` split the work by entry for SLURM arrays."""
    where, params = _where(**select)
    cur = conn.cursor()
    try:
        cur.execute(_DOMAINS_SQL.format(where=where), params)
        rows = cur.fetchall()
    finally:
        cur.close()
    by_entry = defaultdict(list)
    for r in rows:
        by_entry[r[3]].append(r)

    locator = PDBStatusParser(pdb_mirror_path=pdb_mirror_path, filter_designed_proteins=False)
    counts = {k: 0 for k in ("ok",) + FAIL_CLASSES + ("no_query", "multichain", "cif_missing")}
    fails = []
    for i, pdb_id in enumerate(sorted(by_entry)):
        if i % nshards != shard:
            continue
        try:
            schemes = chain_schemes(_read_cif(locator.get_mmcif_path(pdb_id)))
        except FileNotFoundError:
            counts["cif_missing"] += len(by_entry[pdb_id])
            continue
        for pk, dom, uid, _pdb, chain_id, rng, query in by_entry[pdb_id]:
            k = classify(rng, chain_id, query, schemes)
            counts[k] += 1
            if k in FAIL_CLASSES:
                fails.append((pk, dom, uid, pdb_id, chain_id, rng, k))
    return counts, fails
