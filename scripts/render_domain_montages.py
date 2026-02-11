#!/usr/bin/env python3
"""
Render protein chains with colored domains using PyMOL and create montages.

This script:
1. Reads partition XML files to get domain assignments
2. Generates PyMOL scripts to render each chain with colored domains
3. Creates montages of 20 structures at a time (5x4 grid)
"""

import os
import sys
import xml.etree.ElementTree as ET
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple

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
    Parse partition XML to extract domain information.

    Returns:
        dict with keys: pdb_id, chain_id, domains (list of dicts with id, range, family)
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    pdb_id = root.get("pdb_id")
    chain_id = root.get("chain_id")

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
        "domains": domains,
    }


def parse_range(range_str: str) -> List[Tuple[int, int]]:
    """
    Parse domain range string into list of (start, end) tuples.

    Example: "1-110,150-200" -> [(1, 110), (150, 200)]
    """
    segments = []
    for segment in range_str.split(","):
        start, end = map(int, segment.split("-"))
        segments.append((start, end))
    return segments


def get_pdb_residue_mapping(pdb_file: str, chain_id: str) -> Dict[int, str]:
    """
    Extract sequence position to PDB residue number mapping from mmCIF file.

    Args:
        pdb_file: Path to mmCIF file (can be gzipped)
        chain_id: Chain identifier

    Returns:
        Dict mapping sequence position (1-indexed) to PDB residue number (as string)
        Example: {1: "1", 2: "2", ..., 50: "50A", ...}
    """
    import gzip

    mapping = {}

    try:
        # Open file (handle gzip)
        if pdb_file.endswith(".gz"):
            f = gzip.open(pdb_file, "rt")
        else:
            f = open(pdb_file, "r")

        in_atom_site = False
        seq_pos = 0

        for line in f:
            # Find _atom_site loop
            if line.startswith("_atom_site."):
                in_atom_site = True
                continue

            if in_atom_site:
                # Stop at next loop or data block
                if line.startswith("_") or line.startswith("#"):
                    break

                # Parse ATOM/HETATM lines
                parts = line.split()
                if len(parts) < 20:
                    continue

                # mmCIF atom_site columns (approximate - varies by file)
                # Typical: group_PDB type_symbol atom_id comp_id asym_id seq_id ... auth_asym_id auth_seq_id ...
                # We need: label_asym_id (chain), label_seq_id, auth_seq_id

                try:
                    # mmCIF ATOM record columns (after split):
                    # parts[3] = label_atom_id (atom name, e.g., "CA")
                    # parts[6] = label_asym_id (label chain)
                    # parts[8] = label_seq_id (sequence position, 1-indexed)
                    # parts[16] = auth_seq_id (PDB residue number)
                    # parts[18] = auth_asym_id (author chain ID, e.g., "A", "B")

                    atom_name = parts[3] if len(parts) > 3 else None
                    label_seq = parts[8] if len(parts) > 8 else None
                    auth_seq = parts[16] if len(parts) > 16 else None
                    auth_chain = parts[18] if len(parts) > 18 else None

                    # Only process CA atoms for our chain (use auth_asym_id)
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
    """
    Map sequence range to PDB residue range.

    Args:
        seq_range: (start, end) in sequence numbering (1-indexed)
        seq_to_pdb: Mapping from sequence position to PDB residue number

    Returns:
        PDB residue range string, e.g., "10-50" or "10A-50B"
        If mapping unavailable, returns sequence range as fallback
    """
    start_seq, end_seq = seq_range

    if not seq_to_pdb:
        # No mapping available - use sequence numbers as fallback
        return f"{start_seq}-{end_seq}"

    # Map start and end positions
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
    """
    Generate PyMOL script to render chain with colored domains.

    Returns:
        PyMOL script as string
    """
    # Get PDB residue mapping (sequence position -> PDB residue number)
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
        # No domains - color gray
        script_lines.extend([
            f"color gray80, chain_{chain_id}",
        ])
    else:
        # Color each domain
        for i, domain in enumerate(domains):
            color = DOMAIN_COLORS[i % len(DOMAIN_COLORS)]
            range_str = domain["range"]
            family = domain["family"]

            # Parse range and create selections
            segments = parse_range(range_str)
            for seg_idx, (start, end) in enumerate(segments):
                # Convert sequence range to PDB residue range
                pdb_range = map_seq_range_to_pdb((start, end), seq_to_pdb)

                sel_name = f"domain_{i+1}_seg_{seg_idx+1}"
                script_lines.append(
                    f"select {sel_name}, chain {chain_id} and resi {pdb_range}"
                )
                script_lines.append(f"color {color}, {sel_name}")

            # Add comment about domain (showing both sequence and PDB ranges)
            script_lines.append(f"# Domain {i+1}: {family} (sequence: {range_str})")

        script_lines.append("")

    # Center and orient
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
    """
    Render structure with PyMOL and return path to PNG.

    Returns:
        Path to rendered PNG file, or None if failed
    """
    # Find PDB file
    pdb_lower = pdb_id.lower()
    middle_chars = pdb_lower[1:3]
    pdb_file = Path(pdb_dir) / middle_chars / f"{pdb_lower}.cif.gz"

    if not pdb_file.exists():
        print(f"  WARNING: PDB file not found: {pdb_file}")
        return None

    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Output PNG
    output_png = output_path / f"{pdb_id}_{chain_id}.png"

    # Generate PyMOL script
    script_path = output_path / f"{pdb_id}_{chain_id}.pml"
    script_content = generate_pymol_script(
        pdb_id, chain_id, domains, str(pdb_file), str(output_png)
    )

    with open(script_path, "w") as f:
        f.write(script_content)

    # Run PyMOL
    try:
        result = subprocess.run(
            ["pymol", "-c", "-q", str(script_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            print(f"  ERROR: PyMOL failed for {pdb_id}_{chain_id}")
            print(f"    {result.stderr}")
            return None

        if not output_png.exists():
            print(f"  ERROR: PNG not created for {pdb_id}_{chain_id}")
            return None

        return str(output_png)

    except subprocess.TimeoutExpired:
        print(f"  ERROR: PyMOL timeout for {pdb_id}_{chain_id}")
        return None
    except Exception as e:
        print(f"  ERROR: Failed to render {pdb_id}_{chain_id}: {e}")
        return None


def create_montage(image_paths: List[str], output_path: str, title: str = ""):
    """
    Create 5x4 montage of images using ImageMagick.

    Args:
        image_paths: List of paths to PNG files (up to 20)
        output_path: Output path for montage
        title: Optional title for montage
    """
    if not image_paths:
        print("  No images to montage")
        return

    # Ensure we have at most 20 images
    image_paths = image_paths[:20]

    # Build montage command
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
            print(f"  ERROR: Montage creation failed")
            print(f"    {result.stderr}")
        else:
            print(f"  Created montage: {output_path}")

    except Exception as e:
        print(f"  ERROR: Failed to create montage: {e}")


def main():
    """Main rendering workflow."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Render protein chains with colored domains"
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
        help="Output directory for renders (default: batch_dir/renders)",
    )
    parser.add_argument(
        "--max-chains",
        type=int,
        help="Maximum number of chains to render (for testing)",
    )

    args = parser.parse_args()

    batch_dir = Path(args.batch_dir)
    pdb_dir = args.pdb_dir
    output_dir = args.output_dir or (batch_dir / "renders")

    print(f"Batch directory: {batch_dir}")
    print(f"PDB directory: {pdb_dir}")
    print(f"Output directory: {output_dir}")
    print()

    # Check PyMOL availability (command-line mode for headless environments)
    try:
        result = subprocess.run(
            ["pymol", "-c", "-q"],
            input="quit\n",
            capture_output=True,
            text=True,
            timeout=30
        )
        # PyMOL exits cleanly with code 0 when given 'quit' command
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
        if result.returncode != 0:
            print("WARNING: ImageMagick montage not found - montages will be skipped")
            create_montages = False
        else:
            create_montages = True
    except Exception:
        print("WARNING: ImageMagick not available - montages will be skipped")
        create_montages = False

    print()

    # Load manifest
    manifest = BatchManifest(str(batch_dir))

    # Get all chains with partitions
    partition_dir = batch_dir / "partitions"
    if not partition_dir.exists():
        print(f"ERROR: Partition directory not found: {partition_dir}")
        return 1

    partition_files = sorted(partition_dir.glob("*.partition.xml"))

    if args.max_chains:
        partition_files = partition_files[:args.max_chains]

    print(f"Found {len(partition_files)} partition files")
    print()

    # Render each structure
    rendered_images = []

    for i, partition_file in enumerate(partition_files, 1):
        print(f"[{i}/{len(partition_files)}] Rendering {partition_file.name}...")

        # Parse partition
        partition_data = parse_partition_xml(str(partition_file))
        pdb_id = partition_data["pdb_id"]
        chain_id = partition_data["chain_id"]
        domains = partition_data["domains"]

        print(f"  {pdb_id}_{chain_id}: {len(domains)} domains")

        # Render
        png_path = render_structure(
            pdb_id, chain_id, domains, pdb_dir, output_dir
        )

        if png_path:
            rendered_images.append(png_path)
            print(f"  ✓ Rendered: {png_path}")

        print()

    print(f"\nRendered {len(rendered_images)}/{len(partition_files)} structures")

    # Create montages
    if create_montages and rendered_images:
        print(f"\nCreating montages (groups of 20, 5x4 grid)...")

        montage_dir = Path(output_dir) / "montages"
        montage_dir.mkdir(parents=True, exist_ok=True)

        # Group into sets of 20
        for i in range(0, len(rendered_images), 20):
            group = rendered_images[i:i+20]
            montage_num = (i // 20) + 1
            montage_path = montage_dir / f"montage_{montage_num:02d}.png"

            print(f"\nMontage {montage_num}: {len(group)} structures")
            create_montage(
                group,
                str(montage_path),
                title=f"Domain Partitions (Group {montage_num})"
            )

        print(f"\nMontages saved to: {montage_dir}")

    print(f"\n✓ Rendering complete!")
    print(f"  Individual renders: {output_dir}")
    if create_montages:
        print(f"  Montages: {montage_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
