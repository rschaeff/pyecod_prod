#!/usr/bin/env python3
"""Unit tests for the reference-version registry (ReferenceConfig)."""

import tempfile
from pathlib import Path

import pytest

from pyecod_prod.utils.reference_config import ReferenceConfig, available_versions

# A self-contained registry for deterministic tests.
_REGISTRY = """
default: v291
aliases:
  develop291: v291
versions:
  v291:
    summary_suffix: develop291
    blast_chain_db: {chain}
    blast_domain_db: {domain}
    hhsearch_db: {hh}
    family_lookup: {fam}
    classification_lookup: {clf}
    domain_definitions_csv: null
    domain_lengths_csv: null
    protein_lengths_csv: null
  v294.2:
    summary_suffix: develop291
    blast_chain_db: /nonexistent/chainwise
    blast_domain_db: /nonexistent/ecod100
    hhsearch_db: /nonexistent/hh
    family_lookup: /nonexistent/fam.tsv
    classification_lookup: /nonexistent/clf.tsv
    domain_definitions_csv: /nonexistent/dd.csv
    domain_lengths_csv: /nonexistent/dl.csv
    protein_lengths_csv: /nonexistent/pl.csv
"""


@pytest.fixture
def registry(tmp_path):
    # Create existing artifacts for v291 so verify() passes.
    chain = tmp_path / "chainwise.psq"
    chain.write_text("x")
    domain = tmp_path / "ecod100.psq"
    domain.write_text("x")
    hh_data = tmp_path / "hh_hhm.ffdata"
    hh_data.write_text("x")
    hh_index = tmp_path / "hh_hhm.ffindex"
    hh_index.write_text("x")
    fam = tmp_path / "fam.tsv"
    fam.write_text("x")
    clf = tmp_path / "clf.tsv"
    clf.write_text("x")

    reg = tmp_path / "references.yaml"
    reg.write_text(
        _REGISTRY.format(
            chain=str(tmp_path / "chainwise"),  # prefix; .psq exists
            domain=str(tmp_path / "ecod100"),
            hh=str(tmp_path / "hh"),
            fam=str(fam),
            clf=str(clf),
        )
    )
    return str(reg)


class TestReferenceConfig:
    def test_alias_resolves_to_canonical(self, registry):
        c = ReferenceConfig.load("develop291", registry_path=registry)
        assert c.version == "v291"

    def test_default_version(self, registry):
        c = ReferenceConfig.load(registry_path=registry)
        assert c.version == "v291"

    def test_unknown_version_raises(self, registry):
        with pytest.raises(KeyError):
            ReferenceConfig.load("v999", registry_path=registry)

    def test_blast_prefix_existence(self, registry):
        c = ReferenceConfig.load("v291", registry_path=registry)
        # .psq sidecar present -> not missing
        assert c.missing(["blast_chain_db", "blast_domain_db"]) == []

    def test_hhsearch_pair_existence(self, registry):
        c = ReferenceConfig.load("v291", registry_path=registry)
        assert c.missing(["hhsearch_db"]) == []

    def test_verify_passes_for_present_version(self, registry):
        c = ReferenceConfig.load("v291", registry_path=registry)
        c.verify(["blast_chain_db", "blast_domain_db", "hhsearch_db",
                  "family_lookup", "classification_lookup"])

    def test_null_csv_counts_as_missing(self, registry):
        c = ReferenceConfig.load("v291", registry_path=registry)
        # v291 mini CSVs are null -> reported missing when required
        assert "domain_definitions_csv" in c.missing(["domain_definitions_csv"])

    def test_verify_raises_when_absent(self, registry):
        c = ReferenceConfig.load("v294.2", registry_path=registry)
        with pytest.raises(FileNotFoundError):
            c.verify()


class TestRealRegistry:
    """Sanity checks against the shipped references.yaml."""

    def test_versions_present(self):
        vs = available_versions()
        assert "v291" in vs and "v294.2" in vs

    def test_v291_loads(self):
        c = ReferenceConfig.load("develop291")
        assert c.version == "v291"
        assert c.hhsearch_db.endswith("ecod_v291")
