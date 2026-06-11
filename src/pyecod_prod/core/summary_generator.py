#!/usr/bin/env python3
"""
Generate domain summary XML files from BLAST and HHsearch results.

The domain summary combines evidence from multiple sources into a unified
XML format that pyecod-mini uses for domain partitioning.

Output format complies with PYECOD_MINI_API_SPEC.md.
"""

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class BlastHit:
    """Represent a BLAST hit"""

    source: str  # 'chain_blast' or 'domain_blast'
    ecod_domain_id: str  # Domain ID from hit (may be comma-separated for chain hits)
    family_name: str  # ECOD family name (e.g., "GFP-like")
    query_range: str  # e.g., "10-110" or "10-110,150-200"
    target_range: str  # Alignment range in reference
    reference_coverage: float  # Coverage of reference domain
    evalue: float
    bitscore: float
    identity: float  # Sequence identity (0.0-1.0)
    alignment_length: int
    ecod_uid: Optional[int] = None  # ECOD unique ID (for uid-based reference lookup)
    reference_length: Optional[int] = None  # Full length of reference domain


@dataclass
class HHsearchHit:
    """Represent an HHsearch hit"""

    source: str  # 'hhsearch'
    ecod_domain_id: str  # Domain ID from hit
    family_name: str  # ECOD family name
    query_range: str  # e.g., "10-110"
    target_range: str  # Alignment range in reference
    reference_coverage: float  # Coverage of reference domain
    evalue: float
    probability: float  # HHsearch probability (0-100)
    score: float
    ecod_uid: Optional[int] = None  # ECOD unique ID (for uid-based reference lookup)
    reference_length: Optional[int] = None  # Full length of reference domain


