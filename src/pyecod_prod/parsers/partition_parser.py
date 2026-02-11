"""
Parser for pyecod_mini partition XML files.

Extracts domain information from partition XMLs for auto-accession to ecod_commons.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any


@dataclass
class DomainEvidence:
    """Evidence supporting a domain assignment."""
    source_type: str
    source_id: str
    domain_id: str
    evalue: Optional[float] = None
    confidence: float = 0.0


@dataclass
class PartitionDomain:
    """A domain extracted from a partition XML."""
    internal_id: str  # "d1", "d2", etc.
    range_definition: str  # Raw format "1-91"
    family: Optional[str] = None  # F-group like "2.1.1"
    t_group: Optional[str] = None
    h_group: Optional[str] = None
    x_group: Optional[str] = None
    confidence: float = 0.0
    reference_ecod_domain_id: Optional[str] = None
    is_discontinuous: bool = False
    evidence_count: int = 0
    source: Optional[str] = None  # "chain_blast_decomposed", etc.
    primary_evidence: Optional[DomainEvidence] = None

    def get_chain_prefixed_range(self, chain_id: str) -> str:
        """Convert raw range to chain-prefixed format for ecod_commons."""
        # Handle discontinuous ranges (comma-separated)
        parts = self.range_definition.split(',')
        prefixed_parts = []
        for part in parts:
            part = part.strip()
            # Check if already has chain prefix
            if ':' in part:
                prefixed_parts.append(part)
            else:
                prefixed_parts.append(f"{chain_id}:{part}")
        return ','.join(prefixed_parts)


@dataclass
class PartitionMetadata:
    """Metadata from partition XML."""
    algorithm_version: str = ""
    git_commit: str = ""
    timestamp: str = ""
    batch_id: str = ""
    domain_summary_path: str = ""
    sequence_length: int = 0
    domain_count: int = 0
    total_coverage: float = 0.0
    residues_assigned: int = 0


@dataclass
class PartitionResult:
    """Complete result from parsing a partition XML."""
    pdb_id: str
    chain_id: str
    is_classified: bool
    reference: str  # "mini_pyecod"
    metadata: PartitionMetadata
    domains: List[PartitionDomain] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Return the total coverage."""
        return self.metadata.total_coverage


def parse_partition_xml(xml_path: Path) -> PartitionResult:
    """
    Parse a partition XML file and extract domain information.

    Args:
        xml_path: Path to the partition XML file

    Returns:
        PartitionResult with all extracted data

    Raises:
        FileNotFoundError: If XML file doesn't exist
        ET.ParseError: If XML is malformed
        ValueError: If required elements are missing
    """
    if not xml_path.exists():
        raise FileNotFoundError(f"Partition XML not found: {xml_path}")

    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Root element attributes
    pdb_id = root.get('pdb_id', '')
    chain_id = root.get('chain_id', '')
    is_classified = root.get('is_classified', 'false').lower() == 'true'
    reference = root.get('reference', 'mini_pyecod')

    if not pdb_id or not chain_id:
        raise ValueError(f"Missing pdb_id or chain_id in {xml_path}")

    # Parse metadata
    metadata = _parse_metadata(root)

    # Parse domains
    domains = _parse_domains(root)

    return PartitionResult(
        pdb_id=pdb_id,
        chain_id=chain_id,
        is_classified=is_classified,
        reference=reference,
        metadata=metadata,
        domains=domains
    )


def _parse_metadata(root: ET.Element) -> PartitionMetadata:
    """Extract metadata from partition XML."""
    metadata = PartitionMetadata()

    metadata_elem = root.find('metadata')
    if metadata_elem is None:
        return metadata

    # Version info
    version_elem = metadata_elem.find('version')
    if version_elem is not None:
        metadata.algorithm_version = version_elem.get('algorithm', '')
        metadata.git_commit = version_elem.get('git_commit', '')
        metadata.timestamp = version_elem.get('timestamp', '')

    # Source info
    source_elem = metadata_elem.find('source')
    if source_elem is not None:
        metadata.batch_id = source_elem.get('batch_id', '')
        metadata.domain_summary_path = source_elem.get('domain_summary_path', '')

    # Statistics
    stats_elem = metadata_elem.find('statistics')
    if stats_elem is not None:
        metadata.sequence_length = int(stats_elem.get('sequence_length', 0))
        metadata.domain_count = int(stats_elem.get('domain_count', 0))
        metadata.total_coverage = float(stats_elem.get('total_coverage', 0.0))
        metadata.residues_assigned = int(stats_elem.get('residues_assigned', 0))

    return metadata


