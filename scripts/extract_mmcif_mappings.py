#!/usr/bin/env python3
"""
Extract residue numbering mappings and UniProt xrefs from mmCIF files.

Parses local PDB mirror mmCIF files to extract:
1. SEQID → PDB ATOM numbering mapping (from _pdbx_poly_seq_scheme)
2. UniProt crossreferences (from _struct_ref and _struct_ref_seq)

Loads to ecod_curation.residue_mapping table.

Usage:
    # Extract for all proteins missing mappings
    python scripts/extract_mmcif_mappings.py --update-missing

    # Extract for specific batch
    python scripts/extract_mmcif_mappings.py --batch ecod_weekly_20250905

    # Extract for specific proteins
    python scripts/extract_mmcif_mappings.py --source-ids 8yl2_A 8yl2_B

    # Dry run
    python scripts/extract_mmcif_mappings.py --update-missing --dry-run
"""

import sys
import argparse
import gzip
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.database.curation_loader import get_db_connection
from pyecod_prod.utils.pdb_ids import get_directory_hash


# Local PDB mirror paths
PDB_MIRROR_BASE = Path("/usr2/pdb/data/structures/divided/mmCIF")


def get_mmcif_path(pdb_id: str) -> Optional[Path]:
    """
    Get path to mmCIF file in local PDB mirror.

    Supports both legacy 4-character and extended 12-character PDB IDs.
    """
    pdb_id_lower = pdb_id.lower()
    dir_hash = get_directory_hash(pdb_id_lower)
    mmcif_file = PDB_MIRROR_BASE / dir_hash / f"{pdb_id_lower}.cif.gz"

    if mmcif_file.exists():
        return mmcif_file
    return None


def parse_mmcif_loop_table(lines: List[str], start_idx: int) -> Tuple[List[str], List[List[str]], int]:
    """
    Parse a loop_ table from mmCIF.

    Returns:
        (column_names, data_rows, end_index)
    """
    columns = []
    data_rows = []

    i = start_idx + 1  # Skip 'loop_' line

    # Read column names (start with _)
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith('#'):
            i += 1
            continue
        if not line.startswith('_'):
            break
        columns.append(line.split('.')[1] if '.' in line else line)
        i += 1

    # Read data rows
    num_cols = len(columns)
    current_row = []
    in_multiline = False
    multiline_value = []

    while i < len(lines):
        line = lines[i].strip()

        # End of table
        if not line or line.startswith('#') or line.startswith('loop_') or line.startswith('_'):
            if current_row:
                data_rows.append(current_row)
            break

        # Handle multi-line values (semicolon-delimited)
        if line.startswith(';'):
            if in_multiline:
                # End of multiline value
                current_row.append('\n'.join(multiline_value))
                multiline_value = []
                in_multiline = False
            else:
                # Start of multiline value
                in_multiline = True
                multiline_value = []
            i += 1
            continue

        if in_multiline:
            multiline_value.append(line)
            i += 1
            continue

        # Regular data line
        tokens = line.split()
        current_row.extend(tokens)

        # Complete row?
        if len(current_row) >= num_cols:
            data_rows.append(current_row[:num_cols])
            current_row = current_row[num_cols:]

        i += 1

    return columns, data_rows, i


