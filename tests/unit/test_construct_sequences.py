"""Chain sequences are construct (seqid) sequences, not modeled residues.

Regression for the seqid bug (June 2026, again in the Q4 2026 batch): the sequence
searched and partitioned for a chain was its modeled standard residues, so every
domain range on a chain with an unmodeled N-terminus was shifted by the offset.
"""

import gzip

import pytest

from pyecod_prod.parsers.pdb_status import PDBStatusParser, construct_sequences

# Entity 1: protein, chain A, 30 residues, 1-10 unmodeled, TYR at 11 (first modeled),
#   MSE at 12, microheterogeneity at 15.
# Entity 2: protein, chain B, 25 residues, nothing modeled (no structure).
# Entity 3: DNA, chain C.
# Entity 4: protein, chain D, 40-residue construct with only 8 modeled residues.
_AA = ["ALA", "GLY", "SER", "LYS", "LEU"]


def _scheme_rows():
    rows = []
    for i in range(1, 31):
        mon = {11: "TYR", 12: "MSE"}.get(i, _AA[i % 5])
        auth = "?" if i <= 10 else str(i + 100)
        rows.append(("1", i, mon, auth, "A"))
        if i == 15:
            rows.append(("1", i, "TRP", auth, "A"))       # second monomer at seq_id 15
    rows += [("2", i, "ALA", "?", "B") for i in range(1, 26)]
    rows += [("3", i, "DA", str(i), "C") for i in range(1, 11)]
    rows += [("4", i, "GLY", str(i) if 20 <= i < 28 else "?", "D") for i in range(1, 41)]
    return rows


def _write_cif(path):
    lines = [
        "data_TEST",
        "loop_",
        "_entity_poly.entity_id",
        "_entity_poly.type",
        "1 'polypeptide(L)'",
        "2 'polypeptide(L)'",
        "3 polydeoxyribonucleotide",
        "4 'polypeptide(L)'",
        "loop_",
        "_pdbx_poly_seq_scheme.entity_id",
        "_pdbx_poly_seq_scheme.seq_id",
        "_pdbx_poly_seq_scheme.mon_id",
        "_pdbx_poly_seq_scheme.auth_seq_num",
        "_pdbx_poly_seq_scheme.pdb_strand_id",
    ]
    lines += [f"{e} {s} {m} {a} {c}" for e, s, m, a, c in _scheme_rows()]
    with gzip.open(path, "wt") as fh:
        fh.write("\n".join(lines) + "\n")


@pytest.fixture
def parser(tmp_path):
    (tmp_path / "es").mkdir()
    _write_cif(tmp_path / "es" / "1est.cif.gz")
    return PDBStatusParser(pdb_mirror_path=str(tmp_path), filter_designed_proteins=False)


def test_sequence_is_construct_including_unmodeled_terminus(parser):
    chains = {c.chain_id: c for c in parser.get_chains_for_pdb("1est")}
    a = chains["A"]
    assert a.sequence_length == 30                  # not 20 modeled residues
    assert a.sequence[:10] == "GSKLAGSKLA"          # unmodeled seq_ids 1-10 included
    assert a.sequence[10] == "Y"                    # seq_id 11, the first modeled residue


def test_nonstandard_maps_to_parent_and_microheterogeneity_keeps_first(parser):
    a = {c.chain_id: c for c in parser.get_chains_for_pdb("1est")}["A"]
    assert a.sequence[11] == "M"                    # MSE at seq_id 12
    assert a.sequence[14] == "A"                    # seq_id 15: ALA kept, TRP dropped
    assert len(a.sequence) == 30


def test_unmodeled_and_nucleic_acid_chains_omitted(parser):
    ids = {c.chain_id for c in parser.get_chains_for_pdb("1est")}
    assert ids == {"A", "D"}


def test_peptide_threshold_counts_modeled_residues(parser):
    d = {c.chain_id: c for c in parser.get_chains_for_pdb("1est")}["D"]
    assert d.sequence_length == 40
    assert not d.can_classify and d.cannot_classify_reason == "peptide"


def test_construct_sequences_scalar_columns():
    # MMCIF2Dict returns scalars, not lists, for a single-row category
    cif = {
        "_entity_poly.entity_id": "1",
        "_entity_poly.type": "polypeptide(L)",
        "_pdbx_poly_seq_scheme.entity_id": "1",
        "_pdbx_poly_seq_scheme.seq_id": "1",
        "_pdbx_poly_seq_scheme.mon_id": "GLY",
        "_pdbx_poly_seq_scheme.auth_seq_num": "1",
        "_pdbx_poly_seq_scheme.pdb_strand_id": "A",
    }
    assert construct_sequences(cif) == {"A": ("G", 1)}
