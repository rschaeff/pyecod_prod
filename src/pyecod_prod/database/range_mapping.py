"""Map a representative's domain ranges onto a cluster member's chain.

Coordinate systems (see pyecod_mini core/writer.py and validation/seqid_ranges.py):

  ecod_commons.domains.range_definition        SEQID: 1-based position in the chain's
                                               construct sequence (_pdbx_poly_seq_scheme
                                               seq_id), modeled or not
  ecod_commons.domain_ranges (range_type pdb)  AUTHOR: _pdbx_poly_seq_scheme.pdb_seq_num
                                               plus pdb_ins_code (NOT auth_seq_num)

A member of a 70%-identity cluster can differ from its representative by tags,
truncations, insertions and point mutations. So a rep's seqid range cannot simply be
relabelled with the member's chain letter (the pre-2026-11 behaviour), and a seqid
range must never be written as an author range. Instead:

  1. read both chains' construct sequences and author numbering from their mmCIFs
  2. align member to rep (identity fast path when the sequences are equal)
  3. carry each seqid segment across the alignment
  4. translate the member's seqid segments to author numbering

Any member whose ranges cannot be mapped cleanly gets an error, never a guessed range.
"""

import gzip
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from Bio.Align import PairwiseAligner, substitution_matrices
from Bio.Data.PDBData import protein_letters_3to1_extended

# A domain is propagated only if at least this fraction of the rep domain's residues
# align to member residues.
MIN_DOMAIN_COVERAGE = 0.90


class RangeMappingError(Exception):
    """A member's ranges cannot be derived from its representative's."""


@dataclass
class ChainScheme:
    """One chain's construct sequence and per-position annotations (1-based seq_id)."""
    sequence: str
    author: Dict[int, str]   # seq_id -> pdb_seq_num[+ins_code]
    observed: set            # seq_ids with coordinates (auth_seq_num not '?')


def read_poly_seq_scheme(path: str) -> Dict[str, ChainScheme]:
    """Per author chain (pdb_strand_id): ChainScheme, from an mmCIF's _pdbx_poly_seq_scheme.

    A line parser rather than MMCIF2Dict, because propagation reads thousands of entries
    and only needs this one loop. Columns are resolved by name from the loop header.
    Non-standard residues map to their parent (MSE -> M), unknown ones to X;
    microheterogeneity keeps the first monomer at a seq_id. Polymer type is not
    filtered here; callers only ask for chains already known to be protein.
    """
    opener = gzip.open if str(path).endswith(".gz") else open
    cols: List[str] = []
    rows: Dict[str, Dict[int, Tuple[str, str, bool]]] = {}
    state = "seek"  # seek -> header -> data
    with opener(path, "rt") as fh:
        for raw in fh:
            line = raw.strip()
            if line.startswith("_pdbx_poly_seq_scheme."):
                cols.append(line.split()[0].split(".", 1)[1])
                state = "header"
                continue
            if state == "seek":
                continue
            if not line or line.startswith(("#", "loop_", "_", "data_")):
                break  # end of the loop
            state = "data"
            parts = line.split()
            if len(parts) < len(cols):
                continue
            r = dict(zip(cols, parts))
            try:
                sid = int(r["seq_id"])
            except (KeyError, ValueError):
                continue
            chain = rows.setdefault(r.get("pdb_strand_id", "?"), {})
            if sid in chain:
                continue
            num = r.get("pdb_seq_num", "?")
            ins = r.get("pdb_ins_code", ".")
            author = "" if num in ("?", ".") else (num + ins if ins not in (".", "?") else num)
            observed = r.get("auth_seq_num", "?") not in ("?", ".")
            aa = protein_letters_3to1_extended.get(r.get("mon_id", "").upper(), "X")
            chain[sid] = (aa, author, observed)

    out = {}
    for strand, pos in rows.items():
        n = max(pos)
        out[strand] = ChainScheme(
            sequence="".join(pos[i][0] if i in pos else "X" for i in range(1, n + 1)),
            author={i: a for i, (_, a, _) in pos.items() if a},
            observed={i for i, (_, _, o) in pos.items() if o},
        )
    return out


_ALIGNER: Optional[PairwiseAligner] = None


def _aligner() -> PairwiseAligner:
    """Global alignment with free end gaps (tags and truncations cost nothing)."""
    global _ALIGNER
    if _ALIGNER is None:
        a = PairwiseAligner()
        a.mode = "global"
        a.substitution_matrix = substitution_matrices.load("BLOSUM62")
        a.open_gap_score = -10
        a.extend_gap_score = -0.5
        a.end_gap_score = 0
        _ALIGNER = a
    return _ALIGNER


