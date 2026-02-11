#!/usr/bin/env python3
"""
Load partition results to ecod_curation schema.

This script demonstrates loading partition results to the ecod_curation staging area.
Currently loads basic partition data; full evidence integration coming in Phase 2.

Usage:
    # Load a single partition result
    python scripts/load_to_curation.py --pdb 8abc --chain A --partition-xml path/to/8abc_A.partition.xml

    # Load all partitions from a batch
    python scripts/load_to_curation.py --batch-path /data/ecod/test_batches/ecod_weekly_20250905

    # Test mode (prints what would be loaded without database write)
    python scripts/load_to_curation.py --batch-path /data/ecod/test_batches/ecod_weekly_20250905 --dry-run
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import date
from typing import Dict, List, Any, Optional
import argparse

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.database.curation_loader import load_partition_to_curation, get_db_connection
from pyecod_prod.utils.pdb_ids import parse_pdb_chain_id


def lookup_ecod_domain_info(ecod_domain_id: str, connection_params: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Look up ECOD UID and F-group for a given ECOD domain ID.

    Args:
        ecod_domain_id: ECOD domain identifier (e.g., "e6wjcC1")
        connection_params: Optional database connection parameters

    Returns:
        Dict with 'ecod_uid' and 'f_id' (None if not found)
    """
    if not ecod_domain_id:
        return {'ecod_uid': None, 'f_id': None}

    conn = get_db_connection(connection_params)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT
                d.ecod_uid,
                f.f_group_id
            FROM ecod_commons.domains d
            LEFT JOIN ecod_commons.f_group_assignments f ON d.id = f.domain_id
            WHERE d.domain_id = %s
            LIMIT 1
        """, (ecod_domain_id,))

        result = cursor.fetchone()
        if result:
            return {'ecod_uid': result[0], 'f_id': result[1]}
        else:
            return {'ecod_uid': None, 'f_id': None}

    finally:
        cursor.close()
        conn.close()


def parse_fasta(fasta_path: str) -> str:
    """
    Parse FASTA file and extract sequence.

    Args:
        fasta_path: Path to FASTA file

    Returns:
        Protein sequence string
    """
    with open(fasta_path) as f:
        lines = f.readlines()

    # Skip header line, concatenate sequence lines
    sequence = ''.join(line.strip() for line in lines if not line.startswith('>'))
    return sequence


def parse_partition_xml(partition_xml_path: str, fasta_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Parse partition XML and extract data for ecod_curation.

    This handles the actual pyecod_mini 2.0 partition format which includes
    t/h/x groups and evidence details.

    Args:
        partition_xml_path: Path to partition.xml file
        fasta_path: Optional path to FASTA file (for sequence)

    Returns:
        Dict with partition_result structure for load_partition_to_curation
    """
    tree = ET.parse(partition_xml_path)
    root = tree.getroot()

    # Extract protein metadata from root attributes
    pdb_id = root.get('pdb_id')
    chain_id = root.get('chain_id')
    is_classified = root.get('is_classified') == 'true'

    # Get statistics
    stats_elem = root.find('.//statistics')
    if stats_elem is not None:
        sequence_length = int(stats_elem.get('sequence_length', 0))
        coverage = float(stats_elem.get('total_coverage', 0.0))
    else:
        sequence_length = 0
        coverage = 0.0

    # Load sequence from FASTA if available
    sequence = None
    if fasta_path and Path(fasta_path).exists():
        sequence = parse_fasta(fasta_path)
    elif fasta_path is None:
        # Try to find FASTA in same directory structure
        partition_path = Path(partition_xml_path)
        batch_dir = partition_path.parent.parent
        fasta_dir = batch_dir / 'fastas'
        fasta_file = fasta_dir / f'{pdb_id}_{chain_id}.fa'
        if fasta_file.exists():
            sequence = parse_fasta(str(fasta_file))

    if sequence is None:
        # Fallback: create placeholder sequence
        sequence = 'X' * sequence_length

    # Extract domains
    domains = []
    domains_elem = root.find('domains')

    if domains_elem is not None and is_classified:
        for domain_elem in domains_elem.findall('domain'):
            domain_id = domain_elem.get('id')
            range_string = domain_elem.get('range')
            family = domain_elem.get('family')
            source = domain_elem.get('source')
            confidence = domain_elem.get('confidence')

            # Get t/h/x groups (these are in the actual XML!)
            t_group = domain_elem.get('t_group')
            h_group = domain_elem.get('h_group')
            x_group = domain_elem.get('x_group')

            # Get reference ecod domain ID (e.g., "e6wjcC1") and look up UID
            reference_ecod_domain_id = domain_elem.get('reference_ecod_domain_id')
            ref_domain_info = lookup_ecod_domain_info(reference_ecod_domain_id)
            best_match_ecod_uid = ref_domain_info['ecod_uid']

            # Parse range to get start/end
            # Handle discontinuous ranges by using full range
            range_parts = range_string.split(',')
            first_segment = range_parts[0].split('-')
            last_segment = range_parts[-1].split('-')
            start = int(first_segment[0])
            end = int(last_segment[-1])

            # Parse evidence
            evidence_list = []
            primary_evidence = domain_elem.find('primary_evidence')
            if primary_evidence is not None:
                # Parse evalue safely - convert very small values properly
                evalue_str = primary_evidence.get('evalue')
                try:
                    evalue = float(evalue_str) if evalue_str else None
                    # PostgreSQL real type has limited range - clamp very small values
                    if evalue is not None and evalue < 1e-37:
                        evalue = 1e-37  # Minimum value for PostgreSQL real type
                except (ValueError, OverflowError):
                    evalue = None

                # Get the reference ECOD domain ID from evidence (e.g., "e6wjcC1")
                # and look up its UID and F-group from ecod_commons
                hit_domain_id = primary_evidence.get('domain_id')
                hit_domain_info = lookup_ecod_domain_info(hit_domain_id)

                # Parse source_id (handles both legacy "1abc_A" and extended "pdb_00001abc_A" formats)
                source_id = primary_evidence.get('source_id', '')
                hit_pdb_id, hit_chain_id = parse_pdb_chain_id(source_id) if source_id else (None, None)

                evidence = {
                    'type': 'blast_domain' if primary_evidence.get('source_type') == 'domain_blast' else 'blast_chain',
                    'hit_ecod_domain_id': hit_domain_id,  # e.g., "e6wjcC1"
                    'hit_ecod_uid': hit_domain_info['ecod_uid'],  # Looked up from ecod_commons
                    'hit_pdb_id': hit_pdb_id,
                    'hit_chain_id': hit_chain_id,
                    'evalue': evalue,
                    'score': None,
                    'identity': None,
                    'similarity': None,
                    'query_coverage': float(primary_evidence.get('reference_coverage', 0)) if primary_evidence.get('reference_coverage') else None,
                    'hit_coverage': None,
                    'query_range': primary_evidence.get('evidence_range'),
                    'hit_range': primary_evidence.get('hit_range'),
                    'ref_t_group': t_group,  # Use domain's T/H/X classification
                    'ref_h_group': h_group,
                    'ref_x_group': x_group,
                    'ref_f_group': hit_domain_info['f_id'],  # Looked up from ecod_commons (may be None)
                    'source_file': None
                }
                evidence_list.append(evidence)

            # F-groups are NOT assigned during partitioning
            # They are assigned later via hmmscan against Pfam (bulk process)
            # The 'family' field in partition XML is actually the T-group, not F-group
            f_group = None  # Will be assigned later in staging/prod

            # Determine classification level based on what we have from BLAST/HHsearch
            if t_group:
                classification_level = 't_group_only'  # Only T/H/X from evidence
            else:
                classification_level = 'unclassified'

            # Map pyecod_mini source types to schema-allowed assignment methods
            # Schema allows: blast, hhsearch, manual, inheritance, hhblits
            source_mapping = {
                'domain_blast': 'blast',
                'chain_blast': 'blast',
                'chain_blast_decomposed': 'blast',
                'hhsearch': 'hhsearch',
                'inheritance': 'inheritance',
                'hhblits': 'hhblits',
            }
            assignment_method = source_mapping.get(source, 'blast')  # Default to blast

            domain = {
                'start': start,
                'end': end,
                'range_string': range_string,
                't_group': t_group,
                'h_group': h_group,
                'x_group': x_group,
                'f_group': f_group,
                'best_match_ecod_uid': best_match_ecod_uid,  # Looked up from ecod_commons
                'assignment_method': assignment_method,  # Mapped to schema values
                'classification_level': classification_level,
                'confidence': float(confidence) if confidence else None,
                'evidence': evidence_list
            }

            domains.append(domain)

    return {
        'pdb_id': pdb_id,
        'chain_id': chain_id,
        'sequence': sequence,
        'coverage': coverage,
        'domains': domains
    }


