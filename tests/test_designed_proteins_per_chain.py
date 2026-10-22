#!/usr/bin/env python3
"""
Tests for per-chain designed protein detection.

Entry-wide attribution excluded every chain of an entry when any line of its
mmCIF mentioned "synthetic construct" -- a DNA strand, peptide ligand or fusion
tag on one entity was enough. These tests pin the per-entity attribution.
"""

from pathlib import Path

import pytest

from pyecod_prod.utils.designed_proteins import (
    DesignedProteinConfidence,
    DesignedProteinDetector,
)

PDB_MIRROR = Path('/usr2/pdb/data/structures/divided/mmCIF')


def make_cif(entities, title="Cryo-EM structure of a complex", keywords="MEMBRANE PROTEIN"):
    """
    Build a minimal mmCIF.

    entities: list of (entity_id, poly_type, strands, description, src_category, organism)
    """
    lines = [
        "data_TEST",
        "#",
        "_struct.entry_id TEST",
        "_struct.title",
        ";" + title,
        ";",
        "#",
        f"_struct_keywords.pdbx_keywords '{keywords}'",
        "#",
        "loop_",
        "_entity.id",
        "_entity.type",
        "_entity.src_method",
        "_entity.pdbx_description",
    ]
    for eid, _, _, desc, cat, _ in entities:
        method = 'syn' if cat == '_pdbx_entity_src_syn' else 'man'
        lines.append(f"{eid} polymer {method} '{desc}'")
    lines += ["#", "loop_", "_entity_poly.entity_id", "_entity_poly.type",
              "_entity_poly.pdbx_strand_id"]
    for eid, ptype, strands, *_ in entities:
        lines.append(f"{eid} '{ptype}' {strands}")
    field_names = {
        '_entity_src_gen': 'pdbx_gene_src_scientific_name',
        '_entity_src_nat': 'pdbx_organism_scientific',
        '_pdbx_entity_src_syn': 'organism_scientific',
    }
    for cat, field_name in field_names.items():
        rows = [(eid, org) for eid, _, _, _, c, org in entities if c == cat]
        if not rows:
            continue
        lines += ["#", "loop_", f"{cat}.entity_id", f"{cat}.{field_name}"]
        lines += [f"{eid} '{org}'" for eid, org in rows]
    lines.append("#")
    return "\n".join(lines) + "\n"


@pytest.fixture
def mirror(tmp_path):
    """Write an mmCIF into a fake mirror and return a detector reading it."""
    def _write(pdb_id, cif_text):
        directory = tmp_path / pdb_id[1:3]
        directory.mkdir(exist_ok=True)
        (directory / f"{pdb_id}.cif").write_text(cif_text)
        return DesignedProteinDetector(pdb_mirror_path=str(tmp_path))
    return _write


PROTEIN = 'polypeptide(L)'
DNA = 'polydeoxyribonucleotide'


class TestEntryInfo:
    """mmCIF parsing."""

    def test_multiline_title_and_chain_mapping(self, mirror):
        detector = mirror('1abc', make_cif(
            [('1', PROTEIN, 'A,B', 'Histone H3', '_entity_src_gen', 'Xenopus laevis'),
             ('2', DNA, 'X', 'DNA (147-MER)', '_entity_src_gen', 'synthetic construct')],
            title="Structure of a nucleosome",
        ))
        info = detector.get_entry_info('1abc')

        assert info['title'] == 'Structure of a nucleosome'
        assert info['keywords'] == 'MEMBRANE PROTEIN'
        # Nucleic-acid entities are not returned
        assert list(info['entities']) == ['1']
        assert info['entities']['1']['chains'] == ['A', 'B']
        assert info['entities']['1']['organisms'] == ['Xenopus laevis']

    def test_missing_file_returns_empty(self, tmp_path):
        detector = DesignedProteinDetector(pdb_mirror_path=str(tmp_path))
        assert detector.get_entry_info('9zzz')['entities'] == {}
        assert detector.detect_chains('9zzz') == {}


