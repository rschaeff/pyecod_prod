#!/usr/bin/env python3
"""
Build domain → family name lookup from ECOD XML.

Reads ecod.developXXX.xml and generates a TSV lookup file mapping
ECOD domain IDs to family names.

Usage:
    python scripts/build_family_lookup.py \
        /data/ecod/database_versions/v291/ecod.develop291.xml \
        /data/ecod/database_versions/v291/domain_family_lookup.tsv
"""

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def build_family_lookup(ecod_xml: str, output_tsv: str):
    """
    Parse ECOD XML and build domain → family name lookup.

    Args:
        ecod_xml: Path to ecod.developXXX.xml
        output_tsv: Path to output TSV file
    """
    print(f"Parsing {ecod_xml}...")

    tree = ET.parse(ecod_xml)
    root = tree.getroot()

    lookup = {}
    f_group_count = 0
    domain_count = 0

    # Iterate through all f_groups (family groups)
    for f_group in root.findall(".//f_group"):
        f_id = f_group.get("f_id")
        family_name = f_group.get("name")

        if not family_name:
            print(f"Warning: f_group {f_id} has no name, skipping")
            continue

        f_group_count += 1

        # Find all domains under this f_group
        for domain in f_group.findall(".//domain"):
            ecod_domain_id = domain.get("ecod_domain_id")

            if ecod_domain_id:
                lookup[ecod_domain_id] = family_name
                domain_count += 1

    print(f"Found {f_group_count} families with {domain_count} domains")

    # Write TSV
    output_path = Path(output_tsv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_tsv, "w") as f:
        f.write("# ECOD Domain ID to Family Name Lookup\n")
        f.write("# Generated from ECOD XML\n")
        f.write("ecod_domain_id\tfamily_name\n")

        for domain_id in sorted(lookup.keys()):
            f.write(f"{domain_id}\t{lookup[domain_id]}\n")

    print(f"Wrote {len(lookup)} mappings to {output_tsv}")


def main():
    parser = argparse.ArgumentParser(
        description="Build domain → family name lookup from ECOD XML"
    )
    parser.add_argument(
        "ecod_xml",
        help="Path to ecod.developXXX.xml (e.g., /data/ecod/database_versions/v291/ecod.develop291.xml)"
    )
    parser.add_argument(
        "output_tsv",
        help="Path to output TSV file (e.g., /data/ecod/database_versions/v291/domain_family_lookup.tsv)"
    )

    args = parser.parse_args()

    build_family_lookup(args.ecod_xml, args.output_tsv)


if __name__ == "__main__":
    main()
