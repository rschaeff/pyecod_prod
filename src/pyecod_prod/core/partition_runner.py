#!/usr/bin/env python3
"""
Wrapper for pyecod-mini domain partitioning.

Integrates with pyecod_mini library (preferred) or CLI (fallback).
Implements ECOD-specific quality assessment per PYECOD_MINI_API_SPEC.md.
"""

import logging
import os
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Try to import pyecod_mini library (preferred)
try:
    from pyecod_mini import partition_protein, PartitionError as MiniPartitionError
    LIBRARY_AVAILABLE = True
except ImportError:
    LIBRARY_AVAILABLE = False
    MiniPartitionError = Exception  # Fallback for type hints

logger = logging.getLogger(__name__)


@dataclass
class Domain:
    """Represent a partitioned domain (pyecod_prod format)."""

    domain_id: str
    range: str
    size: int
    source: str  # 'chain_blast', 'domain_blast', 'hhsearch', etc.
    family: str  # ECOD family name
    confidence: Optional[float] = None


@dataclass
class PartitionResult:
    """
    Result from domain partitioning (pyecod_prod format).

    Includes ECOD-specific quality assessment.
    """

    pdb_id: str
    chain_id: str
    sequence_length: int
    domains: List[Domain]
    domain_count: int
    partition_coverage: float  # Fraction of sequence covered by domains
    partition_quality: str  # ECOD quality: 'good', 'low_coverage', 'fragmentary', 'no_domains'
    partition_xml_path: str
    algorithm_version: Optional[str] = None  # pyecod_mini version used
    error_message: Optional[str] = None


