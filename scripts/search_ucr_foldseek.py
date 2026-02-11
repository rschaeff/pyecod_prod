#!/usr/bin/env python3
"""
Search unclassified regions (UCRs) against ECOD using Foldseek.

Identifies domain-like UCRs (globular + has significant SS) and searches
for distant structural similarity using Foldseek against ECOD database.

Workflow:
1. Read UCR analysis TSV (from analyze_unclassified_regions.py)
2. Filter for domain-like regions (is_globular=True AND has_significant_ss=True)
3. Extract UCR structures to separate PDB files
4. Run Foldseek against ECOD database
5. Parse results and add to analysis output

Based on BFVD workflow: ~/work/bfvd_2025/cluster_ucr_foldseek.py
"""

import os
import sys
import subprocess
import argparse
import tempfile
from pathlib import Path
import pandas as pd

try:
    import gemmi
except ImportError:
    print("ERROR: gemmi not installed. Install with: pip install gemmi")
    sys.exit(1)

# Add src to path for pyecod_prod imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.utils.pdb_ids import get_directory_hash

# Paths
FOLDSEEK_BIN = "/home/rschaeff/.conda/envs/dpam/bin/foldseek"
ECOD_FOLDSEEK_DB = "/home/rschaeff/data/dpam_reference/ecod_data/ECOD_foldseek_DB"
MMCIF_BASE = "/usr2/pdb/data/structures/divided/mmCIF"


def get_mmcif_path(pdb_id):
    """
    Get path to mmCIF file from PDB mirror.

    Supports both legacy 4-character and extended 12-character PDB IDs.
    """
    pdb_id_lower = pdb_id.lower()
    dir_hash = get_directory_hash(pdb_id_lower)
    cif_file = f"{pdb_id_lower}.cif.gz"
    return os.path.join(MMCIF_BASE, dir_hash, cif_file)


def extract_ucr_structure(pdb_id, chain_id, start, end, output_pdb):
    """
    Extract unclassified region to separate PDB file.

    Args:
        pdb_id: PDB ID
        chain_id: Chain ID
        start: Start residue (1-indexed)
        end: End residue (1-indexed)
        output_pdb: Output PDB file path
    """
    mmcif_path = get_mmcif_path(pdb_id)
    if not os.path.exists(mmcif_path):
        raise FileNotFoundError(f"mmCIF not found: {mmcif_path}")

    structure = gemmi.read_structure(mmcif_path)

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
        raise ValueError(f"No residues found for {pdb_id}_{chain_id} {start}-{end}")

    new_model.add_chain(new_chain)
    new_structure.add_model(new_model)

    # Write PDB
    new_structure.write_pdb(output_pdb)


def run_foldseek(query_dir, output_tsv, sensitivity=7.5):
    """
    Run Foldseek search against ECOD database.

    Args:
        query_dir: Directory containing query PDB files
        output_tsv: Output TSV file
        sensitivity: Foldseek sensitivity (default: 7.5 for remote homology)

    Returns: Path to output TSV
    """
    print(f"Running Foldseek (sensitivity={sensitivity})...")

    # Create temporary database for queries
    temp_db = tempfile.mktemp(prefix="foldseek_query_")

    try:
        # Create query database
        subprocess.run(
            [FOLDSEEK_BIN, "createdb", query_dir, temp_db],
            check=True,
            capture_output=True
        )

        # Search against ECOD
        temp_result = tempfile.mktemp(prefix="foldseek_result_")

        result = subprocess.run([
            FOLDSEEK_BIN, "search",
            temp_db,
            ECOD_FOLDSEEK_DB,
            temp_result,
            tempfile.mkdtemp(prefix="foldseek_tmp_"),
            "-s", str(sensitivity),
            "-e", "0.001",  # E-value threshold
            "--alignment-type", "2",  # TM-align
            "-c", "0.5",  # Coverage threshold
            "-a",  # Generate alignment backtraces (required for TM-scores)
        ], capture_output=True, text=True)

        if result.returncode != 0:
            print(f"  ERROR: Foldseek search failed")
            print(f"  stdout: {result.stdout}")
            print(f"  stderr: {result.stderr}")
            raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)

        # Convert to TSV
        convert_result = subprocess.run([
            FOLDSEEK_BIN, "convertalis",
            temp_db,
            ECOD_FOLDSEEK_DB,
            temp_result,
            output_tsv,
            "--format-output", "query,target,fident,alnlen,mismatch,gapopen,qstart,qend,tstart,tend,evalue,bits,alntmscore,qtmscore,ttmscore"
        ], capture_output=True, text=True)

        if convert_result.returncode != 0:
            print(f"  ERROR: Foldseek convertalis failed")
            print(f"  stdout: {convert_result.stdout}")
            print(f"  stderr: {convert_result.stderr}")
            raise subprocess.CalledProcessError(convert_result.returncode, convert_result.args, convert_result.stdout, convert_result.stderr)

        print(f"  Foldseek results: {output_tsv}")

    finally:
        # Cleanup temp files
        for suffix in ["", ".dbtype", ".index", ".lookup", "_h", "_h.dbtype", "_h.index"]:
            for temp_file in [temp_db + suffix, temp_result + suffix]:
                if os.path.exists(temp_file):
                    os.remove(temp_file)

    return output_tsv


