#!/usr/bin/env python3
"""
Render protein chains with colored domains, filtered to 70% representatives and sorted by quality.

Quality categories:
  A) Fully classified: coverage >= 90%
  B) Partially classified: 50% <= coverage < 90%
  C) Unclassified: coverage < 50% or no domains
  D) Unclassified + low complexity: unclassified with short chains or few residues
"""

import os
import sys
import xml.etree.ElementTree as ET
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple
from collections import defaultdict

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.batch.manifest import BatchManifest


# Color palette for domains (up to 10 domains per chain)
DOMAIN_COLORS = [
    "marine",      # Domain 1: blue
    "salmon",      # Domain 2: orange/red
    "palegreen",   # Domain 3: green
    "gold",        # Domain 4: yellow
    "violet",      # Domain 5: purple
    "cyan",        # Domain 6: cyan
    "pink",        # Domain 7: pink
    "lime",        # Domain 8: bright green
    "orange",      # Domain 9: orange
    "wheat",       # Domain 10: tan
]


def parse_partition_xml(xml_path: str) -> Dict:
    """
    Parse partition XML to extract domain information and coverage.

    Returns:
        dict with keys: pdb_id, chain_id, coverage, seq_length, domains (list)
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    pdb_id = root.get("pdb_id")
    chain_id = root.get("chain_id")

    # Get coverage from metadata
    coverage = 0.0
    seq_length = 0
    metadata = root.find("metadata")
    if metadata is not None:
        cov_elem = metadata.find("partition_coverage")
        if cov_elem is not None:
            coverage = float(cov_elem.text)

        seqlen_elem = metadata.find("sequence_length")
        if seqlen_elem is not None:
            seq_length = int(seqlen_elem.text)

    domains = []
    for domain_elem in root.findall(".//domains/domain"):
        domain = {
            "id": domain_elem.get("id"),
            "range": domain_elem.get("range"),
            "family": domain_elem.get("family"),
            "source": domain_elem.get("source"),
        }
        domains.append(domain)

    return {
        "pdb_id": pdb_id,
        "chain_id": chain_id,
        "coverage": coverage,
        "seq_length": seq_length,
        "domains": domains,
    }


def categorize_chain(partition_data: Dict) -> str:
    """
    Categorize chain by quality.

    Returns:
        Category code: 'A', 'B', 'C', or 'D'
    """
    coverage = partition_data["coverage"]
    domain_count = len(partition_data["domains"])
    seq_length = partition_data["seq_length"]

    # Category A: Fully classified (>= 90% coverage)
    if coverage >= 0.90:
        return "A"

    # Category B: Partially classified (50-90% coverage)
    elif coverage >= 0.50:
        return "B"

    # Category C: Unclassified (< 50% coverage)
    elif domain_count > 0:
        return "C"

    # Category D: Unclassified + low complexity
    # (no domains and short/simple chain)
    else:
        # Consider chains < 100 residues as potentially low complexity
        if seq_length < 100:
            return "D"
        else:
            return "C"


def is_representative(chain_key: str, manifest_data: Dict) -> bool:
    """
    Check if chain is a 70% representative.

    Args:
        chain_key: "pdb_chain" format (e.g., "8yl2_C")
        manifest_data: Manifest data dict

    Returns:
        True if chain is a representative (cluster_representative is None)
    """
    chains = manifest_data.get("chains", {})
    chain_data = chains.get(chain_key)

    if not chain_data:
        return False

    # Representatives have cluster_representative = None
    # Non-representatives have cluster_representative = <rep_id>
    cluster_rep = chain_data.get("cluster_representative")

    # If cluster_representative field doesn't exist, assume it's a representative
    # (for batches without CD-HIT clustering)
    if "cluster_representative" not in chain_data:
        return True

    # It's a representative if cluster_representative is None
    return cluster_rep is None


def parse_range(range_str: str) -> List[Tuple[int, int]]:
    """Parse domain range string into list of (start, end) tuples."""
    segments = []
    for segment in range_str.split(","):
        start, end = map(int, segment.split("-"))
        segments.append((start, end))
    return segments


def get_pdb_residue_mapping(pdb_file: str, chain_id: str) -> Dict[int, str]:
    """Extract sequence position to PDB residue number mapping from mmCIF file."""
    import gzip

    mapping = {}

    try:
        if pdb_file.endswith(".gz"):
            f = gzip.open(pdb_file, "rt")
        else:
            f = open(pdb_file, "r")

        in_atom_site = False

        for line in f:
            if line.startswith("_atom_site."):
                in_atom_site = True
                continue

            if in_atom_site:
                if line.startswith("_") or line.startswith("#"):
                    break

                parts = line.split()
                if len(parts) < 20:
                    continue

                try:
                    atom_name = parts[3] if len(parts) > 3 else None
                    label_seq = parts[8] if len(parts) > 8 else None
                    auth_seq = parts[16] if len(parts) > 16 else None
                    auth_chain = parts[18] if len(parts) > 18 else None

                    if auth_chain == chain_id and atom_name == "CA":
                        if label_seq and auth_seq:
                            seq_num = int(label_seq)
                            mapping[seq_num] = auth_seq

                except (ValueError, IndexError):
                    continue

        f.close()

    except Exception as e:
        print(f"  WARNING: Could not parse PDB residue mapping: {e}")
        return {}

    return mapping


def map_seq_range_to_pdb(
    seq_range: Tuple[int, int],
    seq_to_pdb: Dict[int, str]
) -> str:
    """Map sequence range to PDB residue range."""
    start_seq, end_seq = seq_range

    if not seq_to_pdb:
        return f"{start_seq}-{end_seq}"

    start_pdb = seq_to_pdb.get(start_seq, str(start_seq))
    end_pdb = seq_to_pdb.get(end_seq, str(end_seq))

    return f"{start_pdb}-{end_pdb}"


def generate_pymol_script(
    pdb_id: str,
    chain_id: str,
    domains: List[Dict],
    pdb_file: str,
    output_png: str,
) -> str:
    """Generate PyMOL script to render chain with colored domains."""
    seq_to_pdb = get_pdb_residue_mapping(pdb_file, chain_id)

    script_lines = [
        "# PyMOL script for domain visualization",
        f"# PDB: {pdb_id}, Chain: {chain_id}",
        "",
        "# Load structure",
        f"load {pdb_file}, protein",
        "",
        "# Basic setup",
        "bg_color white",
        "hide everything",
        f"select chain_{chain_id}, chain {chain_id}",
        f"show cartoon, chain_{chain_id}",
        "",
        "# Color by domain",
    ]

    if not domains:
        script_lines.extend([
            f"color gray80, chain_{chain_id}",
        ])
    else:
        for i, domain in enumerate(domains):
            color = DOMAIN_COLORS[i % len(DOMAIN_COLORS)]
            range_str = domain["range"]
            family = domain["family"]

            segments = parse_range(range_str)
            for seg_idx, (start, end) in enumerate(segments):
                pdb_range = map_seq_range_to_pdb((start, end), seq_to_pdb)
                sel_name = f"domain_{i+1}_seg_{seg_idx+1}"
                script_lines.append(
                    f"select {sel_name}, chain {chain_id} and resi {pdb_range}"
                )
                script_lines.append(f"color {color}, {sel_name}")

            script_lines.append(f"# Domain {i+1}: {family} (sequence: {range_str})")

        script_lines.append("")

    script_lines.extend([
        "",
        "# Center and orient",
        f"center chain_{chain_id}",
        f"orient chain_{chain_id}",
        f"zoom chain_{chain_id}, 5",
        "",
        "# Set view",
        "set cartoon_smooth_loops, 0",
        "set cartoon_loop_radius, 0.3",
        "set antialias, 2",
        "set ray_shadows, 0",
        "",
        "# Render",
        f"ray 800, 600",
        f"png {output_png}, dpi=150",
        "",
        "# Quit",
        "quit",
    ])

    return "\n".join(script_lines)


def render_structure(
    pdb_id: str,
    chain_id: str,
    domains: List[Dict],
    pdb_dir: str,
    output_dir: str,
) -> str:
    """Render structure with PyMOL and return path to PNG."""
    pdb_lower = pdb_id.lower()
    middle_chars = pdb_lower[1:3]
    pdb_file = Path(pdb_dir) / middle_chars / f"{pdb_lower}.cif.gz"

    if not pdb_file.exists():
        print(f"  WARNING: PDB file not found: {pdb_file}")
        return None

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    output_png = output_path / f"{pdb_id}_{chain_id}.png"
    script_path = output_path / f"{pdb_id}_{chain_id}.pml"

    script_content = generate_pymol_script(
        pdb_id, chain_id, domains, str(pdb_file), str(output_png)
    )

    with open(script_path, "w") as f:
        f.write(script_content)

    try:
        result = subprocess.run(
            ["pymol", "-c", "-q", str(script_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            print(f"  ERROR: PyMOL failed for {pdb_id}_{chain_id}")
            return None

        if not output_png.exists():
            print(f"  ERROR: PNG not created for {pdb_id}_{chain_id}")
            return None

        return str(output_png)

    except Exception as e:
        print(f"  ERROR: Failed to render {pdb_id}_{chain_id}: {e}")
        return None


def create_montage(image_paths: List[str], output_path: str, title: str = ""):
    """Create 5x4 montage of images using ImageMagick."""
    if not image_paths:
        print("  No images to montage")
        return

    image_paths = image_paths[:20]

    cmd = [
        "montage",
        *image_paths,
        "-tile", "5x4",
        "-geometry", "400x300+10+10",
        "-background", "white",
        "-bordercolor", "gray",
        "-border", "2",
    ]

    if title:
        cmd.extend(["-title", title, "-pointsize", "24"])

    cmd.append(output_path)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            print(f"  ERROR: Montage creation failed: {result.stderr}")
        else:
            print(f"  ✓ Created montage: {output_path}")

    except Exception as e:
        print(f"  ERROR: Failed to create montage: {e}")


def main():
    """Main rendering workflow."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Render 70% representatives sorted by classification quality"
    )
    parser.add_argument(
        "batch_dir",
        help="Path to batch directory (containing batch_manifest.yaml and partitions/)",
    )
    parser.add_argument(
        "--pdb-dir",
        default="/usr2/pdb/data/structures/divided/mmCIF",
        help="Path to PDB mmCIF directory",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory for renders (default: batch_dir/renders_sorted)",
    )
    parser.add_argument(
        "--max-per-category",
        type=int,
        default=20,
        help="Maximum chains to render per category",
    )

    args = parser.parse_args()

    batch_dir = Path(args.batch_dir)
    pdb_dir = args.pdb_dir
    output_dir = args.output_dir or (batch_dir / "renders_sorted")

    print(f"Batch directory: {batch_dir}")
    print(f"PDB directory: {pdb_dir}")
    print(f"Output directory: {output_dir}")
    print()

    # Check PyMOL availability
    try:
        result = subprocess.run(
            ["pymol", "-c", "-q"],
            input="quit\n",
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            print("ERROR: PyMOL not found or not working")
            return 1
    except Exception as e:
        print(f"ERROR: PyMOL not available: {e}")
        return 1

    # Check ImageMagick availability
    try:
        result = subprocess.run(
            ["montage", "-version"], capture_output=True, timeout=5
        )
        create_montages = (result.returncode == 0)
    except Exception:
        print("WARNING: ImageMagick not available - montages will be skipped")
        create_montages = False

    print()

    # Load manifest
    manifest = BatchManifest(str(batch_dir))

    # Get all partition files
    partition_dir = batch_dir / "partitions"
    if not partition_dir.exists():
        print(f"ERROR: Partition directory not found: {partition_dir}")
        return 1

    partition_files = sorted(partition_dir.glob("*.partition.xml"))
    print(f"Found {len(partition_files)} partition files")

    # Categorize chains
    categories = {
        "A": [],  # Fully classified (>= 90%)
        "B": [],  # Partially classified (50-90%)
        "C": [],  # Unclassified (< 50%)
        "D": [],  # Unclassified + low complexity
    }

    print("\nCategorizing chains (filtering to 70% representatives)...")

    for partition_file in partition_files:
        partition_data = parse_partition_xml(str(partition_file))
        pdb_id = partition_data["pdb_id"]
        chain_id = partition_data["chain_id"]
        chain_key = f"{pdb_id}_{chain_id}"

        # Filter to representatives only
        if not is_representative(chain_key, manifest.data):
            continue

        category = categorize_chain(partition_data)

        categories[category].append({
            "partition_file": partition_file,
            "partition_data": partition_data,
            "coverage": partition_data["coverage"],
        })

    # Print category summary
    print("\nCategory Summary:")
    print(f"  A) Fully classified (≥90%):        {len(categories['A'])} chains")
    print(f"  B) Partially classified (50-90%):  {len(categories['B'])} chains")
    print(f"  C) Unclassified (<50%):            {len(categories['C'])} chains")
    print(f"  D) Unclassified + low complexity:  {len(categories['D'])} chains")
    print(f"  Total representatives:             {sum(len(v) for v in categories.values())} chains")
    print()

    # Sort within each category by coverage (descending)
    for cat in categories:
        categories[cat].sort(key=lambda x: x["coverage"], reverse=True)

    # Render chains by category
    category_names = {
        "A": "Fully Classified (≥90%)",
        "B": "Partially Classified (50-90%)",
        "C": "Unclassified (<50%)",
        "D": "Unclassified + Low Complexity",
    }

    all_rendered = {}

    for cat in ["A", "B", "C", "D"]:
        if not categories[cat]:
            continue

        print(f"\n{'='*70}")
        print(f"CATEGORY {cat}: {category_names[cat]}")
        print(f"{'='*70}")
        print(f"Rendering up to {args.max_per_category} structures...")
        print()

        rendered_images = []
        chains_to_render = categories[cat][:args.max_per_category]

        for i, chain_info in enumerate(chains_to_render, 1):
            partition_data = chain_info["partition_data"]
            pdb_id = partition_data["pdb_id"]
            chain_id = partition_data["chain_id"]
            domains = partition_data["domains"]
            coverage = partition_data["coverage"]

            print(f"  [{i}/{len(chains_to_render)}] {pdb_id}_{chain_id}: "
                  f"{len(domains)} domains, {coverage:.1%} coverage")

            png_path = render_structure(
                pdb_id, chain_id, domains, pdb_dir, output_dir
            )

            if png_path:
                rendered_images.append(png_path)

        all_rendered[cat] = rendered_images
        print(f"\n  Rendered {len(rendered_images)}/{len(chains_to_render)} structures")

    # Create montages per category
    if create_montages:
        print(f"\n{'='*70}")
        print("Creating category montages...")
        print(f"{'='*70}")

        montage_dir = Path(output_dir) / "montages"
        montage_dir.mkdir(parents=True, exist_ok=True)

        for cat in ["A", "B", "C", "D"]:
            if not all_rendered.get(cat):
                continue

            images = all_rendered[cat]

            # Create montages in groups of 20
            for i in range(0, len(images), 20):
                group = images[i:i+20]
                group_num = (i // 20) + 1
                montage_path = montage_dir / f"category_{cat}_group_{group_num:02d}.png"

                title = f"Category {cat}: {category_names[cat]} (Group {group_num})"
                print(f"\n  Creating montage: {montage_path.name}")
                print(f"    {len(group)} structures")

                create_montage(group, str(montage_path), title=title)

        print(f"\nMontages saved to: {montage_dir}")

    # Summary
    print(f"\n{'='*70}")
    print("RENDERING COMPLETE")
    print(f"{'='*70}")
    print(f"Individual renders: {output_dir}")
    if create_montages:
        print(f"Montages: {montage_dir}")

    print("\nCategory Results:")
    for cat in ["A", "B", "C", "D"]:
        count = len(all_rendered.get(cat, []))
        if count > 0:
            print(f"  {cat}) {category_names[cat]}: {count} rendered")

    return 0


if __name__ == "__main__":
    sys.exit(main())