def parse_mmcif_mappings(mmcif_path: Path, chain_id: str, verbose: bool = False) -> Optional[Dict]:
    """
    Parse residue mappings and UniProt xrefs from mmCIF file for a specific chain.

    Returns:
        {
            'uniprot_accession': 'A0A5B9DBS5',
            'uniprot_id': 'A0A5B9DBS5_9ARCH',
            'uniprot_range': '2-341',  # Range in UniProt sequence
            'residues': [
                {
                    'seqid': 1,
                    'pdb_num': None,  # Missing in structure
                    'pdb_ins_code': None,
                    'residue': 'GLY',
                    'observed': False
                },
                {
                    'seqid': 42,
                    'pdb_num': 41,
                    'pdb_ins_code': None,
                    'residue': 'SER',
                    'observed': True
                },
                ...
            ]
        }
    """
    try:
        # Open mmCIF file
        if mmcif_path.suffix == '.gz':
            with gzip.open(mmcif_path, 'rt') as f:
                lines = f.readlines()
        else:
            with open(mmcif_path, 'r') as f:
                lines = f.readlines()

        # Parse _struct_ref for UniProt accession/ID
        uniprot_accession = None
        uniprot_id = None
        entity_id = None

        for i, line in enumerate(lines):
            if line.strip().startswith('_struct_ref.pdbx_db_accession'):
                parts = line.split()
                if len(parts) == 2 and parts[1] != '?':
                    uniprot_accession = parts[1]
            elif line.strip().startswith('_struct_ref.db_code'):
                parts = line.split()
                if len(parts) == 2 and parts[1] != '?':
                    uniprot_id = parts[1]
            elif line.strip().startswith('_struct_ref.entity_id'):
                parts = line.split()
                if len(parts) == 2:
                    entity_id = parts[1]

        # Parse _struct_ref_seq for UniProt range (per chain)
        uniprot_range = None

        for i, line in enumerate(lines):
            if line.strip().startswith('loop_') and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line.startswith('_struct_ref_seq.'):
                    # Parse struct_ref_seq table
                    columns, data_rows, _ = parse_mmcif_loop_table(lines, i)

                    # Find row for this chain
                    try:
                        strand_idx = columns.index('pdbx_strand_id')
                        db_beg_idx = columns.index('db_align_beg')
                        db_end_idx = columns.index('db_align_end')

                        for row in data_rows:
                            if row[strand_idx] == chain_id:
                                db_beg = row[db_beg_idx]
                                db_end = row[db_end_idx]
                                if db_beg != '?' and db_end != '?':
                                    uniprot_range = f"{db_beg}-{db_end}"
                                break
                    except (ValueError, IndexError):
                        pass
                    break

        # Parse _pdbx_poly_seq_scheme for residue mappings
        residues = []

        for i, line in enumerate(lines):
            if line.strip().startswith('loop_') and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line.startswith('_pdbx_poly_seq_scheme.'):
                    # Parse poly_seq_scheme table
                    columns, data_rows, _ = parse_mmcif_loop_table(lines, i)

                    try:
                        seq_id_idx = columns.index('seq_id')
                        mon_id_idx = columns.index('mon_id')
                        auth_seq_idx = columns.index('auth_seq_num')
                        strand_id_idx = columns.index('pdb_strand_id')
                        ins_code_idx = columns.index('pdb_ins_code')

                        for row in data_rows:
                            # Filter to target chain
                            if row[strand_id_idx] != chain_id:
                                continue

                            seqid = int(row[seq_id_idx])
                            residue = row[mon_id_idx]
                            auth_seq = row[auth_seq_idx]
                            ins_code = row[ins_code_idx]

                            # auth_seq_num = '?' means not observed in structure
                            observed = (auth_seq != '?')
                            pdb_num = int(auth_seq) if observed else None
                            pdb_ins = ins_code if ins_code != '.' and ins_code != '?' else None

                            residues.append({
                                'seqid': seqid,
                                'pdb_num': pdb_num,
                                'pdb_ins_code': pdb_ins,
                                'residue': residue,
                                'observed': observed
                            })

                    except (ValueError, IndexError) as e:
                        print(f"  ⚠️  Error parsing poly_seq_scheme: {e}")
                        return None
                    break

        if not residues:
            print(f"  ⚠️  No residue mappings found for chain {chain_id}")
            return None

        if verbose:
            pdb_id = mmcif_path.stem.replace('.cif', '').upper()
            print(f"    ✓ UniProt: {uniprot_accession or 'N/A'} ({uniprot_id or 'N/A'})")
            print(f"    ✓ UniProt range: {uniprot_range or 'N/A'}")
            print(f"    ✓ Residues: {len(residues)} total, {sum(1 for r in residues if r['observed'])} observed")

        return {
            'uniprot_accession': uniprot_accession,
            'uniprot_id': uniprot_id,
            'uniprot_range': uniprot_range,
            'residues': residues
        }

    except Exception as e:
        print(f"  ✗ Error parsing mmCIF file {mmcif_path}: {e}")
        import traceback
        traceback.print_exc()
        return None


