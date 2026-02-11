#!/usr/bin/env python3
"""
Extract PDB metadata from local PDB mirror and update ecod_curation.protein.

This script parses mmCIF files from the local PDB mirror at /usr2/pdb/data/structures
to extract metadata:
- Structure title
- Deposition and release dates
- Experimental method (X-ray, Cryo-EM, NMR, Model)
- Resolution (Angstroms)
- Entity descriptions

Data source: Local PDB mirror mmCIF files

Usage:
    # Fetch metadata for all proteins missing it
    python scripts/fetch_pdb_metadata.py --update-missing

    # Fetch for specific batch
    python scripts/fetch_pdb_metadata.py --batch ecod_weekly_20250905

    # Fetch for specific PDB IDs
    python scripts/fetch_pdb_metadata.py --pdb-ids 8yl2 8s72 9ay5

    # Dry run (print what would be fetched without database writes)
    python scripts/fetch_pdb_metadata.py --update-missing --dry-run

    # Fetch and update priority scores
    python scripts/fetch_pdb_metadata.py --update-missing --calculate-priority
"""

import sys
import argparse
import gzip
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
    Directory structure uses appropriate hash based on ID format.

    Args:
        pdb_id: PDB identifier (legacy or extended format)

    Returns:
        Path to mmCIF file, or None if not found

    Examples:
        8yl2 → /usr2/pdb/.../yl/8yl2.cif.gz
        pdb_00008yl2 → /usr2/pdb/.../yl/pdb_00008yl2.cif.gz
    """
    pdb_id_lower = pdb_id.lower()
    dir_hash = get_directory_hash(pdb_id_lower)
    mmcif_file = PDB_MIRROR_BASE / dir_hash / f"{pdb_id_lower}.cif.gz"

    if mmcif_file.exists():
        return mmcif_file

    return None


def parse_mmcif_metadata(mmcif_path: Path, verbose: bool = False) -> Optional[Dict]:
    """
    Parse metadata from mmCIF file.

    Extracts:
    - _struct.title - structure title
    - _pdbx_database_status.recvd_initial_deposition_date - deposition date
    - _pdbx_database_status.status_code_sf (or similar) for release date
    - _exptl.method - experimental method
    - _refine.ls_d_res_high - resolution (X-ray/EM)
    - _em_3d_reconstruction.resolution - resolution (EM)
    - _pdbx_struct_assembly.oligomeric_count - assembly count

    Args:
        mmcif_path: Path to mmCIF file (possibly gzipped)
        verbose: Print detailed progress

    Returns:
        Dictionary with metadata fields, or None if parsing failed
    """
    metadata = {
        'title': None,
        'deposition_date': None,
        'release_date': None,
        'experimental_method': None,
        'resolution': None,
        'biological_assembly_count': 1
    }

    try:
        # Open file (handles .gz automatically)
        if mmcif_path.suffix == '.gz':
            f = gzip.open(mmcif_path, 'rt')
        else:
            f = open(mmcif_path, 'r')

        with f:
            lines = f.readlines()

        # Parse lines with look-ahead for multi-line values
        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Title (may be on next line)
            if line.startswith('_struct.title'):
                # Check if value is on same line
                parts = line.split(maxsplit=1)
                if len(parts) == 2 and parts[1] != '?':
                    title = parts[1].strip().strip("'\"")
                    metadata['title'] = title
                elif i + 1 < len(lines):
                    # Value is on next line
                    next_line = lines[i + 1].strip()
                    if next_line and not next_line.startswith('_'):
                        title = next_line.strip().strip("'\"")
                        metadata['title'] = title
                        i += 1  # Skip next line since we already processed it

            # Deposition date
            elif line.startswith('_pdbx_database_status.recvd_initial_deposition_date'):
                parts = line.split()
                if len(parts) == 2:
                    metadata['deposition_date'] = parts[1]

            # Experimental method
            elif line.startswith('_exptl.method') and not line.startswith('_exptl.method_details'):
                parts = line.split(maxsplit=1)
                if len(parts) == 2 and parts[1] != '?':
                    method = parts[1].strip().strip("'\"")
                    metadata['experimental_method'] = method

            # Resolution (X-ray refinement)
            elif line.startswith('_refine.ls_d_res_high'):
                parts = line.split()
                if len(parts) == 2 and parts[1] != '?':
                    try:
                        metadata['resolution'] = float(parts[1])
                    except ValueError:
                        pass

            # Resolution (EM)
            elif line.startswith('_em_3d_reconstruction.resolution'):
                if metadata['resolution'] is None:  # Prefer refine resolution if available
                    parts = line.split()
                    if len(parts) == 2 and parts[1] != '?':
                        try:
                            metadata['resolution'] = float(parts[1])
                        except ValueError:
                            pass

            i += 1

        # Use deposition date as release date if not found
        # (actual release date is harder to extract from mmCIF)
        if metadata['release_date'] is None:
            metadata['release_date'] = metadata['deposition_date']

        if verbose:
            pdb_id = mmcif_path.stem.replace('.cif', '').upper()
            print(f"    ✓ Title: {metadata['title'][:60] if metadata['title'] else 'N/A'}...")
            print(f"    ✓ Deposited: {metadata['deposition_date']}")
            print(f"    ✓ Method: {metadata['experimental_method']}")
            if metadata['resolution']:
                print(f"    ✓ Resolution: {metadata['resolution']} Å")
            else:
                print(f"    ✓ Resolution: N/A")

        return metadata

    except Exception as e:
        print(f"  ✗ Error parsing mmCIF file {mmcif_path}: {e}")
        return None


def fetch_pdb_metadata(pdb_id: str, verbose: bool = False) -> Optional[Dict]:
    """
    Fetch metadata for a PDB entry from local mirror.

    Args:
        pdb_id: 4-letter PDB identifier (e.g., "8yl2")
        verbose: Print detailed progress

    Returns:
        Dictionary with metadata fields, or None if not found
    """
    if verbose:
        print(f"  Fetching {pdb_id}...")

    # Get mmCIF file path
    mmcif_path = get_mmcif_path(pdb_id)

    if mmcif_path is None:
        if verbose:
            print(f"  ⚠️  {pdb_id} not found in local PDB mirror")
        return None

    # Parse metadata from mmCIF
    return parse_mmcif_metadata(mmcif_path, verbose=verbose)


def update_protein_metadata(
    protein_id: int,
    pdb_id: str,
    metadata: Dict,
    calculate_priority: bool,
    conn,
    dry_run: bool = False
) -> bool:
    """
    Update ecod_curation.protein with fetched metadata.

    Args:
        protein_id: Database protein ID
        pdb_id: PDB identifier
        metadata: Dictionary from fetch_pdb_metadata()
        calculate_priority: Whether to recalculate priority score
        conn: Database connection
        dry_run: If True, don't actually update database

    Returns:
        True if update succeeded
    """
    if dry_run:
        print(f"  [DRY RUN] Would update protein_id={protein_id}")
        return True

    cursor = conn.cursor()

    try:
        # Update metadata
        cursor.execute("""
            UPDATE ecod_curation.protein
            SET
                pdb_title = %s,
                pdb_deposition_date = %s,
                pdb_release_date = %s,
                experimental_method = %s,
                resolution_angstrom = %s,
                biological_assembly_count = %s
            WHERE id = %s
        """, (
            metadata['title'],
            metadata['deposition_date'],
            metadata['release_date'],
            metadata['experimental_method'],
            metadata['resolution'],
            metadata['biological_assembly_count'],
            protein_id
        ))

        # Optionally recalculate priority score
        if calculate_priority and metadata['release_date']:
            cursor.execute("""
                UPDATE ecod_curation.protein
                SET priority_score = ecod_curation.calculate_priority_score(
                    release_date,
                    experimental_method,
                    resolution_angstrom,
                    partition_quality
                )
                WHERE id = %s
            """, (protein_id,))

        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        print(f"  ✗ Database error updating protein {protein_id}: {e}")
        return False
    finally:
        cursor.close()


def get_proteins_missing_metadata(conn, batch_name: Optional[str] = None) -> List[Tuple]:
    """
    Get list of proteins missing PDB metadata.

    Args:
        conn: Database connection
        batch_name: Optional batch filter

    Returns:
        List of (protein_id, pdb_id) tuples
    """
    cursor = conn.cursor()

    if batch_name:
        query = """
            SELECT DISTINCT p.id, p.pdb_id
            FROM ecod_curation.protein p
            WHERE p.processing_version LIKE %s
              AND (p.pdb_title IS NULL
                   OR p.pdb_release_date IS NULL
                   OR p.experimental_method IS NULL)
            ORDER BY p.pdb_id
        """
        cursor.execute(query, (f'%{batch_name}%',))
    else:
        query = """
            SELECT DISTINCT id, pdb_id
            FROM ecod_curation.proteins_missing_metadata
            ORDER BY pdb_id
        """
        cursor.execute(query)

    results = cursor.fetchall()
    cursor.close()
    return results


def get_proteins_by_pdb_ids(conn, pdb_ids: List[str]) -> List[Tuple]:
    """
    Get proteins for specific PDB IDs.

    Args:
        conn: Database connection
        pdb_ids: List of PDB identifiers

    Returns:
        List of (protein_id, pdb_id) tuples
    """
    cursor = conn.cursor()

    # Use ANY to match list of PDB IDs
    query = """
        SELECT DISTINCT id, pdb_id
        FROM ecod_curation.protein
        WHERE pdb_id = ANY(%s)
        ORDER BY pdb_id
    """
    cursor.execute(query, (pdb_ids,))

    results = cursor.fetchall()
    cursor.close()
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Extract PDB metadata from local mirror and update ecod_curation.protein",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Mutually exclusive selection modes
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--update-missing',
        action='store_true',
        help='Update all proteins missing metadata'
    )
    group.add_argument(
        '--batch',
        help='Update proteins from specific batch (e.g., ecod_weekly_20250905)'
    )
    group.add_argument(
        '--pdb-ids',
        nargs='+',
        help='Update specific PDB IDs (space-separated)'
    )

    # Options
    parser.add_argument(
        '--calculate-priority',
        action='store_true',
        help='Recalculate priority scores after updating metadata'
    )
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
        print("Please check that /usr2/pdb/data/structures/divided/mmCIF exists")
        return 1

    # Connect to database
    print("Connecting to database...")
    conn = get_db_connection()

    # Get list of proteins to update
    if args.update_missing:
        print("Finding proteins missing metadata...")
        proteins = get_proteins_missing_metadata(conn)
        print(f"Found {len(proteins)} proteins missing metadata")

    elif args.batch:
        print(f"Finding proteins from batch: {args.batch}")
        proteins = get_proteins_missing_metadata(conn, batch_name=args.batch)
        print(f"Found {len(proteins)} proteins in batch missing metadata")

    elif args.pdb_ids:
        print(f"Finding proteins for PDB IDs: {', '.join(args.pdb_ids)}")
        proteins = get_proteins_by_pdb_ids(conn, args.pdb_ids)
        print(f"Found {len(proteins)} proteins matching PDB IDs")

    if len(proteins) == 0:
        print("No proteins to update. Exiting.")
        conn.close()
        return 0

    # Deduplicate by PDB ID (multiple chains may have same PDB)
    pdb_to_proteins = {}
    for protein_id, pdb_id in proteins:
        if pdb_id not in pdb_to_proteins:
            pdb_to_proteins[pdb_id] = []
        pdb_to_proteins[pdb_id].append(protein_id)

    unique_pdbs = list(pdb_to_proteins.keys())
    print(f"\nUnique PDB entries to process: {len(unique_pdbs)}")
    print(f"Total proteins to update: {len(proteins)}")

    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - No database changes will be made\n")

    # Fetch and update
    print(f"\n{'='*70}")
    print("Extracting PDB metadata from local mirror...")
    print(f"{'='*70}\n")

    success_count = 0
    failed_count = 0

    for i, pdb_id in enumerate(unique_pdbs, 1):
        print(f"[{i}/{len(unique_pdbs)}] {pdb_id}")

        # Parse metadata from local mmCIF file
        metadata = fetch_pdb_metadata(pdb_id, verbose=args.verbose)

        if metadata is None:
            failed_count += 1
            continue

        # Update all proteins with this PDB ID
        protein_ids = pdb_to_proteins[pdb_id]
        for protein_id in protein_ids:
            success = update_protein_metadata(
                protein_id,
                pdb_id,
                metadata,
                args.calculate_priority,
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
    print(f"  Unique PDB entries processed: {len(unique_pdbs)}")
    print(f"  Proteins updated: {success_count}")
    print(f"  Failed: {failed_count}")
    if args.dry_run:
        print(f"\n  ⚠️  DRY RUN - No actual database changes were made")
    print(f"{'='*70}\n")

    conn.close()

    return 0 if failed_count == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