class TestPerChainAttribution:
    """Each chain is judged on its own entity."""

    def test_synthetic_dna_does_not_mark_protein_chains(self, mirror):
        """9v2w shape: natural complex on synthetic DNA."""
        detector = mirror('1abc', make_cif([
            ('1', PROTEIN, 'A', 'Histone deacetylase RPD3', '_entity_src_gen',
             'Saccharomyces cerevisiae'),
            ('2', DNA, 'X', 'DNA (329-MER)', '_entity_src_gen', 'synthetic construct'),
        ]))

        chains = detector.detect_chains('1abc')
        assert chains['A'].confidence == DesignedProteinConfidence.NONE
        # Entry level agrees: the DNA no longer marks the entry
        assert detector.get_pdb_metadata('1abc')['source_organism'] == 'Saccharomyces cerevisiae'
        assert detector.detect('1abc').confidence == DesignedProteinConfidence.NONE

    def test_synthetic_peptide_marks_only_its_own_chain(self, mirror):
        """20zc shape: natural receptor with a synthetic peptide ligand."""
        detector = mirror('1abc', make_cif([
            ('1', PROTEIN, 'R', 'Neurotensin receptor type 1', '_entity_src_gen', 'Homo sapiens'),
            ('2', PROTEIN, 'L', 'LYS-LYS-PRO-TYR-ILE-LEU', '_pdbx_entity_src_syn',
             'synthetic construct'),
        ]))

        chains = detector.detect_chains('1abc')
        assert chains['R'].confidence == DesignedProteinConfidence.NONE
        assert 'synthetic_construct_organism' in chains['L'].reasons
        assert chains['L'].confidence == DesignedProteinConfidence.MEDIUM

    def test_design_title_not_attributed_to_natural_partner(self, mirror):
        """A de novo binder bound to a natural target: only the binder is designed."""
        detector = mirror('1abc', make_cif(
            [('1', PROTEIN, 'A', 'Spike glycoprotein', '_entity_src_gen',
              'Severe acute respiratory syndrome coronavirus 2'),
             ('2', PROTEIN, 'B', 'Binder LCB1', '_entity_src_gen', 'synthetic construct')],
            title="De novo designed miniprotein binder in complex with spike",
            keywords="DE NOVO PROTEIN",
        ))

        chains = detector.detect_chains('1abc')
        assert chains['A'].confidence == DesignedProteinConfidence.NONE
        assert chains['B'].confidence == DesignedProteinConfidence.HIGH
        assert 'de_novo_keyword' in chains['B'].reasons
        assert 'de_novo_title' in chains['B'].reasons

    def test_entity_description_counts_for_anchored_entity(self, mirror):
        """Design language in a chain's own description applies regardless of organism."""
        detector = mirror('1abc', make_cif([
            ('1', PROTEIN, 'A', 'de novo designed TIM barrel', '_entity_src_gen',
             'Escherichia coli'),
        ]))
        assert 'de_novo_title' in detector.detect_chains('1abc')['A'].reasons

    def test_unidentified_organism_receives_entry_signals(self, mirror):
        detector = mirror('1abc', make_cif(
            [('1', PROTEIN, 'A', 'Protein', '_entity_src_gen', 'unidentified')],
            keywords="DE NOVO PROTEIN",
        ))
        assert detector.detect_chains('1abc')['A'].confidence == DesignedProteinConfidence.HIGH

    def test_chimera_with_natural_source_is_anchored(self, mirror):
        """A fusion with any natural source row does not receive entry-level signals."""
        cif = make_cif(
            [('1', PROTEIN, 'A', 'Porin fusion', '_entity_src_gen', 'Mycolicibacterium smegmatis')],
            keywords="DE NOVO PROTEIN",
        ).replace(
            "1 'Mycolicibacterium smegmatis'",
            "1 'Mycolicibacterium smegmatis'\n1 'synthetic construct'",
        )
        detector = mirror('1abc', cif)
        assert detector.detect_chains('1abc')['A'].confidence == DesignedProteinConfidence.NONE


class TestFalsePositivePatterns:
    """FALSE_POSITIVE_PATTERNS were compiled but never applied."""

    def test_designed_for_is_not_a_design_signal(self):
        detector = DesignedProteinDetector()
        result = detector.detect('test', metadata={
            'title': 'Mutated albumin designed for bacterial expression',
            'keywords': 'TRANSPORT PROTEIN',
            'source_organism': 'Homo sapiens',
        })
        assert result.confidence == DesignedProteinConfidence.NONE
        # The reported title is unchanged
        assert result.title == 'Mutated albumin designed for bacterial expression'

    def test_genuine_designed_still_matches(self):
        detector = DesignedProteinDetector()
        result = detector.detect('test', metadata={
            'title': 'Structure of a designed zinc finger',
            'keywords': 'METAL BINDING PROTEIN',
            'source_organism': 'Escherichia coli',
        })
        assert 'designed_title' in result.reasons


class TestParserUsesChains:
    """PDBStatusParser excludes chains, not entries."""

    def test_is_classifiable_per_chain(self, mirror):
        from pyecod_prod.parsers.pdb_status import PDBStatusParser

        detector = mirror('1abc', make_cif(
            [('1', PROTEIN, 'A', 'Spike glycoprotein', '_entity_src_gen', 'Homo sapiens'),
             ('2', PROTEIN, 'B', 'Binder', '_entity_src_gen', 'synthetic construct')],
            keywords="DE NOVO PROTEIN",
        ))
        parser = PDBStatusParser(pdb_mirror_path=str(detector.pdb_mirror_path))
        seq = 'M' * 80

        assert parser._is_classifiable(seq, 80, '1abc', 'A') == (True, None)
        assert parser._is_classifiable(seq, 80, '1abc', 'B') == (False, 'designed_protein')


@pytest.mark.skipif(not PDB_MIRROR.exists(), reason="PDB mirror not available")
class TestRealEntries:
    """Entries the entry-wide filter excluded in the 2026-05-22 weekly release."""

    def test_9v2w_protein_chains_kept(self):
        """Rpd3L on a di-nucleosome; only the DNA is a synthetic construct."""
        chains = DesignedProteinDetector().detect_chains('9v2w')
        assert chains
        assert all(not r.should_exclude for r in chains.values())

    def test_20zc_receptor_kept(self):
        """NTSR1-Gi1 complex; only the neurotensin peptide is synthetic."""
        chains = DesignedProteinDetector().detect_chains('20zc')
        assert not chains['R'].should_exclude
        assert not chains['A'].should_exclude

    def test_engineered_natural_variants_kept(self):
        """Labelled "synthetic construct" but natural families ECOD can classify."""
        detector = DesignedProteinDetector()
        # hSA3 albumin variant; ancestral dehalogenase-luciferase
        assert not detector.detect_chains('9r8p')['A'].should_exclude
        assert not detector.detect_chains('9rbn')['A'].should_exclude

    def test_9hnh_still_designed(self):
        """Synthetic alpha solenoid: a genuine design stays excluded."""
        chains = DesignedProteinDetector().detect_chains('9hnh')
        assert chains and all(r.should_exclude for r in chains.values())