def align_positions(rep_seq: str, member_seq: str) -> Dict[int, int]:
    """{rep seq_id: member seq_id} for aligned (non-gap) columns, both 1-based."""
    if rep_seq == member_seq:
        return {i: i for i in range(1, len(rep_seq) + 1)}
    aligner = _aligner()
    alphabet = set(aligner.substitution_matrix.alphabet)
    # U (Sec), O (Pyl) etc. are not in BLOSUM62; score them as X. Lengths are unchanged.
    clean = lambda s: "".join(c if c in alphabet else "X" for c in s.upper())  # noqa: E731
    aln = aligner.align(clean(rep_seq), clean(member_seq))[0]
    out = {}
    for (r0, r1), (m0, m1) in zip(*aln.aligned):
        for k in range(r1 - r0):
            out[r0 + k + 1] = m0 + k + 1
    return out


def _segments(range_def: str) -> List[Tuple[int, int]]:
    """'A:10-50,A:60-90' -> [(10, 50), (60, 90)]; chain prefixes are dropped."""
    segs = []
    for part in range_def.split(","):
        body = part.strip().rsplit(":", 1)[-1]
        lo, sep, hi = body.partition("-")
        try:
            lo_i, hi_i = int(lo), int(hi)
        except ValueError:
            raise RangeMappingError(f"not a seqid range: {range_def!r}")
        if not sep or lo_i < 1 or hi_i < lo_i:
            raise RangeMappingError(f"not a seqid range: {range_def!r}")
        segs.append((lo_i, hi_i))
    if not segs:
        raise RangeMappingError(f"empty range: {range_def!r}")
    return segs


def map_domain_range(
    rep_range: str,
    pos_map: Dict[int, int],
    member_chain: str,
    member: ChainScheme,
    min_coverage: float = MIN_DOMAIN_COVERAGE,
) -> Tuple[str, str]:
    """Rep seqid range -> (member seqid range, member author range), chain-prefixed.

    Each rep segment becomes the span of its aligned member positions. Raises
    RangeMappingError when the domain is under-covered, a segment vanishes, segments
    collide after mapping, or an endpoint has no author number.
    """
    segs = _segments(rep_range)
    total = sum(hi - lo + 1 for lo, hi in segs)
    mapped_total = 0
    out: List[Tuple[int, int]] = []
    for lo, hi in segs:
        mapped = [pos_map[i] for i in range(lo, hi + 1) if i in pos_map]
        if not mapped:
            raise RangeMappingError(f"segment {lo}-{hi} has no aligned member residues")
        mapped_total += len(mapped)
        out.append((min(mapped), max(mapped)))

    coverage = mapped_total / total
    if coverage < min_coverage:
        raise RangeMappingError(f"only {coverage:.0%} of {rep_range} aligns to the member")
    for (_, prev_hi), (lo, _) in zip(out, out[1:]):
        if lo <= prev_hi:
            raise RangeMappingError(f"segments overlap after mapping: {out}")
    if not any(i in member.observed for lo, hi in out for i in range(lo, hi + 1)):
        raise RangeMappingError("mapped range has no modeled residues")

    seqid_parts, author_parts = [], []
    for lo, hi in out:
        a_lo, a_hi = member.author.get(lo), member.author.get(hi)
        if not a_lo or not a_hi:
            raise RangeMappingError(f"no author number for seq_id {lo} or {hi}")
        seqid_parts.append(f"{member_chain}:{lo}-{hi}")
        author_parts.append(f"{member_chain}:{a_lo}-{a_hi}")
    return ",".join(seqid_parts), ",".join(author_parts)


class RangeMapper:
    """Maps rep domains onto members, caching parsed mmCIFs by entry."""

    def __init__(self, locate_mmcif, max_cached_entries: int = 64):
        """``locate_mmcif(pdb_id) -> path``; raises FileNotFoundError if absent."""
        self._locate = locate_mmcif
        self._cache: Dict[str, Dict[str, ChainScheme]] = {}
        self._max = max_cached_entries

    def chain(self, pdb_id: str, chain_id: str) -> ChainScheme:
        key = pdb_id.lower()
        if key not in self._cache:
            try:
                path = self._locate(key)
            except FileNotFoundError:
                raise RangeMappingError(f"no mmCIF for {key}")
            if len(self._cache) >= self._max:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = read_poly_seq_scheme(path)
        try:
            return self._cache[key][chain_id]
        except KeyError:
            raise RangeMappingError(f"chain {chain_id} not in {key} _pdbx_poly_seq_scheme")

    def map_member(
        self,
        rep_pdb_id: str,
        rep_chain_id: str,
        member_pdb_id: str,
        member_chain_id: str,
        rep_ranges: List[str],
    ) -> List[Tuple[str, str]]:
        """[(member seqid range, member author range)] per rep range, in order.

        All-or-nothing: if any domain fails to map, RangeMappingError is raised and the
        member gets no domains.
        """
        rep = self.chain(rep_pdb_id, rep_chain_id)
        member = self.chain(member_pdb_id, member_chain_id)
        pos_map = align_positions(rep.sequence, member.sequence)
        return [map_domain_range(r, pos_map, member_chain_id, member) for r in rep_ranges]
