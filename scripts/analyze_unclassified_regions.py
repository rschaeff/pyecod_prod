#!/usr/bin/env python3
"""
Analyze unclassified regions in PDB backfill partitions.

Three key questions:
1. Are unclassified regions disordered? (B-factors, missing density)
2. Do they have secondary structure? (DSSP helix%, sheet%)
3. Are they globular? (Radius of gyration)

Follows BFVD analysis pattern from ~/work/bfvd_2025/identify_unclassified_regions.py
"""

import os
import sys
import subprocess
import tempfile
import argparse
import gzip
from pathlib import Path
from collections import defaultdict
import xml.etree.ElementTree as ET

import numpy as np

try:
    import gemmi
except ImportError:
    print("ERROR: gemmi not installed. Install with: pip install gemmi")
    sys.exit(1)

# Paths
DSSP_BIN = "/home/rschaeff/src/Dali_v5/DaliLite.v5/bin/dsspcmbi"
MMCIF_BASE = "/usr2/pdb/data/structures/divided/mmCIF"


def parse_partition_xml(partition_xml):
    """
    Parse partition XML to extract domain ranges and sequence length.

    Returns:
        {
            'sequence_length': int,
            'domain_ranges': [(start, end), ...],
            'domain_count': int,
            'coverage': float
        }
    """
    tree = ET.parse(partition_xml)
    root = tree.getroot()

    # Get statistics
    stats = root.find(".//statistics")
    if stats is None:
        return None

    seq_length = int(stats.get("sequence_length", "0"))
    coverage = float(stats.get("total_coverage", "0.0"))
    domain_count = int(stats.get("domain_count", "0"))

    # Get domain ranges
    domain_ranges = []
    for domain in root.findall(".//domain"):
        range_str = domain.get("range", "")
        if range_str:
            # Parse range: "10-50" or "10-50,100-150"
            for segment in range_str.split(','):
                start, end = map(int, segment.strip().split('-'))
                domain_ranges.append((start, end))

    return {
        'sequence_length': seq_length,
        'domain_ranges': domain_ranges,
        'domain_count': domain_count,
        'coverage': coverage
    }


def find_unclassified_regions(seq_length, domain_ranges):
    """
    Find gaps between domains (unclassified regions).

    Returns: [(start, end), ...]
    """
    if not domain_ranges:
        return [(1, seq_length)]

    # Merge overlapping domains
    sorted_ranges = sorted(domain_ranges)
    merged = [sorted_ranges[0]]

    for start, end in sorted_ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    # Find gaps
    gaps = []

    # N-terminus gap
    if merged[0][0] > 1:
        gaps.append((1, merged[0][0] - 1))

    # Internal gaps
    for i in range(len(merged) - 1):
        gap_start = merged[i][1] + 1
        gap_end = merged[i+1][0] - 1
        if gap_start <= gap_end:
            gaps.append((gap_start, gap_end))

    # C-terminus gap
    if merged[-1][1] < seq_length:
        gaps.append((merged[-1][1] + 1, seq_length))

    return gaps


def get_mmcif_path(pdb_id):
    """
    Get path to mmCIF file from PDB mirror.

    Args:
        pdb_id: 4-letter PDB ID (e.g., "8abc")

    Returns: Path to gzipped mmCIF file
    """
    middle_2 = pdb_id[1:3].lower()
    cif_file = f"{pdb_id.lower()}.cif.gz"
    return os.path.join(MMCIF_BASE, middle_2, cif_file)


def calculate_radius_of_gyration(structure, chain_id, start, end):
    """
    Calculate radius of gyration for a region from Cα coordinates.

    Args:
        structure: gemmi Structure object
        chain_id: Chain ID
        start: Start residue (1-indexed)
        end: End residue (1-indexed)

    Returns: (Rg, Rg_normalized) or (None, None)
    """
    try:
        ca_coords = []

        for chain in structure[0]:
            if chain.name != chain_id:
                continue

            for residue in chain:
                seqid = residue.seqid.num
                if start <= seqid <= end:
                    ca = residue.find_atom("CA", "*")
                    if ca:
                        pos = ca.pos
                        ca_coords.append([pos.x, pos.y, pos.z])

        if len(ca_coords) < 3:
            return None, None

        coords = np.array(ca_coords)
        center = coords.mean(axis=0)
        sq_distances = np.sum((coords - center)**2, axis=1)
        rg = np.sqrt(sq_distances.mean())

        # Normalize by length^0.6 (expected scaling for random coil)
        length = end - start + 1
        rg_normalized = rg / (length ** 0.6)

        return round(rg, 3), round(rg_normalized, 3)

    except Exception as e:
        print(f"  WARNING: Rg calculation failed: {e}")
        return None, None


def calculate_mean_bfactor(structure, chain_id, start, end):
    """
    Calculate mean and min B-factor for a region.

    B-factors indicate disorder (higher = more disordered).

    Returns: (mean_bfactor, min_bfactor) or (None, None)
    """
    try:
        bfactors = []

        for chain in structure[0]:
            if chain.name != chain_id:
                continue

            for residue in chain:
                seqid = residue.seqid.num
                if start <= seqid <= end:
                    for atom in residue:
                        if atom.name == "CA":
                            bfactors.append(atom.b_iso)
                            break

        if not bfactors:
            return None, None

        return round(np.mean(bfactors), 2), round(np.min(bfactors), 2)

    except Exception:
        return None, None


