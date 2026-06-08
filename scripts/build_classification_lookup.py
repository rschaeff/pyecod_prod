#!/usr/bin/env python3
"""
Build domain → ECOD classification (x/h/t/f group ids) lookup.

Writes a TSV mapping each ECOD domain id to its X/H/T/F group ids, for use by
SummaryGenerator (enables F-group / T-group exclusion in pyecod_mini for
non-circular validation of existing reps).

Two input formats are supported (auto-detected by extension):

1. ECOD ``domains.txt`` (PREFERRED — the current/forward format). Columns are
   read from the header; the numeric ``f_id`` (e.g. ``1.1.1.3`` = X.H.T.F) gives
   all four levels directly, with correct modern naming:
       x_group = X            (1)
       h_group = X.H          (1.1)
       t_group = X.H.T        (1.1.1)
       f_group = X.H.T.F      (1.1.1.3)  -- only when f_id has 4 components

2. Legacy ``ecod.developXXX.xml`` (DEPRECATED — being phased out). The element
   named ``f_group`` is actually the T-group and ``pf_group`` the real F-group;
   this script maps them to their true meaning (see build_from_xml).

Usage:
    # domains.txt (preferred)
    python scripts/build_classification_lookup.py \
        /data/ecod/database_versions/v294/bulk_files/ecod.develop294.domains.txt \
        /data/ecod/database_versions/v294/domain_classification_lookup.tsv

    # legacy XML
    python scripts/build_classification_lookup.py \
        /data/ecod/database_versions/v291/ecod.develop291.xml \
        /data/ecod/database_versions/v291/domain_classification_lookup.tsv
"""

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Tuple


def _split_f_id(f_id: str) -> Tuple[str, str, str, str]:
    """Split a numeric ECOD f_id (X.H.T.F) into (x_group, h_group, t_group, f_group).

    Components beyond what is present are returned empty. f_group is only set when
    the id has 4 components.
    """
    parts = f_id.split(".") if f_id else []
    x_group = parts[0] if len(parts) >= 1 else ""
    h_group = ".".join(parts[:2]) if len(parts) >= 2 else ""
    t_group = ".".join(parts[:3]) if len(parts) >= 3 else ""
    f_group = f_id if len(parts) >= 4 else ""
    return x_group, h_group, t_group, f_group


def _write_lookup(lookup: Dict[str, Tuple[str, str, str, str]], output_tsv: str) -> None:
    """Write the domain → (x,h,t,f) lookup TSV."""
    output_path = Path(output_tsv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_tsv, "w") as f:
        f.write("# ECOD Domain ID to X/H/T/F group classification lookup\n")
        f.write("ecod_domain_id\tx_group\th_group\tt_group\tf_group\n")
        for dom_id in sorted(lookup.keys()):
            x_id, h_id, t_id, f_id = lookup[dom_id]
            f.write(f"{dom_id}\t{x_id}\t{h_id}\t{t_id}\t{f_id}\n")
    print(f"Wrote {len(lookup):,} mappings to {output_tsv}")


def build_from_domains_txt(domains_txt: str, output_tsv: str) -> None:
    """Build the classification lookup from an ECOD domains.txt file.

    Header is located by finding the line containing both ``ecod_domain_id`` and
    ``f_id``; column positions are read from it (robust to column reordering).
    """
    print(f"Parsing {domains_txt}...")

    lookup: Dict[str, Tuple[str, str, str, str]] = {}
    id_col = f_col = None

    with open(domains_txt) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue

            if id_col is None:
                # Look for the header row (uncommented, contains the field names)
                cols = line.lstrip("#").strip().split("\t")
                if "ecod_domain_id" in cols and "f_id" in cols:
                    id_col = cols.index("ecod_domain_id")
                    f_col = cols.index("f_id")
                continue

            if line.startswith("#"):
                continue

            fields = line.split("\t")
            if len(fields) <= max(id_col, f_col):
                continue

            dom_id = fields[id_col].strip()
            f_id = fields[f_col].strip()
            if not dom_id:
                continue

            lookup[dom_id] = _split_f_id(f_id)

    if id_col is None:
        raise ValueError(
            f"Could not find a header row with 'ecod_domain_id' and 'f_id' in {domains_txt}"
        )

    domains_with_fgroup = sum(1 for g in lookup.values() if g[3])
    print(
        f"Mapped {len(lookup):,} domains "
        f"({domains_with_fgroup:,} with a 4-level F-group)"
    )
    _write_lookup(lookup, output_tsv)


def build_from_xml(ecod_xml: str, output_tsv: str) -> None:
    """Parse legacy ECOD XML and build domain → (x,h,t,f group) lookup.

    DEPRECATED: the ecod.developXXX.xml format is being phased out; prefer
    build_from_domains_txt. Retained for older versions (e.g. v291) that only
    ship the XML. Handles the legacy naming oddity (f_group=T, pf_group=F).

    Args:
        ecod_xml: Path to ecod.developXXX.xml
        output_tsv: Path to output TSV file
    """
    print(f"Parsing {ecod_xml} (legacy XML format)...")

    tree = ET.parse(ecod_xml)
    root = tree.getroot()

    # domain_id -> (x_group, h_group, t_group, f_group)
    lookup: Dict[str, Tuple[str, str, str, str]] = {}
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
    _write_lookup(lookup, output_tsv)


def main():
    parser = argparse.ArgumentParser(
        description="Build domain → ECOD classification (x/h/t/f) lookup "
        "from an ECOD domains.txt (preferred) or legacy ecod.developXXX.xml"
    )
    parser.add_argument(
        "input", help="Path to ECOD domains.txt (preferred) or ecod.developXXX.xml"
    )
    parser.add_argument("output_tsv", help="Path to output TSV file")
    parser.add_argument(
        "--format",
        choices=["auto", "domains", "xml"],
        default="auto",
        help="Input format (default: auto-detect by extension)",
    )
    args = parser.parse_args()

    fmt = args.format
    if fmt == "auto":
        fmt = "xml" if args.input.lower().endswith(".xml") else "domains"

    if fmt == "xml":
        build_from_xml(args.input, args.output_tsv)
    else:
        build_from_domains_txt(args.input, args.output_tsv)


if __name__ == "__main__":
    main()
