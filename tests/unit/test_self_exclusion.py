#!/usr/bin/env python3
"""
Unit tests for self-exclusion support in pyecod_prod:
  - classification lookup loading (x/h/t/f group)
  - SummaryGenerator emitting classification attributes on <hit>
  - SummaryGenerator optional evidence masking (exclude_self / exclude_domain_ids)
"""

import importlib.util
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pyecod_prod.core.summary_generator import BlastHit, SummaryGenerator
from pyecod_prod.utils.classification_lookup import load_classification_lookup

# Load the standalone builder script as a module
_BUILDER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "build_classification_lookup.py"
_spec = importlib.util.spec_from_file_location("build_classification_lookup", _BUILDER_PATH)
build_classification_lookup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_classification_lookup)


class TestDomainsTxtBuilder:
    def test_split_f_id(self):
        split = build_classification_lookup._split_f_id
        assert split("1.1.1.3") == ("1", "1.1", "1.1.1", "1.1.1.3")
        # 3-level id -> no F-group
        assert split("2.5.7") == ("2", "2.5", "2.5.7", "")
        assert split("") == ("", "", "", "")

    def test_build_from_domains_txt(self):
        # Minimal ECOD domains.txt: comment, header, two data rows
        content = (
            "# ECOD Domain List\n"
            "uid\tecod_domain_id\tmanual_rep\tf_id\tpdb\tchain\n"
            "0\te2nmzA1\tTrue\t1.1.1.3\t2nmz\tA\n"
            "1\te1gcyA2\tFalse\t2002.1.1.301\t1gcy\tA\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".domains.txt", delete=False) as f:
            f.write(content)
            src = f.name
        out = src + ".lookup.tsv"
        try:
            build_classification_lookup.build_from_domains_txt(src, out)
            lk = load_classification_lookup(out)
            assert lk["e2nmzA1"] == {
                "x_group": "1", "h_group": "1.1", "t_group": "1.1.1", "f_group": "1.1.1.3"
            }
            assert lk["e1gcyA2"]["f_group"] == "2002.1.1.301"
        finally:
            Path(src).unlink(missing_ok=True)
            Path(out).unlink(missing_ok=True)


class TestClassificationLookup:
    @pytest.fixture
    def lookup_tsv(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            f.write("# classification lookup\n")
            f.write("ecod_domain_id\tx_group\th_group\tt_group\tf_group\n")
            f.write("e1udzA1\t1\t1.1\t1.1.1\t1.1.1.1\n")
            f.write("e2xyzB1\t2\t2.3\t2.3.4\t\n")  # no f_group
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)

    def test_load(self, lookup_tsv):
        lk = load_classification_lookup(lookup_tsv)
        assert lk["e1udzA1"] == {
            "x_group": "1", "h_group": "1.1", "t_group": "1.1.1", "f_group": "1.1.1.1"
        }
        # blank f_group omitted
        assert lk["e2xyzB1"] == {"x_group": "2", "h_group": "2.3", "t_group": "2.3.4"}


def _blast_hit(domain_id):
    return BlastHit(
        source="domain_blast",
        ecod_domain_id=domain_id,
        family_name="test",
        query_range="1-100",
        target_range="1-100",
        reference_coverage=1.0,
        evalue=0.0,
        bitscore=99.0,
        identity=1.0,
        alignment_length=100,
        reference_length=100,
    )


class TestSummaryClassificationEmission:
    def test_classification_attrs_emitted(self):
        clf = {"e1gcyA2": {"x_group": "2008", "h_group": "2008.1",
                           "t_group": "2008.1.1", "f_group": "2008.1.1.1"}}
        gen = SummaryGenerator(classification_lookup=clf)
        evidence = ET.Element("evidence")
        gen._add_blast_hit(evidence, _blast_hit("e1gcyA2"))
        hit = evidence.find("hit")
        assert hit.get("t_group") == "2008.1.1"
        assert hit.get("f_group") == "2008.1.1.1"

    def test_no_classification_when_absent(self):
        gen = SummaryGenerator()  # no lookup
        evidence = ET.Element("evidence")
        gen._add_blast_hit(evidence, _blast_hit("e1gcyA2"))
        hit = evidence.find("hit")
        assert hit.get("t_group") is None
        assert hit.get("f_group") is None


class TestSummaryMasking:
    def test_hit_excluded_self(self):
        gen = SummaryGenerator()
        gen._masked_hit_count = 0
        assert gen._hit_excluded("e1gcyA2", "1gcy", True, set()) is True
        assert gen._hit_excluded("e9xyzB1", "1gcy", True, set()) is False
        assert gen._masked_hit_count == 1

    def test_hit_excluded_by_id(self):
        gen = SummaryGenerator()
        gen._masked_hit_count = 0
        # provided without leading 'e' should still match
        assert gen._hit_excluded("e1gcyA2", "9zzz", False, {"e1gcyA2", "1gcyA2"}) is True

    def test_extract_hit_pdb(self):
        assert SummaryGenerator._extract_hit_pdb("e1gcyA2") == "1gcy"
        assert SummaryGenerator._extract_hit_pdb("1gcy_A") == "1gcy"
        assert SummaryGenerator._extract_hit_pdb("") is None