class SummaryGenerator:
    """
    Generate domain_summary.xml from BLAST and HHsearch results.

    Output format per PYECOD_MINI_API_SPEC.md.

    Phase 2: BLAST-only mode
    Phase 3: Added HHsearch support for low-coverage chains
    """

    def __init__(
        self,
        reference_version: str = "v294.2",
        family_lookup: Optional[Dict[str, str]] = None,
        classification_lookup: Optional[Dict[str, Dict[str, str]]] = None,
    ):
        """
        Initialize summary generator.

        Args:
            reference_version: ECOD reference version
            family_lookup: Optional dict mapping domain IDs to family names
            classification_lookup: Optional dict mapping domain IDs to their
                ECOD classification {x_group, h_group, t_group, f_group}. When
                provided, these are emitted on each <hit>, enabling F-group /
                T-group exclusion in pyecod_mini (non-circular rep validation).
        """
        self.reference_version = reference_version
        self.family_lookup = family_lookup or {}
        self.classification_lookup = classification_lookup or {}

    def parse_blast_xml(self, blast_xml: str, source: str) -> List[BlastHit]:
        """
        Parse BLAST XML and extract hits.

        Args:
            blast_xml: Path to BLAST XML file
            source: 'chain_blast' or 'domain_blast'

        Returns:
            List of BlastHit objects
        """
        if not os.path.exists(blast_xml):
            raise FileNotFoundError(f"BLAST XML not found: {blast_xml}")

        hits = []

        try:
            tree = ET.parse(blast_xml)
            root = tree.getroot()

            # Iterate through all iterations (usually just one)
            for iteration in root.findall(".//Iteration"):
                # Get query length for coverage calculation
                query_len_elem = iteration.find("Iteration_query-len")
                if query_len_elem is None:
                    continue
                query_len = int(query_len_elem.text)

                # Iterate through hits
                for hit in iteration.findall(".//Hit"):
                    # Extract hit information
                    hit_id_elem = hit.find("Hit_id")
                    hit_def_elem = hit.find("Hit_def")

                    if hit_id_elem is None or hit_def_elem is None:
                        continue

                    hit_id = hit_id_elem.text
                    hit_def = hit_def_elem.text

                    # Extract domain ID from hit definition
                    # For chain BLAST: Hit_def is "6ces A" format (PDB_ID + chain)
                    # For domain BLAST: Hit_def contains ECOD domain ID like "e6cesA1"
                    if source == "chain_blast":
                        # Chain BLAST: extract "pdb_id chain_id" from Hit_def
                        domain_id = self._extract_chain_id(hit_def)
                        ecod_uid = None  # Chain BLAST doesn't have uid
                    else:
                        # Domain BLAST: extract ECOD domain ID and uid
                        domain_id = self._extract_domain_id(hit_id, hit_def)
                        ecod_uid = self._extract_ecod_uid(hit_def)

                    if not domain_id:
                        continue

                    ecod_domain_id = domain_id

                    # Get best HSP (high-scoring segment pair)
                    hsps = hit.findall(".//Hsp")
                    if not hsps:
                        continue

                    # Use first (best) HSP
                    hsp = hsps[0]

                    # Extract HSP details
                    try:
                        evalue = float(hsp.find("Hsp_evalue").text)
                        bitscore = float(hsp.find("Hsp_bit-score").text)
                        align_len = int(hsp.find("Hsp_align-len").text)

                        # Get query range
                        query_from = int(hsp.find("Hsp_query-from").text)
                        query_to = int(hsp.find("Hsp_query-to").text)
                        query_range = f"{query_from}-{query_to}"

                        # Get hit range for coverage calculation
                        hit_from = int(hsp.find("Hsp_hit-from").text)
                        hit_to = int(hsp.find("Hsp_hit-to").text)
                        hit_len_elem = hit.find("Hit_len")
                        hit_len = int(hit_len_elem.text) if hit_len_elem is not None else 0

                        target_range = f"{hit_from}-{hit_to}"

                        # Calculate reference coverage
                        if hit_len > 0:
                            hit_coverage = (hit_to - hit_from + 1) / hit_len
                        else:
                            hit_coverage = 0.0

                        # Get identity
                        identity_elem = hsp.find("Hsp_identity")
                        identity_count = int(identity_elem.text) if identity_elem is not None else 0
                        identity = identity_count / align_len if align_len > 0 else 0.0

                        # Get family name from lookup
                        family_name = self.family_lookup.get(ecod_domain_id, "Unknown")

                        # Create BlastHit
                        blast_hit = BlastHit(
                            source=source,
                            ecod_domain_id=ecod_domain_id,
                            family_name=family_name,
                            query_range=query_range,
                            target_range=target_range,
                            reference_coverage=hit_coverage,
                            evalue=evalue,
                            bitscore=bitscore,
                            identity=identity,
                            alignment_length=align_len,
                            ecod_uid=ecod_uid,
                            reference_length=hit_len if hit_len > 0 else None,
                        )

                        hits.append(blast_hit)

                    except (AttributeError, ValueError, TypeError) as e:
                        # Skip malformed HSP
                        continue

        except Exception as e:
            print(f"Warning: Failed to parse {blast_xml}: {e}")
            return []

        return hits

    def _extract_chain_id(self, hit_def: str) -> Optional[str]:
        """
        Extract PDB ID and chain from chain BLAST hit definition.

        Args:
            hit_def: Hit definition (e.g., "6ces A" or "6ces_A")

        Returns:
            Chain identifier in format "pdb_chain" (e.g., "6ces_A")
        """
        # Chain BLAST format: "PDB_ID CHAIN_ID" (e.g., "6ces A")
        parts = hit_def.strip().split()
        if len(parts) >= 2:
            pdb_id = parts[0].lower()  # Normalize to lowercase
            chain_id = parts[1]
            return f"{pdb_id}_{chain_id}"
        elif len(parts) == 1 and "_" in parts[0]:
            # Already in "pdb_chain" format
            return parts[0].lower()
        else:
            # Can't parse - return as-is
            return hit_def if hit_def else None

    def _extract_domain_id(self, hit_id: str, hit_def: str) -> Optional[str]:
        """
        Extract ECOD domain ID from BLAST hit.

        Args:
            hit_id: Hit ID from BLAST (may be gnl|BL_ORD_ID|... internal ID)
            hit_def: Hit definition line containing actual domain ID

        Returns:
            ECOD domain ID or None

        Supported formats:
            - Traditional ECOD: "e6rw9A2 uid:2546239 range:... assignment:..."
            - UniProt-based (v293.1+): "B6A877_nD3 uid:4312072 range:... assignment:..."
            - Legacy chain format: "8abc_A e8abcA1,e8abcA2"
        """
        # First, check if hit_id is a valid ECOD domain ID (legacy format)
        if hit_id.startswith("e") and len(hit_id) > 5 and not hit_id.startswith("gnl|"):
            return hit_id

        # Extract first word from hit_def - this is the domain ID
        # Works for both traditional (e6rw9A2) and UniProt (B6A877_D3) formats
        parts = hit_def.split()
        if parts:
            domain_id = parts[0]
            # Validate it looks like a domain ID (not just noise)
            # Traditional: e6rw9A2 (starts with 'e', alphanumeric)
            # UniProt: {UNP_ID}_D{num} (e.g., B6A877_D3, A0A1P8B6J1_D1)
            if domain_id.startswith("e") and len(domain_id) > 5:
                return domain_id
            elif "_D" in domain_id or "_nD" in domain_id:
                # UniProt-based domain ID (e.g., B6A877_D3, B6A877_nD3)
                return domain_id
            elif len(domain_id) > 3 and domain_id[0].isalnum():
                # Generic alphanumeric ID - accept it
                return domain_id

        # Fallback: use hit_id only if it's not an internal BLAST ID
        if not hit_id.startswith("gnl|BL_ORD_ID"):
            return hit_id

        # Last resort: return first word of hit_def anyway
        return parts[0] if parts else None

    def _extract_ecod_uid(self, hit_def: str) -> Optional[int]:
        """
        Extract ECOD unique ID (uid) from BLAST hit definition.

        Handles two formats:
        1. Tagged format: "B6A877_nD3 uid:4312072 range:... assignment:..."
        2. v293 format: "e6rw9E2 E:21-80,E:100-297,... 002546267" (uid is last token)

        Args:
            hit_def: Hit definition line

        Returns:
            ECOD uid as integer, or None if not found
        """
        import re

        # Format 1: Tagged pattern "uid:DIGITS" (e.g., "uid:4312072")
        match = re.search(r'uid:(\d+)', hit_def)
        if match:
            return int(match.group(1))

        # Format 2: v293 format - uid is last token and is numeric (zero-padded)
        # e.g., "e6rw9E2 E:21-80,E:100-297,E:446-1066,E:1736-1937 002546267"
        parts = hit_def.split()
        if len(parts) >= 2:
            last_token = parts[-1]
            # Check if last token is purely numeric (zero-padded uid)
            if last_token.isdigit():
                return int(last_token)

        return None

    def parse_hhsearch_hhr(self, hhr_file: str, source: str) -> List[HHsearchHit]:
        """
        Parse HHsearch HHR file and extract hits.

        Args:
            hhr_file: Path to HHR file
            source: Source type (usually 'hhsearch')

        Returns:
            List of HHsearchHit objects
        """
        if not os.path.exists(hhr_file):
            raise FileNotFoundError(f"HHR file not found: {hhr_file}")

        hits = []

        try:
            # Use the HHsearchParser from parsers module
            from pyecod_prod.parsers.hhsearch_parser import HHsearchParser

            parser = HHsearchParser()
            hhr_hits = parser.parse_hhr(hhr_file)

            # Convert to HHsearchHit format for summary
            for hit in hhr_hits:
                # Calculate template coverage
                # Parse template range to get length
                template_start, template_end = self._parse_range_tuple(hit.template_range)
                if hit.template_length > 0:
                    template_coverage = (template_end - template_start + 1) / hit.template_length
                else:
                    template_coverage = 0.0

                # Get family name from lookup
                family_name = self.family_lookup.get(hit.hit_id, "Unknown")

                hhsearch_hit = HHsearchHit(
                    source=source,
                    ecod_domain_id=hit.hit_id,
                    family_name=family_name,
                    query_range=hit.query_range,
                    target_range=hit.template_range,
                    reference_coverage=template_coverage,
                    evalue=hit.evalue,
                    probability=hit.probability,
                    score=hit.score,
                )

                hits.append(hhsearch_hit)

        except Exception as e:
            print(f"Warning: Failed to parse {hhr_file}: {e}")
            return []

        return hits

    def _parse_range_tuple(self, range_str: str) -> tuple:
        """Parse range string like '10-110' to (10, 110)"""
        import re
        match = re.match(r"(\d+)-(\d+)", range_str)
        if match:
            return int(match.group(1)), int(match.group(2))
        return 0, 0

    def generate_summary(
        self,
        pdb_id: str,
        chain_id: str,
        sequence: str,
        sequence_length: int,
        chain_blast_xml: Optional[str] = None,
        domain_blast_xml: Optional[str] = None,
        hhsearch_xml: Optional[str] = None,
        output_path: Optional[str] = None,
        batch_id: Optional[str] = None,
        exclude_self: bool = False,
        exclude_domain_ids: Optional[set] = None,
    ) -> str:
        """
        Generate domain summary XML from BLAST and HHsearch results.

        Output format per PYECOD_MINI_API_SPEC.md.

        Args:
            pdb_id: PDB ID
            chain_id: Chain ID
            sequence: Amino acid sequence (REQUIRED by pyecod_mini)
            sequence_length: Protein sequence length
            chain_blast_xml: Path to chain BLAST XML (optional)
            domain_blast_xml: Path to domain BLAST XML (optional)
            hhsearch_xml: Path to HHsearch HHR file (optional, Phase 3)
            output_path: Output path (auto-generated if None)
            batch_id: Optional batch ID for tracking
            exclude_self: Omit hits to the query's own structure (same PDB id),
                producing a pre-masked summary for non-circular rep validation.
            exclude_domain_ids: Omit hits to these reference ECOD domain ids.

        Returns:
            Path to generated summary XML
        """
        exclude_domain_ids = exclude_domain_ids or set()
        # Normalize exclude ids (match with and without leading 'e')
        excl_ids = set()
        for d in exclude_domain_ids:
            excl_ids.add(d)
            excl_ids.add(d[1:] if d.startswith("e") else d)
        self._masked_hit_count = 0
        # Create summary XML per API spec
        root = ET.Element("domain_summary")
        root.set("version", "1.0")  # Schema version

        # Protein metadata (attributes per API spec)
        protein = ET.SubElement(root, "protein")
        protein.set("pdb_id", pdb_id.lower())
        protein.set("chain_id", chain_id)
        protein.set("length", str(sequence_length))

        # Sequence (REQUIRED by pyecod_mini)
        sequence_elem = ET.SubElement(protein, "sequence")
        sequence_elem.text = sequence

        # Evidence container (per API spec)
        evidence = ET.SubElement(root, "evidence")

        # Parse domain BLAST
        if domain_blast_xml and os.path.exists(domain_blast_xml):
            domain_hits = self.parse_blast_xml(domain_blast_xml, "domain_blast")
            for hit in domain_hits:
                if self._hit_excluded(hit.ecod_domain_id, pdb_id, exclude_self, excl_ids):
                    continue
                self._add_blast_hit(evidence, hit)

        # Parse chain BLAST
        if chain_blast_xml and os.path.exists(chain_blast_xml):
            chain_hits = self.parse_blast_xml(chain_blast_xml, "chain_blast")
            for hit in chain_hits:
                if self._hit_excluded(hit.ecod_domain_id, pdb_id, exclude_self, excl_ids):
                    continue
                self._add_blast_hit(evidence, hit)

        # Parse HHsearch results (Phase 3)
        if hhsearch_xml and os.path.exists(hhsearch_xml):
            hhsearch_hits = self.parse_hhsearch_hhr(hhsearch_xml, "hhsearch")
            for hit in hhsearch_hits:
                if self._hit_excluded(hit.ecod_domain_id, pdb_id, exclude_self, excl_ids):
                    continue
                self._add_hhsearch_hit(evidence, hit)

        # Metadata section (per API spec)
        metadata = ET.SubElement(root, "metadata")
        if batch_id:
            batch_elem = ET.SubElement(metadata, "batch_id")
            batch_elem.text = batch_id
        timestamp_elem = ET.SubElement(metadata, "timestamp")
        timestamp_elem.text = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        # Record evidence masking (non-circular rep validation), if any
        if exclude_self or excl_ids:
            masked_elem = ET.SubElement(metadata, "masked_evidence")
            masked_elem.set("count", str(self._masked_hit_count))
            masked_elem.set("exclude_self", str(exclude_self).lower())
            if excl_ids:
                masked_elem.set("exclude_domain_ids", str(len(exclude_domain_ids)))

        # Generate output path if not provided
        if output_path is None:
            output_path = f"/tmp/{pdb_id}_{chain_id}.summary.xml"

        # Write XML with pretty formatting
        self._write_pretty_xml(root, output_path)

        return output_path

    def _add_blast_hit(self, evidence: ET.Element, hit: BlastHit):
        """
        Add BLAST hit as <hit> element per API spec.

        Args:
            evidence: Evidence container XML element
            hit: BlastHit object
        """
        hit_elem = ET.SubElement(evidence, "hit")
        hit_elem.set("type", hit.source)  # chain_blast or domain_blast
        hit_elem.set("target", hit.ecod_domain_id)
        hit_elem.set("target_family", hit.family_name)
        hit_elem.set("evalue", f"{hit.evalue:.2e}")
        hit_elem.set("bitscore", f"{hit.bitscore:.1f}")
        hit_elem.set("identity", f"{hit.identity:.2f}")
        hit_elem.set("coverage", f"{hit.reference_coverage:.2f}")
        hit_elem.set("query_range", hit.query_range)
        hit_elem.set("target_range", hit.target_range)
        # Add uid and reference_length for uid-based lookups
        if hit.ecod_uid is not None:
            hit_elem.set("ecod_uid", str(hit.ecod_uid))
        if hit.reference_length is not None:
            hit_elem.set("reference_length", str(hit.reference_length))
        # Classification (enables F-group / T-group exclusion in pyecod_mini)
        self._add_classification(hit_elem, hit.ecod_domain_id)

    def _hit_excluded(
        self, ecod_domain_id: str, query_pdb: str, exclude_self: bool, excl_ids: set
    ) -> bool:
        """Return True if this hit should be masked from the summary.

        Used for optional pre-masked summary generation (non-circular rep
        validation). Increments self._masked_hit_count when a hit is excluded.
        """
        if not exclude_self and not excl_ids:
            return False

        excluded = False
        if exclude_self:
            hit_pdb = self._extract_hit_pdb(ecod_domain_id)
            if hit_pdb and hit_pdb == query_pdb.lower():
                excluded = True

        if not excluded and excl_ids and ecod_domain_id:
            normalized = ecod_domain_id[1:] if ecod_domain_id.startswith("e") else ecod_domain_id
            if ecod_domain_id in excl_ids or normalized in excl_ids:
                excluded = True

        if excluded:
            self._masked_hit_count += 1
        return excluded

    @staticmethod
    def _extract_hit_pdb(ecod_domain_id: str) -> Optional[str]:
        """Extract the lowercase PDB id from a hit's domain/chain identifier.

        Handles 'e1gcyA2' (domain BLAST) -> '1gcy' and '1gcy_A' (chain BLAST) -> '1gcy'.
        """
        if not ecod_domain_id:
            return None
        s = ecod_domain_id
        if "_" in s:  # chain BLAST "pdb_chain"
            return s.split("_")[0].lower()
        if s.startswith("e") and len(s) >= 5:
            return s[1:5].lower()
        return None

    def _add_classification(self, hit_elem: ET.Element, ecod_domain_id: str):
        """Emit x/h/t/f group attributes from the classification lookup, if present."""
        groups = self.classification_lookup.get(ecod_domain_id)
        if not groups:
            return
        for key in ("t_group", "h_group", "x_group", "f_group"):
            val = groups.get(key)
            if val:
                hit_elem.set(key, val)

    def _add_hhsearch_hit(self, evidence: ET.Element, hit: HHsearchHit):
        """
        Add HHsearch hit as <hit> element per API spec.

        Args:
            evidence: Evidence container XML element
            hit: HHsearchHit object
        """
        hit_elem = ET.SubElement(evidence, "hit")
        hit_elem.set("type", hit.source)  # hhsearch
        hit_elem.set("target", hit.ecod_domain_id)
        hit_elem.set("target_family", hit.family_name)
        hit_elem.set("probability", f"{hit.probability:.1f}")
        hit_elem.set("evalue", f"{hit.evalue:.2e}")
        hit_elem.set("score", f"{hit.score:.1f}")
        hit_elem.set("query_range", hit.query_range)
        hit_elem.set("target_range", hit.target_range)
        # Add uid and reference_length for uid-based lookups
        if hit.ecod_uid is not None:
            hit_elem.set("ecod_uid", str(hit.ecod_uid))
        if hit.reference_length is not None:
            hit_elem.set("reference_length", str(hit.reference_length))
        # Classification (enables F-group / T-group exclusion in pyecod_mini)
        self._add_classification(hit_elem, hit.ecod_domain_id)

    def _write_pretty_xml(self, root: ET.Element, output_path: str):
        """
        Write XML with pretty formatting and XML declaration.

        Args:
            root: Root XML element
            output_path: Output file path
        """
        # Convert to string
        xml_str = ET.tostring(root, encoding="unicode")

        # Parse and write with pretty formatting
        from xml.dom import minidom

        dom = minidom.parseString(xml_str)
        pretty_xml = dom.toprettyxml(indent="  ", encoding=None)

        # Remove blank lines but keep XML declaration
        lines = [line for line in pretty_xml.split("\n") if line.strip()]

        with open(output_path, "w") as f:
            f.write("\n".join(lines))