def run_dssp(structure, chain_id, start, end, temp_dir):
    """
    Run DSSP on a region to characterize secondary structure.

    Returns: dict with helix_pct, sheet_pct, has_significant_ss, etc.
    """
    try:
        # Create new structure with only this region
        new_structure = gemmi.Structure()
        new_model = gemmi.Model("1")
        new_chain = gemmi.Chain("A")

        for chain in structure[0]:
            if chain.name != chain_id:
                continue

            for residue in chain:
                seqid = residue.seqid.num
                if start <= seqid <= end:
                    new_chain.add_residue(residue)

        if len(new_chain) == 0:
            return None

        new_model.add_chain(new_chain)
        new_structure.add_model(new_model)

        # Write temporary PDB
        temp_pdb = os.path.join(temp_dir, "region.pdb")
        new_structure.write_pdb(temp_pdb)

        # Run DSSP
        dssp_out = os.path.join(temp_dir, "region.dssp")
        result = subprocess.run(
            [DSSP_BIN, temp_pdb, dssp_out],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0 or not os.path.exists(dssp_out):
            return None

        # Parse DSSP output
        return parse_dssp_output(dssp_out)

    except Exception as e:
        print(f"  WARNING: DSSP failed: {e}")
        return None


def parse_dssp_output(dssp_file):
    """
    Parse DSSP output to count secondary structure elements.

    Returns: dict with counts and percentages
    """
    helix_codes = {'H', 'G', 'I'}
    sheet_codes = {'E', 'B'}
    turn_codes = {'T', 'S'}

    helix_count = 0
    sheet_count = 0
    turn_count = 0
    coil_count = 0
    total = 0

    with open(dssp_file, 'r') as f:
        in_residues = False

        for line in f:
            if line.startswith("  #  RESIDUE"):
                in_residues = True
                continue

            if not in_residues or len(line) < 20:
                continue

            # DSSP format: SS is at position 16
            ss = line[16] if len(line) > 16 else ' '

            if ss in helix_codes:
                helix_count += 1
            elif ss in sheet_codes:
                sheet_count += 1
            elif ss in turn_codes:
                turn_count += 1
            else:
                coil_count += 1

            total += 1

    if total == 0:
        return None

    helix_pct = round(100.0 * helix_count / total, 2)
    sheet_pct = round(100.0 * sheet_count / total, 2)

    return {
        'helix_count': helix_count,
        'sheet_count': sheet_count,
        'turn_count': turn_count,
        'coil_count': coil_count,
        'helix_pct': helix_pct,
        'sheet_pct': sheet_pct,
        'has_significant_ss': (helix_count + sheet_count) >= 0.2 * total
    }


def analyze_chain(pdb_id, chain_id, partition_xml, temp_dir):
    """
    Analyze unclassified regions for a single chain.

    Returns: list of dicts with region analysis results
    """
    # Parse partition XML
    partition_data = parse_partition_xml(partition_xml)
    if not partition_data:
        return []

    seq_length = partition_data['sequence_length']
    domain_ranges = partition_data['domain_ranges']

    # Find unclassified regions
    unclassified = find_unclassified_regions(seq_length, domain_ranges)

    if not unclassified:
        return []

    # Get mmCIF structure
    mmcif_path = get_mmcif_path(pdb_id)
    if not os.path.exists(mmcif_path):
        print(f"  WARNING: mmCIF not found: {mmcif_path}")
        return []

    # Load structure
    structure = gemmi.read_structure(mmcif_path)

    # Analyze each unclassified region
    results = []

    for ucr_idx, (start, end) in enumerate(unclassified, 1):
        ucr_length = end - start + 1

        # Skip very short regions
        if ucr_length < 10:
            continue

        print(f"  Analyzing UCR{ucr_idx}: {start}-{end} ({ucr_length} residues)")

        # Calculate structural properties
        rg, rg_norm = calculate_radius_of_gyration(structure, chain_id, start, end)
        mean_bfactor, min_bfactor = calculate_mean_bfactor(structure, chain_id, start, end)
        dssp_result = run_dssp(structure, chain_id, start, end, temp_dir)

        # Determine globularity
        is_globular = None
        if rg_norm is not None:
            is_globular = rg_norm < 1.0  # More compact than random coil

        results.append({
            'pdb_id': pdb_id,
            'chain_id': chain_id,
            'ucr_id': f"ucr{ucr_idx}",
            'range': f"{start}-{end}",
            'length': ucr_length,
            'seq_length': seq_length,
            'domain_count': partition_data['domain_count'],
            'coverage': partition_data['coverage'],
            # Globularity
            'rg': rg,
            'rg_normalized': rg_norm,
            'is_globular': is_globular,
            # Disorder
            'mean_bfactor': mean_bfactor,
            'min_bfactor': min_bfactor,
            # Secondary structure
            'helix_pct': dssp_result['helix_pct'] if dssp_result else None,
            'sheet_pct': dssp_result['sheet_pct'] if dssp_result else None,
            'has_significant_ss': dssp_result['has_significant_ss'] if dssp_result else None,
        })

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Analyze unclassified regions in PDB backfill partitions'
    )
    parser.add_argument(
        'partition_dir',
        help='Directory containing partition XML files'
    )
    parser.add_argument(
        '--output',
        default='unclassified_regions_analysis.tsv',
        help='Output TSV file'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of chains to analyze (for testing)'
    )

    args = parser.parse_args()

    partition_dir = Path(args.partition_dir)
    if not partition_dir.exists():
        print(f"ERROR: Partition directory not found: {partition_dir}")
        sys.exit(1)

    # Get partition XML files
    partition_files = sorted(partition_dir.glob("*.partition.xml"))

    if args.limit:
        partition_files = partition_files[:args.limit]

    print(f"Found {len(partition_files)} partition files")
    print()

    # Create temp directory for DSSP
    temp_dir = tempfile.mkdtemp(prefix="ucr_analysis_")

    all_results = []

    try:
        for idx, partition_file in enumerate(partition_files, 1):
            # Parse chain ID from filename: "8abc_A.partition.xml"
            filename = partition_file.stem.replace('.partition', '')
            pdb_id, chain_id = filename.split('_', 1)

            print(f"[{idx}/{len(partition_files)}] {pdb_id}_{chain_id}")

            try:
                results = analyze_chain(pdb_id, chain_id, partition_file, temp_dir)
                all_results.extend(results)

                if results:
                    print(f"  Found {len(results)} unclassified regions")

            except Exception as e:
                print(f"  ERROR: {e}")
                continue

        # Write results
        if all_results:
            print()
            print(f"Writing {len(all_results)} unclassified regions to {args.output}")

            with open(args.output, 'w') as f:
                # Header
                fields = [
                    'pdb_id', 'chain_id', 'ucr_id', 'range', 'length',
                    'seq_length', 'domain_count', 'coverage',
                    'rg', 'rg_normalized', 'is_globular',
                    'mean_bfactor', 'min_bfactor',
                    'helix_pct', 'sheet_pct', 'has_significant_ss'
                ]
                f.write('\t'.join(fields) + '\n')

                # Data
                for result in all_results:
                    values = [str(result.get(field, '')) for field in fields]
                    f.write('\t'.join(values) + '\n')

            # Summary statistics
            print()
            print("="*60)
            print("SUMMARY STATISTICS")
            print("="*60)

            total_chains = len(set((r['pdb_id'], r['chain_id']) for r in all_results))
            total_ucrs = len(all_results)

            print(f"Chains analyzed: {total_chains}")
            print(f"Unclassified regions found: {total_ucrs}")
            print()

            # Question 1: Disorder
            bfactors = [r['mean_bfactor'] for r in all_results if r['mean_bfactor'] is not None]
            if bfactors:
                print(f"Disorder (B-factor):")
                print(f"  Mean B-factor: {np.mean(bfactors):.2f} ± {np.std(bfactors):.2f}")
                print(f"  High disorder (B>50): {sum(1 for b in bfactors if b > 50)} ({100*sum(1 for b in bfactors if b > 50)/len(bfactors):.1f}%)")
                print()

            # Question 2: Secondary structure
            with_ss = [r for r in all_results if r['has_significant_ss'] is not None]
            if with_ss:
                sig_ss_count = sum(1 for r in with_ss if r['has_significant_ss'])
                print(f"Secondary structure:")
                print(f"  With significant SS (≥20% helix+sheet): {sig_ss_count}/{len(with_ss)} ({100*sig_ss_count/len(with_ss):.1f}%)")

                helix_pcts = [r['helix_pct'] for r in with_ss if r['helix_pct'] is not None]
                sheet_pcts = [r['sheet_pct'] for r in with_ss if r['sheet_pct'] is not None]

                if helix_pcts:
                    print(f"  Mean helix%: {np.mean(helix_pcts):.1f}% ± {np.std(helix_pcts):.1f}%")
                if sheet_pcts:
                    print(f"  Mean sheet%: {np.mean(sheet_pcts):.1f}% ± {np.std(sheet_pcts):.1f}%")
                print()

            # Question 3: Globularity
            globular_data = [r for r in all_results if r['is_globular'] is not None]
            if globular_data:
                globular_count = sum(1 for r in globular_data if r['is_globular'])
                print(f"Globularity:")
                print(f"  Globular (Rg_norm < 1.0): {globular_count}/{len(globular_data)} ({100*globular_count/len(globular_data):.1f}%)")

                rg_norms = [r['rg_normalized'] for r in globular_data]
                print(f"  Mean Rg_normalized: {np.mean(rg_norms):.3f} ± {np.std(rg_norms):.3f}")
                print()

            print("="*60)

        else:
            print()
            print("No unclassified regions found")

    finally:
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

    print()
    print("Done!")


if __name__ == '__main__':
    main()
