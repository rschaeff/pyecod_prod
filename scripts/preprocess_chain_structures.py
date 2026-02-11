#!/usr/bin/env python3
"""
Preprocess chain structures for ECOD curation interface.

Extracts individual chain PDB files from mmCIF structures for 3D visualization
in pyecod_vis. Processes chains with completed partitions.

Usage:
    python preprocess_chain_structures.py \\
        --partition-dir /path/to/partitions \\
        --output-dir /path/to/chain_pdbs \\
        [--batch-size 100] [--batch-index 0]
"""

import os
import sys
import argparse
from pathlib import Path

try:
    import gemmi
except ImportError:
    print("ERROR: gemmi not installed. Install with: pip install gemmi")
    sys.exit(1)

# Add src to path for pyecod_prod imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.utils.pdb_ids import get_directory_hash

# PDB mirror path
MMCIF_BASE = "/data/usr2/pdb/data/structures/divided/mmCIF"


def get_mmcif_path(pdb_id):
    """
    Get path to mmCIF file from PDB mirror.

    Supports both legacy 4-character and extended 12-character PDB IDs.
    """
    pdb_id_lower = pdb_id.lower()
    dir_hash = get_directory_hash(pdb_id_lower)
    cif_file = f"{pdb_id_lower}.cif.gz"
    return os.path.join(MMCIF_BASE, dir_hash, cif_file)


def extract_chain_pdb(pdb_id, chain_id, output_pdb):
    """
    Extract a single chain from mmCIF and write as PDB.

    Args:
        pdb_id: PDB ID (e.g., "7yp8")
        chain_id: Chain ID (e.g., "A")
        output_pdb: Output PDB file path

    Returns:
        True if successful, False otherwise
    """
    mmcif_path = get_mmcif_path(pdb_id)

    if not os.path.exists(mmcif_path):
        print(f"  WARNING: mmCIF not found: {mmcif_path}")
        return False

    try:
        # Read structure
        structure = gemmi.read_structure(mmcif_path)

        # Create new structure with only this chain
        new_structure = gemmi.Structure()
        new_structure.name = f"{pdb_id}_{chain_id}"

        new_model = gemmi.Model("1")

        # Find and copy the target chain
        found = False
        for chain in structure[0]:
            if chain.name == chain_id:
                new_model.add_chain(chain)
                found = True
                break

        if not found:
            print(f"  WARNING: Chain {chain_id} not found in {pdb_id}")
            return False

        if len(new_model) == 0:
            print(f"  WARNING: Chain {chain_id} is empty in {pdb_id}")
            return False

        new_structure.add_model(new_model)

        # Write PDB
        new_structure.write_pdb(output_pdb)
        return True

    except Exception as e:
        print(f"  ERROR: Failed to extract {pdb_id}_{chain_id}: {e}")
        return False


def parse_partition_filename(partition_file):
    """
    Parse partition filename to extract PDB ID and chain ID.

    Format: <pdb_id>_<chain_id>.partition.xml
    Examples:
        7yp8_A.partition.xml -> (7yp8, A)
        8ckb_A001.partition.xml -> (8ckb, A001)
    """
    basename = partition_file.name
    # Remove .partition.xml suffix
    chain_str = basename.replace('.partition.xml', '')

    # Split on underscore
    parts = chain_str.split('_')
    if len(parts) != 2:
        raise ValueError(f"Unexpected partition filename format: {basename}")

    pdb_id, chain_id = parts
    return pdb_id, chain_id


def main():
    parser = argparse.ArgumentParser(
        description='Preprocess chain structures for ECOD curation interface'
    )
    parser.add_argument(
        '--partition-dir',
        required=True,
        help='Directory containing partition XML files'
    )
    parser.add_argument(
        '--output-dir',
        required=True,
        help='Output directory for chain PDB files'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=None,
        help='Process chains in batches of this size (for SLURM arrays)'
    )
    parser.add_argument(
        '--batch-index',
        type=int,
        default=0,
        help='Batch index to process (0-indexed, for SLURM arrays)'
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Overwrite existing PDB files'
    )

    args = parser.parse_args()

    partition_dir = Path(args.partition_dir)
    output_dir = Path(args.output_dir)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get list of partition files
    partition_files = sorted(partition_dir.glob("*.partition.xml"))

    print(f"Found {len(partition_files)} partition files")

    if len(partition_files) == 0:
        print("ERROR: No partition files found!")
        return 1

    # Apply batching if requested
    if args.batch_size:
        start_idx = args.batch_index * args.batch_size
        end_idx = start_idx + args.batch_size
        partition_files = partition_files[start_idx:end_idx]
        print(f"Processing batch {args.batch_index}: chains {start_idx+1}-{min(end_idx, len(partition_files))}")

    # Process each partition
    success_count = 0
    skip_count = 0
    fail_count = 0

    for i, partition_file in enumerate(partition_files, 1):
        try:
            pdb_id, chain_id = parse_partition_filename(partition_file)

            # Output path
            output_pdb = output_dir / f"{pdb_id}_{chain_id}.pdb"

            # Skip if exists and not overwriting
            if output_pdb.exists() and not args.overwrite:
                skip_count += 1
                if i % 100 == 0:
                    print(f"  Progress: {i}/{len(partition_files)} chains "
                          f"(success: {success_count}, skip: {skip_count}, fail: {fail_count})")
                continue

            # Extract chain
            if extract_chain_pdb(pdb_id, chain_id, str(output_pdb)):
                success_count += 1
            else:
                fail_count += 1

            # Progress update
            if i % 100 == 0:
                print(f"  Progress: {i}/{len(partition_files)} chains "
                      f"(success: {success_count}, skip: {skip_count}, fail: {fail_count})")

        except Exception as e:
            print(f"  ERROR: Failed to process {partition_file.name}: {e}")
            fail_count += 1

    # Final summary
    print()
    print("="*60)
    print("STRUCTURE PREPROCESSING SUMMARY")
    print("="*60)
    print(f"Total partitions: {len(partition_files)}")
    print(f"Successfully extracted: {success_count}")
    print(f"Skipped (already exist): {skip_count}")
    print(f"Failed: {fail_count}")
    print(f"Success rate: {100*success_count/(len(partition_files)-skip_count):.1f}%")
    print("="*60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
