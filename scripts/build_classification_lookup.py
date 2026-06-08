#!/usr/bin/env python3
"""
Build domain → ECOD classification (x/h/t/f group ids) lookup from ECOD XML.

Reads ecod.developXXX.xml and writes a TSV mapping each ECOD domain id to its
X/H/T/F group ids, for use by SummaryGenerator (enables F-group / T-group
exclusion in pyecod_mini for non-circular validation of existing reps).

IMPORTANT — legacy XML naming oddity (since discarded):
  In the old ECOD XML the element named ``f_group`` is actually the **T-group**,
  and the element named ``pf_group`` (Pfam group) is actually the **F-group**.
  This script maps them to their true meaning:

    XML element / attr        true ECOD level     emitted column
    -----------------------   -----------------   --------------
    <x_group  x_id="1">       X-group             x_group
    <h_group  h_id="1.1">     H-group             h_group
    <f_group  f_id="1.1.1">   T-group             t_group
    <pf_group pf_id="1.1.1.1">F-group (family)    f_group

Domains directly under an <f_group> with no <pf_group> have no F-group (blank).

Usage:
    python scripts/build_classification_lookup.py \
        /data/ecod/database_versions/v291/ecod.develop291.xml \
        /data/ecod/database_versions/v291/domain_classification_lookup.tsv
"""

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def build_classification_lookup(ecod_xml: str, output_tsv: str) -> None:
    """Parse ECOD XML and build domain → (x,h,t,f group) lookup.

    Args:
        ecod_xml: Path to ecod.developXXX.xml
        output_tsv: Path to output TSV file
    """
    print(f"Parsing {ecod_xml}...")

    tree = ET.parse(ecod_xml)
    root = tree.getroot()

    # domain_id -> (x_group, h_group, t_group, f_group)
    lookup: dict[str, tuple[str, str, str, str]] = {}
    domains_with_fgroup = 0

    for x_group in root.findall(".//x_group"):
        x_id = x_group.get("x_id", "")
        for h_group in x_group.findall("h_group"):
            h_id = h_group.get("h_id", "")
            for f_group in h_group.findall("f_group"):
                # NOTE: <f_group> is the T-group (legacy naming oddity)
                t_id = f_group.get("f_id", "")

                # Domains nested in a <pf_group> get a real F-group (pf_id)
                for pf_group in f_group.findall("pf_group"):
                    # NOTE: <pf_group> is the real F-group
                    f_id = pf_group.get("pf_id", "")
                    for domain in pf_group.findall(".//domain"):
                        dom_id = domain.get("ecod_domain_id")
                        if dom_id:
                            lookup[dom_id] = (x_id, h_id, t_id, f_id)
                            domains_with_fgroup += 1

                # Domains directly under <f_group> (no pf_group) have no F-group
                for domain in f_group.findall("domain"):
                    dom_id = domain.get("ecod_domain_id")
                    if dom_id and dom_id not in lookup:
                        lookup[dom_id] = (x_id, h_id, t_id, "")

    print(
        f"Mapped {len(lookup):,} domains "
        f"({domains_with_fgroup:,} with an F-group / pf_group)"
    )

    output_path = Path(output_tsv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_tsv, "w") as f:
        f.write("# ECOD Domain ID to X/H/T/F group classification lookup\n")
        f.write("# Generated from ECOD XML (f_group=T-group, pf_group=F-group)\n")
        f.write("ecod_domain_id\tx_group\th_group\tt_group\tf_group\n")
        for dom_id in sorted(lookup.keys()):
            x_id, h_id, t_id, f_id = lookup[dom_id]
            f.write(f"{dom_id}\t{x_id}\t{h_id}\t{t_id}\t{f_id}\n")

    print(f"Wrote {len(lookup):,} mappings to {output_tsv}")


def main():
    parser = argparse.ArgumentParser(
        description="Build domain → ECOD classification (x/h/t/f) lookup from ECOD XML"
    )
    parser.add_argument("ecod_xml", help="Path to ecod.developXXX.xml")
    parser.add_argument("output_tsv", help="Path to output TSV file")
    args = parser.parse_args()
    build_classification_lookup(args.ecod_xml, args.output_tsv)


if __name__ == "__main__":
    main()
