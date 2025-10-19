#!/usr/bin/env python3
"""
Wrapper for pyecod-mini domain partitioning.

Runs pyecod-mini on domain summary files and parses the results.
"""

import os
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Domain:
    """Represent a partitioned domain"""

    domain_id: str
    range: str
    size: int
    source: str  # 'chain_blast', 'domain_blast', 'hhsearch', etc.
    family: str  # ECOD family name
    confidence: Optional[float] = None


@dataclass
class PartitionResult:
    """Result from domain partitioning"""

    pdb_id: str
    chain_id: str
    sequence_length: int
    domains: List[Domain]
    domain_count: int
    partition_coverage: float  # Fraction of sequence covered by domains
    partition_quality: str  # 'good', 'low_coverage', 'fragmentary', 'failed'
    partition_xml_path: str
    error_message: Optional[str] = None


class PartitionRunner:
    """
    Run pyecod-mini domain partitioning.

    Wraps the pyecod-mini executable and parses results.
    """

    def __init__(self, pyecod_mini_path: str = "pyecod-mini"):
        """
        Initialize partition runner.

        Args:
            pyecod_mini_path: Path to pyecod-mini executable
        """
        self.pyecod_mini_path = pyecod_mini_path

        # Verify pyecod-mini is available
        try:
            result = subprocess.run(
                [self.pyecod_mini_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                print(f"Warning: pyecod-mini may not be properly installed")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"Warning: Could not verify pyecod-mini: {e}")

    def partition(
        self,
        summary_xml: str,
        output_dir: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> PartitionResult:
        """
        Run pyecod-mini on a summary XML file.

        Args:
            summary_xml: Path to domain summary XML
            output_dir: Output directory for partition XML (default: /tmp)
            batch_id: Optional batch ID for organization

        Returns:
            PartitionResult with parsed domains and metrics
        """
        if not os.path.exists(summary_xml):
            raise FileNotFoundError(f"Summary XML not found: {summary_xml}")

        # Parse summary to get metadata
        pdb_id, chain_id, seq_len = self._parse_summary_metadata(summary_xml)

        # Determine output path
        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            partition_xml = output_dir / f"{pdb_id}_{chain_id}.domains.xml"
        else:
            partition_xml = Path(f"/tmp/{pdb_id}_{chain_id}.domains.xml")

        # Build pyecod-mini command
        cmd = [
            self.pyecod_mini_path,
            f"{pdb_id}_{chain_id}",
            "--summary-xml",
            summary_xml,
            "--output",
            str(partition_xml),
        ]

        if batch_id:
            cmd.extend(["--batch-id", batch_id])

        # Run pyecod-mini
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                error_msg = f"pyecod-mini failed: {result.stderr}"
                print(f"ERROR: {error_msg}")

                return PartitionResult(
                    pdb_id=pdb_id,
                    chain_id=chain_id,
                    sequence_length=seq_len,
                    domains=[],
                    domain_count=0,
                    partition_coverage=0.0,
                    partition_quality="failed",
                    partition_xml_path=str(partition_xml),
                    error_message=error_msg,
                )

        except subprocess.TimeoutExpired:
            error_msg = "pyecod-mini timed out after 5 minutes"
            print(f"ERROR: {error_msg}")

            return PartitionResult(
                pdb_id=pdb_id,
                chain_id=chain_id,
                sequence_length=seq_len,
                domains=[],
                domain_count=0,
                partition_coverage=0.0,
                partition_quality="failed",
                partition_xml_path=str(partition_xml),
                error_message=error_msg,
            )

        # Parse partition XML
        if not partition_xml.exists():
            error_msg = f"Partition XML not created: {partition_xml}"
            print(f"ERROR: {error_msg}")

            return PartitionResult(
                pdb_id=pdb_id,
                chain_id=chain_id,
                sequence_length=seq_len,
                domains=[],
                domain_count=0,
                partition_coverage=0.0,
                partition_quality="failed",
                partition_xml_path=str(partition_xml),
                error_message=error_msg,
            )

        # Parse domains from partition XML
        domains = self._parse_partition_xml(str(partition_xml))

        # Calculate coverage
        coverage = self._calculate_coverage(domains, seq_len)

        # Assess quality
        quality = self._assess_quality(domains, coverage, seq_len)

        return PartitionResult(
            pdb_id=pdb_id,
            chain_id=chain_id,
            sequence_length=seq_len,
            domains=domains,
            domain_count=len(domains),
            partition_coverage=coverage,
            partition_quality=quality,
            partition_xml_path=str(partition_xml),
            error_message=None,
        )

    def _parse_summary_metadata(self, summary_xml: str) -> tuple:
        """
        Parse metadata from summary XML.

        Returns:
            (pdb_id, chain_id, sequence_length)
        """
        try:
            tree = ET.parse(summary_xml)
            root = tree.getroot()

            protein = root.find("protein")
            if protein is None:
                raise ValueError("No protein element found")

            pdb_id = protein.findtext("pdb_id", "unknown")
            chain_id = protein.findtext("chain_id", "unknown")
            seq_len = int(protein.findtext("length", "0"))

            return pdb_id, chain_id, seq_len

        except Exception as e:
            print(f"Warning: Failed to parse summary metadata: {e}")
            return "unknown", "unknown", 0

    def _parse_partition_xml(self, partition_xml: str) -> List[Domain]:
        """
        Parse domains from partition XML.

        Args:
            partition_xml: Path to partition XML

        Returns:
            List of Domain objects
        """
        domains = []

        try:
            tree = ET.parse(partition_xml)
            root = tree.getroot()

            for domain_elem in root.findall(".//domain"):
                domain_id = domain_elem.get("id", "")
                range_str = domain_elem.get("range", "")
                size = int(domain_elem.get("size", "0"))
                source = domain_elem.get("source", "unknown")
                family = domain_elem.get("family", "")

                domain = Domain(
                    domain_id=domain_id,
                    range=range_str,
                    size=size,
                    source=source,
                    family=family,
                )

                domains.append(domain)

        except Exception as e:
            print(f"Warning: Failed to parse partition XML: {e}")

        return domains

    def _calculate_coverage(self, domains: List[Domain], sequence_length: int) -> float:
        """
        Calculate fraction of sequence covered by domains.

        Args:
            domains: List of Domain objects
            sequence_length: Total sequence length

        Returns:
            Coverage fraction (0.0-1.0)
        """
        if sequence_length == 0:
            return 0.0

        # Track covered positions
        covered = set()

        for domain in domains:
            # Parse range string (e.g., "10-110" or "10-110,150-200")
            for segment in domain.range.split(","):
                segment = segment.strip()
                if "-" in segment:
                    try:
                        start, end = map(int, segment.split("-"))
                        for pos in range(start, end + 1):
                            covered.add(pos)
                    except ValueError:
                        continue

        coverage = len(covered) / sequence_length
        return coverage

    def _assess_quality(
        self, domains: List[Domain], coverage: float, sequence_length: int
    ) -> str:
        """
        Assess partition quality.

        Args:
            domains: List of Domain objects
            coverage: Partition coverage
            sequence_length: Total sequence length

        Returns:
            Quality string: 'good', 'low_coverage', 'fragmentary', 'no_domains'
        """
        if len(domains) == 0:
            return "no_domains"

        if coverage >= 0.80:
            return "good"
        elif coverage >= 0.50:
            return "low_coverage"
        else:
            return "fragmentary"


def main():
    """Command-line interface for testing"""
    import argparse

    parser = argparse.ArgumentParser(description="Run pyecod-mini domain partitioning")
    parser.add_argument("summary_xml", help="Path to domain summary XML")
    parser.add_argument("--output-dir", "-o", help="Output directory")
    parser.add_argument("--batch-id", help="Batch ID")
    parser.add_argument("--pyecod-mini", default="pyecod-mini", help="Path to pyecod-mini")

    args = parser.parse_args()

    runner = PartitionRunner(pyecod_mini_path=args.pyecod_mini)

    result = runner.partition(
        summary_xml=args.summary_xml,
        output_dir=args.output_dir,
        batch_id=args.batch_id,
    )

    print(f"\nPartition Results:")
    print(f"  PDB: {result.pdb_id}_{result.chain_id}")
    print(f"  Sequence length: {result.sequence_length}")
    print(f"  Domains found: {result.domain_count}")
    print(f"  Coverage: {result.partition_coverage:.1%}")
    print(f"  Quality: {result.partition_quality}")
    print(f"  Output: {result.partition_xml_path}")

    if result.error_message:
        print(f"  Error: {result.error_message}")

    # Show domains
    if result.domains:
        print(f"\n  Domains:")
        for domain in result.domains:
            print(f"    {domain.domain_id}: {domain.range} ({domain.size} aa) [{domain.source}]")


if __name__ == "__main__":
    main()
