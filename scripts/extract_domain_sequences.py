#!/usr/bin/env python3
"""
Extract domain sequences from chain sequences using range definitions.

This script:
1. Queries domains from ecod_commons.domains for a specific domain_version
2. Gets chain sequences from ecod_commons.proteins
3. Extracts subsequences using range definitions
4. Inserts into ecod_commons.domain_sequences
5. Optionally writes to a combined FASTA file

Usage:
    # Extract and insert domain sequences for new batch
    python scripts/extract_domain_sequences.py \
        --domain-version "pyecod_prod_ecod_q4_2025_q1_2026" \
        --output-fasta /data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/domains/all_domains.fasta

    # Dry run (preview without inserting)
    python scripts/extract_domain_sequences.py \
        --domain-version "pyecod_prod_ecod_q4_2025_q1_2026" \
        --dry-run

    # With limit for testing
    python scripts/extract_domain_sequences.py \
        --domain-version "pyecod_prod_ecod_q4_2025_q1_2026" \
        --limit 100 \
        --dry-run
"""

import sys
import os
import argparse
import logging
import hashlib
import re
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass

import psycopg2

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database connection parameters
DEFAULT_CONNECTION_PARAMS = {
    'host': os.environ.get('ECOD_DB_HOST', 'dione'),
    'port': int(os.environ.get('ECOD_DB_PORT', '45000')),
    'user': os.environ.get('ECOD_DB_USER', 'ecod'),
    'password': os.environ.get('ECOD_DB_PASSWORD', ''),
    'dbname': os.environ.get('ECOD_DB_NAME', 'ecod_protein'),
}


@dataclass
class RangeSegment:
    """A single continuous segment of a domain range."""
    chain_id: Optional[str]
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def parse_range_segments(range_string: str) -> List[Tuple[int, int]]:
    """
    Parse a domain range string into list of (start, end) tuples.

    Supports:
    - "A:10-150" (chain-specified)
    - "A:10-150,A:200-250" (discontinuous, chain-specified)
    - "10-150" (raw)
    - "10-150,200-250" (discontinuous, raw)

    Returns:
        List of (start, end) tuples (1-indexed)
    """
    if not range_string or range_string.strip() == "":
        return []

    segments = []
    parts = range_string.split(",")

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Try chain-specified format: "A:10-150"
        chain_match = re.match(r'^([A-Za-z0-9]+):(-?\d+)-(-?\d+)$', part)
        if chain_match:
            start = int(chain_match.group(2))
            end = int(chain_match.group(3))
            segments.append((start, end))
            continue

        # Try raw format: "10-150"
        raw_match = re.match(r'^(-?\d+)-(-?\d+)$', part)
        if raw_match:
            start = int(raw_match.group(1))
            end = int(raw_match.group(2))
            segments.append((start, end))
            continue

        # Unrecognized format - log warning but continue
        logger.warning(f"Cannot parse range segment: '{part}'")

    return segments


def extract_domain_sequence(chain_sequence: str, range_definition: str) -> str:
    """
    Extract domain sequence from chain sequence using range definition.

    Args:
        chain_sequence: Full chain amino acid sequence
        range_definition: Range string (e.g., "A:10-150" or "10-50,100-150")

    Returns:
        Domain sequence (concatenated if discontinuous)
    """
    segments = parse_range_segments(range_definition)

    if not segments:
        logger.warning(f"No segments parsed from range: {range_definition}")
        return ""

    domain_seq = ""
    seq_len = len(chain_sequence)

    for start, end in segments:
        # Handle negative ranges (shouldn't happen but be defensive)
        if start < 1:
            start = 1
        if end > seq_len:
            end = seq_len

        # Python is 0-indexed, ranges are 1-indexed
        segment_seq = chain_sequence[start-1:end]
        domain_seq += segment_seq

    return domain_seq


def get_connection(connection_params: Dict = None):
    """Get database connection."""
    params = connection_params or DEFAULT_CONNECTION_PARAMS
    return psycopg2.connect(**params)