def update_protein_mappings(
    protein_id: int,
    pdb_id: str,
    chain_id: str,
    mappings: Dict,
    conn,
    dry_run: bool = False
) -> bool:
    """
    Update ecod_curation.protein with UniProt xrefs and load residue mappings.
    """
    if dry_run:
        print(f"  [DRY RUN] Would update protein_id={protein_id}")
        return True

    cursor = conn.cursor()

    try:
        # Update protein table with UniProt info
        cursor.execute("""
            UPDATE ecod_curation.protein
            SET
                uniprot_accession = %s,
                uniprot_id = %s,
                uniprot_range = %s
            WHERE id = %s
        """, (
            mappings['uniprot_accession'],
            mappings['uniprot_id'],
            mappings['uniprot_range'],
            protein_id
        ))

        # Delete existing mappings (if re-processing)
        cursor.execute("""
            DELETE FROM ecod_curation.residue_mapping
            WHERE protein_id = %s
        """, (protein_id,))

        # Insert residue mappings
        for res in mappings['residues']:
            cursor.execute("""
                INSERT INTO ecod_curation.residue_mapping
                (protein_id, seqid_position, pdb_position, pdb_insertion_code,
                 residue_name, is_observed)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                protein_id,
                res['seqid'],
                res['pdb_num'],
                res['pdb_ins_code'],
                res['residue'],
                res['observed']
            ))

        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        print(f"  ✗ Database error updating protein {protein_id}: {e}")
        return False
    finally:
        cursor.close()


def get_proteins_missing_mappings(conn, batch_name: Optional[str] = None) -> List[Tuple]:
    """Get list of proteins missing residue mappings."""
    cursor = conn.cursor()

    if batch_name:
        query = """
            SELECT p.id, p.source_id, p.pdb_id, p.chain_id
            FROM ecod_curation.protein p
            LEFT JOIN ecod_curation.residue_mapping rm ON p.id = rm.protein_id
            WHERE p.processing_version LIKE %s
            GROUP BY p.id, p.source_id, p.pdb_id, p.chain_id
            HAVING COUNT(rm.seqid_position) = 0
            ORDER BY p.pdb_id, p.chain_id
        """
        cursor.execute(query, (f'%{batch_name}%',))
    else:
        query = """
            SELECT id, source_id, pdb_id, chain_id
            FROM ecod_curation.proteins_missing_sifts
            ORDER BY pdb_id, chain_id
        """
        cursor.execute(query)

    results = cursor.fetchall()
    cursor.close()
    return results


def get_proteins_by_source_ids(conn, source_ids: List[str]) -> List[Tuple]:
    """Get proteins for specific source IDs (e.g., '8yl2_A')."""
    cursor = conn.cursor()

    query = """
        SELECT id, source_id, pdb_id, chain_id
        FROM ecod_curation.protein
        WHERE source_id = ANY(%s)
        ORDER BY source_id
    """
    cursor.execute(query, (source_ids,))

    results = cursor.fetchall()
    cursor.close()
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Extract residue mappings and UniProt xrefs from mmCIF files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Mutually exclusive selection modes
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--update-missing',
        action='store_true',
        help='Update all proteins missing mappings'
    )
    group.add_argument(
        '--batch',
        help='Update proteins from specific batch'
    )
    group.add_argument(
        '--source-ids',
        nargs='+',
        help='Update specific source IDs (e.g., 8yl2_A 8yl2_B)'
    )

    # Options
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print what would be done without database writes'
    )
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Print detailed progress'
    )

    args = parser.parse_args()

    # Check PDB mirror exists
    if not PDB_MIRROR_BASE.exists():
        print(f"ERROR: PDB mirror not found at {PDB_MIRROR_BASE}")
        return 1

    # Connect to database
    print("Connecting to database...")
    conn = get_db_connection()

    # Get list of proteins to process
    if args.update_missing:
        print("Finding proteins missing mappings...")
        proteins = get_proteins_missing_mappings(conn)
        print(f"Found {len(proteins)} proteins missing mappings")

    elif args.batch:
        print(f"Finding proteins from batch: {args.batch}")
        proteins = get_proteins_missing_mappings(conn, batch_name=args.batch)
        print(f"Found {len(proteins)} proteins in batch missing mappings")

    elif args.source_ids:
        print(f"Finding proteins for source IDs: {', '.join(args.source_ids)}")
        proteins = get_proteins_by_source_ids(conn, args.source_ids)
        print(f"Found {len(proteins)} proteins matching source IDs")

    if len(proteins) == 0:
        print("No proteins to process. Exiting.")
        conn.close()
        return 0

    # Group by PDB ID to minimize file re-reads
    pdb_to_chains = defaultdict(list)
    for protein_id, source_id, pdb_id, chain_id in proteins:
        pdb_to_chains[pdb_id].append((protein_id, source_id, chain_id))

    print(f"\nUnique PDB entries to process: {len(pdb_to_chains)}")
    print(f"Total proteins to process: {len(proteins)}")

    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - No database changes will be made\n")

    # Process
    print(f"\n{'='*70}")
    print("Extracting residue mappings from mmCIF files...")
    print(f"{'='*70}\n")

    success_count = 0
    failed_count = 0

    for i, (pdb_id, chains) in enumerate(pdb_to_chains.items(), 1):
        print(f"[{i}/{len(pdb_to_chains)}] {pdb_id} ({len(chains)} chains)")

        # Get mmCIF file path
        mmcif_path = get_mmcif_path(pdb_id)
        if mmcif_path is None:
            print(f"  ⚠️  mmCIF file not found in local mirror")
            failed_count += len(chains)
            continue

        # Process each chain
        for protein_id, source_id, chain_id in chains:
            if args.verbose:
                print(f"  Processing {source_id} (chain {chain_id})...")

            # Parse mappings for this chain
            mappings = parse_mmcif_mappings(mmcif_path, chain_id, verbose=args.verbose)

            if mappings is None:
                failed_count += 1
                continue

            # Update database
            success = update_protein_mappings(
                protein_id,
                pdb_id,
                chain_id,
                mappings,
                conn,
                dry_run=args.dry_run
            )

            if success:
                success_count += 1
            else:
                failed_count += 1

    # Summary
    print(f"\n{'='*70}")
    print("Summary")
    print(f"{'='*70}")
    print(f"  PDB entries processed: {len(pdb_to_chains)}")
    print(f"  Proteins updated: {success_count}")
    print(f"  Failed: {failed_count}")
    if args.dry_run:
        print(f"\n  ⚠️  DRY RUN - No actual database changes were made")
    print(f"{'='*70}\n")

    conn.close()

    return 0 if failed_count == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