def load_batch_to_curation(batch_path: str, dry_run: bool = False) -> Dict[str, int]:
    """
    Load all partition results from a batch to ecod_curation.

    Args:
        batch_path: Path to batch directory
        dry_run: If True, print what would be loaded without database writes

    Returns:
        Dict with 'loaded' and 'failed' counts
    """
    batch_path = Path(batch_path)
    partitions_dir = batch_path / "partitions"

    if not partitions_dir.exists():
        raise FileNotFoundError(f"Partitions directory not found: {partitions_dir}")

    # Parse batch name to get release date
    batch_name = batch_path.name
    if batch_name.startswith('ecod_weekly_'):
        date_str = batch_name.split('_')[-1]  # '20250905'
        release_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
    else:
        # Default to today if batch name doesn't match expected format
        release_date = date.today()

    loaded = 0
    failed = 0

    print(f"\n{'=' * 70}")
    print(f"Loading batch: {batch_name}")
    print(f"Release date: {release_date}")
    print(f"Partitions dir: {partitions_dir}")
    print(f"Dry run: {dry_run}")
    print(f"{'=' * 70}\n")

    # Find all partition XML files
    partition_files = list(partitions_dir.glob("*.partition.xml"))

    if not partition_files:
        print(f"⚠️  No partition files found in {partitions_dir}")
        return {'loaded': 0, 'failed': 0}

    print(f"Found {len(partition_files)} partition files\n")

    for partition_file in sorted(partition_files):
        try:
            # Parse partition XML
            partition_data = parse_partition_xml(str(partition_file))

            pdb_id = partition_data['pdb_id']
            chain_id = partition_data['chain_id']

            if dry_run:
                print(f"Would load: {pdb_id}_{chain_id}")
                print(f"  Coverage: {partition_data['coverage']:.2f}")
                print(f"  Domains: {len(partition_data['domains'])}")
                loaded += 1
                continue

            # Load to ecod_curation
            protein_id = load_partition_to_curation(
                pdb_id=pdb_id,
                chain_id=chain_id,
                release_date=release_date,
                sequence=partition_data['sequence'],
                partition_result=partition_data,
                processing_version=f'pyecod_prod_batch_{batch_name}'
            )

            print(f"✓ Loaded {pdb_id}_{chain_id} (protein_id={protein_id})")
            print(f"  Coverage: {partition_data['coverage']:.2f}, Domains: {len(partition_data['domains'])}")
            loaded += 1

        except Exception as e:
            print(f"✗ Failed to load {partition_file.name}: {e}")
            failed += 1

    print(f"\n{'=' * 70}")
    print(f"Summary: {loaded} loaded, {failed} failed")
    print(f"{'=' * 70}\n")

    return {'loaded': loaded, 'failed': failed}