def parse_foldseek_results(foldseek_tsv):
    """
    Parse Foldseek results and extract best hits.

    Returns: dict mapping ucr_id to {
        'target': str (ECOD domain ID),
        'evalue': float,
        'alntmscore': float,
        'qtmscore': float,
        'ttmscore': float
    }
    """
    if not os.path.exists(foldseek_tsv):
        return {}

    # Read TSV
    df = pd.read_csv(foldseek_tsv, sep='\t', names=[
        'query', 'target', 'fident', 'alnlen', 'mismatch', 'gapopen',
        'qstart', 'qend', 'tstart', 'tend', 'evalue', 'bits',
        'alntmscore', 'qtmscore', 'ttmscore'
    ])

    if df.empty:
        return {}

    # Get best hit per query (lowest E-value)
    best_hits = df.loc[df.groupby('query')['evalue'].idxmin()]

    results = {}
    for _, row in best_hits.iterrows():
        ucr_id = row['query']
        results[ucr_id] = {
            'target': row['target'],
            'evalue': row['evalue'],
            'alntmscore': row['alntmscore'],
            'qtmscore': row['qtmscore'],
            'ttmscore': row['ttmscore']
        }

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Search domain-like unclassified regions against ECOD using Foldseek'
    )
    parser.add_argument(
        'ucr_tsv',
        help='Input TSV from analyze_unclassified_regions.py'
    )
    parser.add_argument(
        '--output',
        default='ucr_foldseek_results.tsv',
        help='Output TSV file with Foldseek results'
    )
    parser.add_argument(
        '--min-length',
        type=int,
        default=30,
        help='Minimum UCR length to search (default: 30)'
    )
    parser.add_argument(
        '--sensitivity',
        type=float,
        default=7.5,
        help='Foldseek sensitivity (default: 7.5)'
    )

    args = parser.parse_args()

    # Read UCR analysis
    print(f"Reading UCR analysis: {args.ucr_tsv}")
    df = pd.read_csv(args.ucr_tsv, sep='\t')

    print(f"  Total UCRs: {len(df)}")

    # Filter for domain-like regions
    domain_like = df[
        (df['is_globular'] == True) &
        (df['has_significant_ss'] == True) &
        (df['length'] >= args.min_length)
    ]

    print(f"  Domain-like UCRs (globular + has SS + length≥{args.min_length}): {len(domain_like)}")

    if domain_like.empty:
        print("No domain-like UCRs found!")
        return

    # Create temp directory for UCR structures
    temp_dir = tempfile.mkdtemp(prefix="ucr_structures_")
    print(f"Extracting UCR structures to: {temp_dir}")

    extracted_count = 0
    ucr_id_map = {}  # Map filename to original UCR info

    try:
        for idx, row in domain_like.iterrows():
            pdb_id = row['pdb_id']
            chain_id = row['chain_id']
            ucr_id = row['ucr_id']
            range_str = row['range']

            # Parse range
            start, end = map(int, range_str.split('-'))

            # Create filename: pdb_chain_ucr.pdb
            ucr_filename = f"{pdb_id}_{chain_id}_{ucr_id}"
            output_pdb = os.path.join(temp_dir, f"{ucr_filename}.pdb")

            try:
                extract_ucr_structure(pdb_id, chain_id, start, end, output_pdb)
                ucr_id_map[ucr_filename] = row.to_dict()
                extracted_count += 1

                if extracted_count % 50 == 0:
                    print(f"  Extracted {extracted_count}/{len(domain_like)} UCRs")

            except Exception as e:
                print(f"  WARNING: Failed to extract {pdb_id}_{chain_id}_{ucr_id}: {e}")

        print(f"Extracted {extracted_count} UCR structures")

        if extracted_count == 0:
            print("No structures extracted!")
            return

        # Run Foldseek
        foldseek_tsv = tempfile.mktemp(prefix="foldseek_results_", suffix=".tsv")
        run_foldseek(temp_dir, foldseek_tsv, sensitivity=args.sensitivity)

        # Parse Foldseek results
        print("Parsing Foldseek results...")
        foldseek_results = parse_foldseek_results(foldseek_tsv)

        print(f"  Found structural similarity for {len(foldseek_results)}/{extracted_count} UCRs")

        # Merge with original data
        output_rows = []

        for ucr_filename, ucr_info in ucr_id_map.items():
            hit = foldseek_results.get(ucr_filename)

            output_row = ucr_info.copy()

            if hit:
                output_row['foldseek_target'] = hit['target']
                output_row['foldseek_evalue'] = hit['evalue']
                output_row['foldseek_alntmscore'] = hit['alntmscore']
                output_row['foldseek_qtmscore'] = hit['qtmscore']
                output_row['foldseek_ttmscore'] = hit['ttmscore']
            else:
                output_row['foldseek_target'] = None
                output_row['foldseek_evalue'] = None
                output_row['foldseek_alntmscore'] = None
                output_row['foldseek_qtmscore'] = None
                output_row['foldseek_ttmscore'] = None

            output_rows.append(output_row)

        # Write output
        output_df = pd.DataFrame(output_rows)
        output_df.to_csv(args.output, sep='\t', index=False)

        print(f"Results written to: {args.output}")

        # Summary statistics
        print()
        print("="*60)
        print("FOLDSEEK SEARCH SUMMARY")
        print("="*60)

        with_hits = output_df[output_df['foldseek_target'].notna()]
        print(f"Domain-like UCRs searched: {len(output_df)}")
        print(f"UCRs with ECOD structural similarity: {len(with_hits)} ({100*len(with_hits)/len(output_df):.1f}%)")

        if not with_hits.empty:
            print(f"Mean TM-score (alignment): {with_hits['foldseek_alntmscore'].mean():.3f}")
            print(f"Mean TM-score (query): {with_hits['foldseek_qtmscore'].mean():.3f}")

            # Best hits
            print()
            print("Top 10 hits by TM-score:")
            print(f"  {'UCR':<20} {'Target':<15} {'E-value':<12} {'TM-score':<10}")
            print(f"  {'-'*20} {'-'*15} {'-'*12} {'-'*10}")

            top_hits = with_hits.nlargest(10, 'foldseek_qtmscore')
            for _, row in top_hits.iterrows():
                ucr_str = f"{row['pdb_id']}_{row['chain_id']}_{row['ucr_id']}"
                print(f"  {ucr_str:<20} {row['foldseek_target']:<15} {row['foldseek_evalue']:<12.2e} {row['foldseek_qtmscore']:<10.3f}")

        print("="*60)

    finally:
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        if os.path.exists(foldseek_tsv):
            os.remove(foldseek_tsv)

    print()
    print("Done!")


if __name__ == '__main__':
    main()