def _parse_domains(root: ET.Element) -> List[PartitionDomain]:
    """Extract domains from partition XML."""
    domains = []

    domains_elem = root.find('domains')
    if domains_elem is None:
        return domains

    for domain_elem in domains_elem.findall('domain'):
        domain = PartitionDomain(
            internal_id=domain_elem.get('id', ''),
            range_definition=domain_elem.get('range', ''),
            family=domain_elem.get('family'),
            t_group=domain_elem.get('t_group'),
            h_group=domain_elem.get('h_group'),
            x_group=domain_elem.get('x_group'),
            confidence=float(domain_elem.get('confidence', 0.0)),
            reference_ecod_domain_id=domain_elem.get('reference_ecod_domain_id'),
            is_discontinuous=domain_elem.get('is_discontinuous', 'false').lower() == 'true',
            evidence_count=int(domain_elem.get('evidence_count', 0)),
            source=domain_elem.get('source'),
        )

        # Parse primary evidence if present
        evidence_elem = domain_elem.find('primary_evidence')
        if evidence_elem is not None:
            evalue_str = evidence_elem.get('evalue')
            evalue = None
            if evalue_str:
                try:
                    evalue = float(evalue_str)
                except ValueError:
                    pass

            domain.primary_evidence = DomainEvidence(
                source_type=evidence_elem.get('source_type', ''),
                source_id=evidence_elem.get('source_id', ''),
                domain_id=evidence_elem.get('domain_id', ''),
                evalue=evalue,
                confidence=float(evidence_elem.get('confidence', 0.0)),
            )

        domains.append(domain)

    return domains


def parse_partition_directory(
    partition_dir: Path,
    min_coverage: float = 0.0,
    limit: Optional[int] = None
) -> List[PartitionResult]:
    """
    Parse all partition XMLs in a directory.

    Args:
        partition_dir: Directory containing partition XMLs
        min_coverage: Minimum coverage threshold (default: include all)
        limit: Maximum number of partitions to parse (default: no limit)

    Returns:
        List of PartitionResult objects
    """
    results = []
    xml_files = sorted(partition_dir.glob('*.partition.xml'))

    for i, xml_path in enumerate(xml_files):
        if limit is not None and i >= limit:
            break

        try:
            result = parse_partition_xml(xml_path)

            # Apply coverage filter
            if result.coverage >= min_coverage:
                results.append(result)

        except Exception as e:
            # Log error but continue processing
            print(f"Warning: Failed to parse {xml_path}: {e}")

    return results


def generate_ecod_domain_id(pdb_id: str, chain_id: str, domain_num: int) -> str:
    """
    Generate ECOD-style domain ID.

    Format: e{pdb_id}{chain_id}{domain_num}
    Example: e9qf6BA1

    Args:
        pdb_id: PDB ID (e.g., "9qf6")
        chain_id: Chain ID (e.g., "BA")
        domain_num: Domain number (1-indexed)

    Returns:
        ECOD domain ID string
    """
    return f"e{pdb_id}{chain_id}{domain_num}"


def partition_to_domain_data(
    partition: PartitionResult,
    domain: PartitionDomain,
    domain_num: int
) -> Dict[str, Any]:
    """
    Convert partition domain to data dict for auto-accession.

    Args:
        partition: The partition result containing this domain
        domain: The domain to convert
        domain_num: The domain number (1-indexed)

    Returns:
        Dict with fields needed for auto-accession
    """
    return {
        'pdb_id': partition.pdb_id,
        'chain_id': partition.chain_id,
        'domain_id': generate_ecod_domain_id(
            partition.pdb_id, partition.chain_id, domain_num
        ),
        'domain_num': domain_num,
        'range_definition': domain.get_chain_prefixed_range(partition.chain_id),
        'raw_range': domain.range_definition,
        'family': domain.family,
        't_group': domain.t_group,
        'h_group': domain.h_group,
        'x_group': domain.x_group,
        'confidence': domain.confidence,
        'reference_ecod_domain_id': domain.reference_ecod_domain_id,
        'is_discontinuous': domain.is_discontinuous,
        'source': domain.source,
        'partition_coverage': partition.coverage,
        'sequence_length': partition.metadata.sequence_length,
        'algorithm_version': partition.metadata.algorithm_version,
        'batch_id': partition.metadata.batch_id,
    }


if __name__ == '__main__':
    # Quick test
    import sys

    if len(sys.argv) < 2:
        print("Usage: python partition_parser.py <partition.xml>")
        sys.exit(1)

    result = parse_partition_xml(Path(sys.argv[1]))
    print(f"PDB: {result.pdb_id}, Chain: {result.chain_id}")
    print(f"Coverage: {result.coverage:.1%}")
    print(f"Domains: {len(result.domains)}")

    for i, domain in enumerate(result.domains, 1):
        data = partition_to_domain_data(result, domain, i)
        print(f"\n  Domain {i}:")
        print(f"    ID: {data['domain_id']}")
        print(f"    Range: {data['range_definition']}")
        print(f"    Family: {data['family']}")
        print(f"    T-group: {data['t_group']}")
        print(f"    Confidence: {data['confidence']:.4f}")