def main():
    parser = argparse.ArgumentParser(
        description="Load partition results to ecod_curation schema",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--batch-path', help='Path to batch directory')
    group.add_argument('--partition-xml', help='Path to single partition XML file')

    parser.add_argument('--pdb', help='PDB ID (required with --partition-xml)')
    parser.add_argument('--chain', help='Chain ID (required with --partition-xml)')
    parser.add_argument('--release-date', help='Release date YYYY-MM-DD (optional, defaults to today)')
    parser.add_argument('--dry-run', action='store_true', help='Print what would be loaded without database writes')

    args = parser.parse_args()

    if args.batch_path:
        # Load entire batch
        result = load_batch_to_curation(args.batch_path, dry_run=args.dry_run)
        return 0 if result['failed'] == 0 else 1

    elif args.partition_xml:
        # Load single partition
        if not args.pdb or not args.chain:
            parser.error("--pdb and --chain are required with --partition-xml")

        partition_data = parse_partition_xml(args.partition_xml)

        if args.release_date:
            release_date = date.fromisoformat(args.release_date)
        else:
            release_date = date.today()

        if args.dry_run:
            print(f"Would load: {args.pdb}_{args.chain}")
            print(f"  Coverage: {partition_data['coverage']:.2f}")
            print(f"  Domains: {len(partition_data['domains'])}")
            return 0

        try:
            protein_id = load_partition_to_curation(
                pdb_id=args.pdb,
                chain_id=args.chain,
                release_date=release_date,
                sequence=partition_data['sequence'],
                partition_result=partition_data,
                processing_version='pyecod_prod_manual'
            )

            print(f"✓ Loaded {args.pdb}_{args.chain} (protein_id={protein_id})")
            return 0

        except Exception as e:
            print(f"✗ Failed to load: {e}")
            return 1


if __name__ == '__main__':
    sys.exit(main())