def get_domains_for_version(conn, domain_version: str, limit: int = None) -> List[Dict]:
    """
    Get domains for a specific domain_version.

    Returns list of dicts with:
    - domain_db_id: Database ID (PK)
    - domain_id: ECOD domain ID (e.g., "e1suaA1")
    - ecod_uid: Numeric UID
    - protein_id: FK to proteins table
    - range_definition: Domain range (e.g., "A:10-150")
    - pdb_id: PDB ID
    - chain_id: Chain ID
    """
    cursor = conn.cursor()

    # Use exact match if domain_version doesn't contain wildcards
    use_exact = '%' not in domain_version and '_' not in domain_version

    query = """
        SELECT d.id as domain_db_id, d.domain_id, d.ecod_uid,
               d.protein_id, d.range_definition,
               p.pdb_id, p.chain_id
        FROM ecod_commons.domains d
        JOIN ecod_commons.proteins p ON d.protein_id = p.id
        WHERE d.domain_version {} %s
        AND NOT EXISTS (
            SELECT 1 FROM ecod_commons.domain_sequences ds
            WHERE ds.domain_id = d.id
        )
        ORDER BY d.ecod_uid
    """.format('=' if use_exact else 'LIKE')

    if limit:
        query += f" LIMIT {limit}"

    param = domain_version if use_exact else f"{domain_version}%"
    cursor.execute(query, (param,))

    columns = ['domain_db_id', 'domain_id', 'ecod_uid', 'protein_id',
               'range_definition', 'pdb_id', 'chain_id']

    results = []
    for row in cursor:
        results.append(dict(zip(columns, row)))

    cursor.close()
    return results


def get_protein_sequences(conn, protein_ids: List[int]) -> Dict[int, str]:
    """
    Get protein sequences for a list of protein IDs from protein_sequences table.

    Returns dict mapping protein_id -> sequence
    """
    if not protein_ids:
        return {}

    cursor = conn.cursor()

    # Use ANY for efficient batch query against protein_sequences table
    cursor.execute("""
        SELECT protein_id, sequence
        FROM ecod_commons.protein_sequences
        WHERE protein_id = ANY(%s)
    """, (protein_ids,))

    sequences = {}
    for protein_id, sequence in cursor:
        sequences[protein_id] = sequence or ""

    cursor.close()
    return sequences