def main():
    """Command-line interface for testing"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate domain summary XML from BLAST results (per PYECOD_MINI_API_SPEC.md)"
    )
    parser.add_argument("pdb_id", help="PDB ID")
    parser.add_argument("chain_id", help="Chain ID")
    parser.add_argument("--sequence", required=True, help="Amino acid sequence")
    parser.add_argument("--length", type=int, required=True, help="Sequence length")
    parser.add_argument("--chain-blast", help="Chain BLAST XML file")
    parser.add_argument("--domain-blast", help="Domain BLAST XML file")
    parser.add_argument("--hhsearch", help="HHsearch HHR file")
    parser.add_argument("--output", "-o", help="Output path")
    parser.add_argument("--batch-id", help="Batch ID")
    parser.add_argument("--reference", default="develop291", help="Reference version")

    args = parser.parse_args()

    generator = SummaryGenerator(reference_version=args.reference)

    output_path = generator.generate_summary(
        pdb_id=args.pdb_id,
        chain_id=args.chain_id,
        sequence=args.sequence,
        sequence_length=args.length,
        chain_blast_xml=args.chain_blast,
        domain_blast_xml=args.domain_blast,
        hhsearch_xml=args.hhsearch,
        output_path=args.output,
        batch_id=args.batch_id,
    )

    print(f"Generated summary: {output_path}")


if __name__ == "__main__":
    main()