class PartitionRunner:
    """
    Run pyecod-mini domain partitioning.

    Hybrid implementation:
    1. Prefers library API (if pyecod_mini package installed)
    2. Falls back to CLI (if library not available)

    Applies ECOD-specific quality assessment per production policy.

    See PYECOD_MINI_API_SPEC.md for API contract.
    """

    def __init__(self, pyecod_mini_path: str = "pyecod-mini", use_library: bool = True):
        """
        Initialize partition runner.

        Args:
            pyecod_mini_path: Path to pyecod-mini CLI executable (fallback)
            use_library: Prefer library API if available (default: True)
        """
        self.pyecod_mini_path = pyecod_mini_path
        self.use_library = use_library and LIBRARY_AVAILABLE

        if self.use_library:
            logger.info("pyecod_mini library available - using library API")
        else:
            logger.info("pyecod_mini library not available - using CLI fallback")
            self._verify_cli_available()

    def _verify_cli_available(self):
        """Verify pyecod-mini CLI is available."""
        try:
            result = subprocess.run(
                [self.pyecod_mini_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                logger.warning("pyecod-mini CLI may not be properly installed")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning(f"Could not verify pyecod-mini CLI: {e}")

    def partition(
        self,
        summary_xml: str,
        output_dir: str,
        batch_id: Optional[str] = None,
        blast_dir: Optional[str] = None,
    ) -> PartitionResult:
        """
        Run pyecod-mini on a summary XML file.

        Args:
            summary_xml: Path to domain_summary.xml (input)
            output_dir: Output directory for partition.xml (REQUIRED)
            batch_id: Optional batch ID for tracking
            blast_dir: Optional path to directory containing BLAST XML files
                       (enables chain BLAST decomposition)

        Returns:
            PartitionResult with domains, coverage, and ECOD quality assessment

        Raises:
            FileNotFoundError: If summary_xml doesn't exist
        """
        if not os.path.exists(summary_xml):
            raise FileNotFoundError(f"Summary XML not found: {summary_xml}")

        # Parse summary to get metadata (for fallback and validation)
        pdb_id, chain_id, seq_len = self._parse_summary_metadata(summary_xml)

        # Ensure output directory exists
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        partition_xml = output_path / f"{pdb_id}_{chain_id}.partition.xml"

        # Call pyecod_mini (library or CLI)
        if self.use_library:
            result = self._partition_via_library(
                summary_xml=summary_xml,
                partition_xml=partition_xml,
                batch_id=batch_id,
                pdb_id=pdb_id,
                chain_id=chain_id,
                seq_len=seq_len,
                blast_dir=blast_dir,
            )
        else:
            result = self._partition_via_cli(
                summary_xml=summary_xml,
                partition_xml=partition_xml,
                batch_id=batch_id,
                pdb_id=pdb_id,
                chain_id=chain_id,
                seq_len=seq_len,
                blast_dir=blast_dir,
            )

        return result

    def _partition_via_library(
        self,
        summary_xml: Path,
        partition_xml: Path,
        batch_id: Optional[str],
        pdb_id: str,
        chain_id: str,
        seq_len: int,
        blast_dir: Optional[str] = None,
    ) -> PartitionResult:
        """
        Call pyecod_mini library API.

        This is the preferred method - better error handling, no subprocess overhead.
        """
        try:
            # Call pyecod_mini library
            mini_result = partition_protein(
                summary_xml=summary_xml,
                output_xml=partition_xml,
                pdb_id=pdb_id,
                chain_id=chain_id,
                batch_id=batch_id,
                blast_dir=blast_dir,  # Pass BLAST directory for alignment data
            )

            # Convert pyecod_mini domains to pyecod_prod format
            domains = [
                Domain(
                    domain_id=d.domain_id,
                    range=d.range_string,
                    size=d.residue_count,
                    source=d.source,
                    family=d.family_name,
                    confidence=d.confidence,
                )
                for d in mini_result.domains
            ]

            # Apply ECOD-specific quality assessment
            quality = self._assess_ecod_quality(
                domain_count=len(domains),
                coverage=mini_result.coverage,
                sequence_length=mini_result.sequence_length,
            )

            logger.info(
                f"{pdb_id}_{chain_id}: Partitioned via library - "
                f"{len(domains)} domains, {mini_result.coverage:.2%} coverage, "
                f"quality={quality}, version={mini_result.algorithm_version}"
            )

            return PartitionResult(
                pdb_id=mini_result.pdb_id,
                chain_id=mini_result.chain_id,
                sequence_length=mini_result.sequence_length,
                domains=domains,
                domain_count=len(domains),
                partition_coverage=mini_result.coverage,  # Trust pyecod_mini's coverage
                partition_quality=quality,  # ECOD policy
                partition_xml_path=str(partition_xml),
                algorithm_version=mini_result.algorithm_version,
                error_message=mini_result.error_message if not mini_result.success else None,
            )

        except MiniPartitionError as e:
            error_msg = f"Partitioning failed: {e}"
            logger.error(f"{pdb_id}_{chain_id}: {error_msg}")

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

        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            logger.exception(f"{pdb_id}_{chain_id}: {error_msg}")

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

    def _partition_via_cli(
        self,
        summary_xml: Path,
        partition_xml: Path,
        batch_id: Optional[str],
        pdb_id: str,
        chain_id: str,
        seq_len: int,
        blast_dir: Optional[str] = None,
    ) -> PartitionResult:
        """
        Call pyecod_mini CLI via subprocess.

        Fallback when library not available.
        """
        # Build command
        cmd = [
            self.pyecod_mini_path,
            f"{pdb_id}_{chain_id}",
            "--summary-xml",
            str(summary_xml),
            "--output",
            str(partition_xml),
        ]

        if batch_id:
            cmd.extend(["--batch-id", batch_id])

        # Note: CLI doesn't support --blast-dir yet, will infer from summary-xml path
        # blast_dir parameter accepted for API consistency but not used in CLI mode

        # Run pyecod-mini
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                check=False,  # Don't raise on non-zero exit
            )

            if result.returncode != 0:
                error_msg = f"CLI failed (exit {result.returncode}): {result.stderr}"
                logger.error(f"{pdb_id}_{chain_id}: {error_msg}")

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
            error_msg = "CLI timed out after 5 minutes"
            logger.error(f"{pdb_id}_{chain_id}: {error_msg}")

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

        # Verify output file exists
        if not partition_xml.exists():
            error_msg = f"Partition XML not created: {partition_xml}"
            logger.error(f"{pdb_id}_{chain_id}: {error_msg}")

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

        # Parse partition XML to extract results
        domains, coverage, algo_version = self._parse_partition_xml(str(partition_xml))

        # Apply ECOD quality assessment
        quality = self._assess_ecod_quality(
            domain_count=len(domains),
            coverage=coverage,
            sequence_length=seq_len,
        )

        logger.info(
            f"{pdb_id}_{chain_id}: Partitioned via CLI - "
            f"{len(domains)} domains, {coverage:.2%} coverage, "
            f"quality={quality}, version={algo_version}"
        )

        return PartitionResult(
            pdb_id=pdb_id,
            chain_id=chain_id,
            sequence_length=seq_len,
            domains=domains,
            domain_count=len(domains),
            partition_coverage=coverage,  # From pyecod_mini XML
            partition_quality=quality,  # ECOD policy
            partition_xml_path=str(partition_xml),
            algorithm_version=algo_version,
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

            pdb_id = protein.get("pdb_id") or protein.findtext("pdb_id", "unknown")
            chain_id = protein.get("chain_id") or protein.findtext("chain_id", "unknown")
            seq_len = int(protein.get("length") or protein.findtext("length", "0"))

            return pdb_id, chain_id, seq_len

        except Exception as e:
            logger.warning(f"Failed to parse summary metadata: {e}")
            return "unknown", "unknown", 0

    def _parse_partition_xml(self, partition_xml: str) -> tuple:
        """
        Parse partition XML output from pyecod_mini.

        Returns:
            (domains, coverage, algorithm_version)
        """
        domains = []
        coverage = 0.0
        algo_version = None

        try:
            tree = ET.parse(partition_xml)
            root = tree.getroot()

            # Get algorithm version (per API spec)
            algo_version = root.get("algorithm_version")

            # Get coverage (per API spec - pyecod_mini provides this)
            protein = root.find("protein")
            if protein is not None:
                coverage_elem = protein.find("coverage")
                if coverage_elem is not None:
                    coverage = float(coverage_elem.text)

            # Parse domains
            for domain_elem in root.findall(".//domain"):
                domain_id = domain_elem.get("id", "")
                range_str = domain_elem.get("range", "")
                size = int(domain_elem.get("size", "0"))
                source = domain_elem.get("source", "unknown")
                family = domain_elem.get("family", "")
                confidence_str = domain_elem.get("confidence")
                confidence = float(confidence_str) if confidence_str else None

                domain = Domain(
                    domain_id=domain_id,
                    range=range_str,
                    size=size,
                    source=source,
                    family=family,
                    confidence=confidence,
                )

                domains.append(domain)

        except Exception as e:
            logger.warning(f"Failed to parse partition XML: {e}")

        return domains, coverage, algo_version

    def _assess_ecod_quality(
        self, domain_count: int, coverage: float, sequence_length: int
    ) -> str:
        """
        Assess partition quality using ECOD production thresholds.

        IMPORTANT: This is ECOD-specific policy, NOT part of pyecod_mini algorithm.
        Thresholds can be adjusted based on production experience.

        Args:
            domain_count: Number of domains found
            coverage: Fraction of sequence covered (0.0-1.0)
            sequence_length: Total sequence length

        Returns:
            Quality string: 'good', 'low_coverage', 'fragmentary', 'no_domains'
        """
        if domain_count == 0:
            return "no_domains"

        # ECOD production thresholds (tunable)
        if coverage >= 0.80:
            return "good"  # Production-ready
        elif coverage >= 0.50:
            return "low_coverage"  # May need manual review
        else:
            return "fragmentary"  # Likely incomplete


def main():
    """Command-line interface for testing."""
    import argparse

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    parser = argparse.ArgumentParser(description="Run pyecod-mini domain partitioning")
    parser.add_argument("summary_xml", help="Path to domain summary XML")
    parser.add_argument("--output-dir", "-o", required=True, help="Output directory")
    parser.add_argument("--batch-id", help="Batch ID")
    parser.add_argument("--pyecod-mini", default="pyecod-mini", help="Path to pyecod-mini CLI")
    parser.add_argument("--use-library", action="store_true", default=True, help="Prefer library API")
    parser.add_argument("--use-cli", action="store_true", help="Force CLI usage")

    args = parser.parse_args()

    use_library = args.use_library and not args.use_cli

    runner = PartitionRunner(
        pyecod_mini_path=args.pyecod_mini,
        use_library=use_library
    )

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
    print(f"  Quality (ECOD): {result.partition_quality}")
    print(f"  Algorithm version: {result.algorithm_version}")
    print(f"  Output: {result.partition_xml_path}")

    if result.error_message:
        print(f"  Error: {result.error_message}")

    # Show domains
    if result.domains:
        print(f"\n  Domains:")
        for domain in result.domains:
            print(
                f"    {domain.domain_id}: {domain.range} ({domain.size} aa) "
                f"[{domain.source}] {domain.family}"
            )


if __name__ == "__main__":
    main()