def load_fasta_sequences(fasta_path: str) -> Dict[str, str]:
    """
    Load sequences from a FASTA file.

    Returns dict mapping "pdb_id_chain_id" -> sequence
    """
    sequences = {}
    current_id = None
    current_seq = []

    with open(fasta_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if line.startswith('>'):
                # Save previous sequence
                if current_id and current_seq:
                    sequences[current_id] = ''.join(current_seq)

                # Parse header - expected format: >pdb_chain or >pdb|chain
                header = line[1:].split()[0]  # Get first part before whitespace
                # Handle both pdb_chain and pdb|chain formats
                if '|' in header:
                    parts = header.split('|')
                    current_id = f"{parts[0]}_{parts[1]}"
                else:
                    current_id = header  # Already in pdb_chain format

                current_seq = []
            else:
                current_seq.append(line)

    # Save last sequence
    if current_id and current_seq:
        sequences[current_id] = ''.join(current_seq)

    return sequences


def insert_domain_sequence(conn, domain_db_id: int, sequence: str,
                           dry_run: bool = False) -> bool:
    """
    Insert domain sequence into ecod_commons.domain_sequences.

    Returns True if successful, False otherwise.
    """
    if dry_run:
        return True

    cursor = conn.cursor()

    try:
        sequence_md5 = hashlib.md5(sequence.encode()).hexdigest()

        cursor.execute("""
            INSERT INTO ecod_commons.domain_sequences
                (domain_id, sequence, sequence_md5, extracted_from, created_date)
            VALUES (%s, %s, %s, 'chain_sequence', NOW())
            ON CONFLICT (domain_id) DO NOTHING
        """, (domain_db_id, sequence, sequence_md5))

        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to insert sequence for domain {domain_db_id}: {e}")
        return False

    finally:
        cursor.close()


def write_fasta(fasta_path: Path, domain_id: str, ecod_uid: int,
                domain_version: str, sequence: str):
    """Append a sequence to the FASTA file."""
    with open(fasta_path, 'a') as f:
        header = f">{domain_id}|{ecod_uid}|{domain_version}"
        f.write(f"{header}\n")

        # Write sequence in 80-character lines
        for i in range(0, len(sequence), 80):
            f.write(sequence[i:i+80] + '\n')


def main():
    parser = argparse.ArgumentParser(
        description="Extract domain sequences from chain sequences"
    )
    parser.add_argument(
        "--domain-version", required=True,
        help="Domain version to process (e.g., pyecod_prod_ecod_q4_2025_q1_2026)"
    )
    parser.add_argument(
        "--input-fasta", type=str,
        help="Input FASTA file with chain sequences (used when DB sequences not available)"
    )
    parser.add_argument(
        "--output-fasta", type=str,
        help="Output FASTA file path (optional)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview without inserting into database"
    )
    parser.add_argument(
        "--limit", type=int,
        help="Limit number of domains to process"
    )
    parser.add_argument(
        "--batch-size", type=int, default=1000,
        help="Batch size for protein sequence fetching"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Domain Sequence Extraction")
    logger.info("=" * 60)
    logger.info(f"Domain version: {args.domain_version}")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'REAL RUN'}")
    if args.input_fasta:
        logger.info(f"Input FASTA: {args.input_fasta}")
    if args.output_fasta:
        logger.info(f"Output FASTA: {args.output_fasta}")
    if args.limit:
        logger.info(f"Limit: {args.limit}")
    logger.info("=" * 60)

    # Load FASTA sequences if provided
    fasta_sequences = {}
    if args.input_fasta:
        logger.info(f"Loading sequences from {args.input_fasta}...")
        fasta_sequences = load_fasta_sequences(args.input_fasta)
        logger.info(f"Loaded {len(fasta_sequences)} chain sequences from FASTA")

    # Connect to database
    conn = get_connection()

    # Get domains needing sequence extraction
    logger.info("Querying domains...")
    domains = get_domains_for_version(conn, args.domain_version, args.limit)
    logger.info(f"Found {len(domains)} domains needing sequence extraction")

    if not domains:
        logger.info("No domains to process")
        conn.close()
        return 0

    # Initialize FASTA file if requested
    if args.output_fasta:
        fasta_path = Path(args.output_fasta)
        fasta_path.parent.mkdir(parents=True, exist_ok=True)
        # Clear existing file
        with open(fasta_path, 'w') as f:
            f.write(f"# Domain sequences for {args.domain_version}\n")
            f.write(f"# Generated: {datetime.now().isoformat()}\n")

    # Process in batches to avoid memory issues
    stats = {
        'processed': 0,
        'success': 0,
        'failed': 0,
        'empty_sequence': 0,
        'missing_chain_sequence': 0
    }

    start_time = datetime.now()

    # Collect unique protein IDs for batch fetching
    batch_start = 0
    while batch_start < len(domains):
        batch_end = min(batch_start + args.batch_size, len(domains))
        batch = domains[batch_start:batch_end]

        # Get protein sequences for this batch
        protein_ids = list(set(d['protein_id'] for d in batch))
        protein_sequences = get_protein_sequences(conn, protein_ids)

        for domain in batch:
            stats['processed'] += 1

            protein_id = domain['protein_id']
            chain_sequence = protein_sequences.get(protein_id, "")

            # Fall back to FASTA file if database sequence not available
            if not chain_sequence and fasta_sequences:
                # Try pdb_chain format
                fasta_key = f"{domain['pdb_id']}_{domain['chain_id']}"
                chain_sequence = fasta_sequences.get(fasta_key, "")

                # Also try lowercase pdb_id
                if not chain_sequence:
                    fasta_key_lower = f"{domain['pdb_id'].lower()}_{domain['chain_id']}"
                    chain_sequence = fasta_sequences.get(fasta_key_lower, "")

            if not chain_sequence:
                stats['missing_chain_sequence'] += 1
                if stats['missing_chain_sequence'] <= 10:  # Limit warning output
                    logger.warning(
                        f"Missing chain sequence for domain {domain['domain_id']} "
                        f"(pdb={domain['pdb_id']}, chain={domain['chain_id']})"
                    )
                continue

            # Extract domain sequence
            domain_sequence = extract_domain_sequence(
                chain_sequence, domain['range_definition']
            )

            if not domain_sequence:
                stats['empty_sequence'] += 1
                logger.warning(
                    f"Empty sequence for domain {domain['domain_id']} "
                    f"(range={domain['range_definition']})"
                )
                continue

            # Insert into database
            success = insert_domain_sequence(
                conn, domain['domain_db_id'], domain_sequence,
                dry_run=args.dry_run
            )

            if success:
                stats['success'] += 1

                # Write to FASTA if requested
                if args.output_fasta:
                    write_fasta(
                        fasta_path, domain['domain_id'], domain['ecod_uid'],
                        args.domain_version, domain_sequence
                    )
            else:
                stats['failed'] += 1

            # Progress logging
            if stats['processed'] % 1000 == 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                rate = stats['processed'] / elapsed if elapsed > 0 else 0
                logger.info(
                    f"Progress: {stats['processed']}/{len(domains)} "
                    f"({rate:.1f} domains/sec)"
                )

        batch_start = batch_end

    conn.close()

    # Summary
    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("")
    logger.info("=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)
    logger.info(f"Total domains: {len(domains)}")
    logger.info(f"Processed: {stats['processed']}")
    logger.info(f"Success: {stats['success']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info(f"Empty sequence: {stats['empty_sequence']}")
    logger.info(f"Missing chain sequence: {stats['missing_chain_sequence']}")
    logger.info(f"Time: {elapsed:.1f} seconds")
    if stats['processed'] > 0:
        logger.info(f"Rate: {stats['processed'] / elapsed:.1f} domains/sec")

    if args.output_fasta:
        logger.info(f"FASTA written to: {args.output_fasta}")

    if args.dry_run:
        logger.info("")
        logger.info("DRY RUN - no changes made to database")

    return 0 if stats['failed'] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
