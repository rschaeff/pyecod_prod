#!/usr/bin/env python3
"""
Non-circular validation of existing ECOD representative domains.

For each rep (e.g. one of the 456 v294 "movers"), this runs pyecod_mini with
``--exclude-self`` (and any caller-supplied exclude list) so the query cannot
trivially self-match its own reference entry, then reports whether the algorithm
re-derives the rep's current F-group from *independent* evidence.

For each query it reports one of:
  * ``supported``     - a re-derived domain maps to the current (commons) F-group
  * ``different``     - re-derived F-group(s) differ from the current one
  * ``unclassified``  - no domains survived (placement unsupported independently)

The re-derived F-group of each output domain is obtained by mapping the domain's
``reference_ecod_domain_id`` through the classification lookup
(see scripts/build_classification_lookup.py).

Input TSV (header required), one row per rep:
    domain_id   pdb_id  chain_id    old_f   commons_f   summary_xml [exclude_domains]

  - domain_id:        the rep ECOD domain id being validated (e.g. e1gcyA2)
  - pdb_id, chain_id: the query chain (used for self-exclusion + summary lookup)
  - old_f, commons_f: current F-group ids (commons_f is the target to confirm)
  - summary_xml:      path to the query's domain_summary.xml; if blank, derived
                      from --summaries-dir as {summaries_dir}/{pdb}_{chain}.summary.xml
  - exclude_domains:  optional ';'-separated reference domain ids to also mask
                      (e.g. the query's full F-group membership list)

Usage:
    python scripts/validate_reps_self_exclusion.py movers.tsv \
        --output movers_validation.tsv \
        --out-dir /tmp/mover_partitions \
        --reference develop291
"""

import argparse
import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

# Make src importable when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pyecod_prod.core.partition_runner import PartitionRunner  # noqa: E402
from pyecod_prod.utils.classification_lookup import (  # noqa: E402
    load_classification_lookup,
    load_classification_lookup_for_version,
)


def _read_input(path: str) -> List[dict]:
    rows = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            rows.append(row)
    return rows


def _summary_path(row: dict, summaries_dir: Optional[str]) -> Optional[str]:
    sp = (row.get("summary_xml") or "").strip()
    if sp:
        return sp
    if summaries_dir:
        pdb = row["pdb_id"].strip()
        chain = row["chain_id"].strip()
        return str(Path(summaries_dir) / f"{pdb}_{chain}.summary.xml")
    return None


def _rederived_fgroups(
    partition_xml: str, classification: Dict[str, Dict[str, str]]
) -> List[str]:
    """Map each output domain's reference_ecod_domain_id -> f_group."""
    fgroups = []
    try:
        root = ET.parse(partition_xml).getroot()
    except (ET.ParseError, FileNotFoundError):
        return fgroups
    for domain in root.findall(".//domain"):
        ref_id = domain.get("reference_ecod_domain_id")
        if not ref_id:
            continue
        groups = classification.get(ref_id) or {}
        f = groups.get("f_group")
        if f:
            fgroups.append(f)
    return fgroups


def _verdict(commons_f: str, rederived: List[str], n_domains: int) -> str:
    if n_domains == 0:
        return "unclassified"
    if commons_f and commons_f in rederived:
        return "supported"
    return "different"


def validate(
    rows: List[dict],
    classification: Dict[str, Dict[str, str]],
    out_dir: str,
    summaries_dir: Optional[str],
) -> List[dict]:
    runner = PartitionRunner()
    results = []

    for row in rows:
        domain_id = row["domain_id"].strip()
        pdb_id = row["pdb_id"].strip()
        chain_id = row["chain_id"].strip()
        commons_f = (row.get("commons_f") or "").strip()
        old_f = (row.get("old_f") or "").strip()

        summary_xml = _summary_path(row, summaries_dir)
        exclude_domains = [
            d.strip()
            for d in (row.get("exclude_domains") or "").split(";")
            if d.strip()
        ]

        record = {
            "domain_id": domain_id,
            "query": f"{pdb_id}_{chain_id}",
            "old_f": old_f,
            "commons_f": commons_f,
            "n_domains": 0,
            "rederived_f": "",
            "verdict": "error",
            "note": "",
        }

        if not summary_xml or not Path(summary_xml).exists():
            record["note"] = f"summary not found: {summary_xml}"
            results.append(record)
            continue

        try:
            result = runner.partition(
                summary_xml=summary_xml,
                output_dir=out_dir,
                batch_id="rep_self_exclusion",
                exclude_self=True,
                exclude_domain_ids=exclude_domains or None,
            )
        except Exception as e:  # noqa: BLE001
            record["note"] = f"partition error: {e}"
            results.append(record)
            continue

        rederived = _rederived_fgroups(result.partition_xml_path, classification)
        record["n_domains"] = result.domain_count
        record["rederived_f"] = ";".join(rederived)
        record["verdict"] = _verdict(commons_f, rederived, result.domain_count)
        results.append(record)

        print(
            f"{domain_id} ({pdb_id}_{chain_id}): {record['verdict']} "
            f"[{result.domain_count} dom, rederived={record['rederived_f'] or '-'}]"
        )

    return results


def _write_output(results: List[dict], output: str) -> None:
    fields = [
        "domain_id", "query", "old_f", "commons_f",
        "n_domains", "rederived_f", "verdict", "note",
    ]
    with open(output, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for r in results:
            writer.writerow(r)


def main():
    parser = argparse.ArgumentParser(
        description="Non-circular validation of existing ECOD reps via self-exclusion"
    )
    parser.add_argument("input_tsv", help="Movers input TSV (see module docstring)")
    parser.add_argument("--output", "-o", required=True, help="Output verdict TSV")
    parser.add_argument(
        "--out-dir", default="/tmp/rep_self_exclusion", help="Partition XML output dir"
    )
    parser.add_argument(
        "--summaries-dir",
        help="Directory of {pdb}_{chain}.summary.xml (used when a row has no summary_xml)",
    )
    parser.add_argument("--reference", default="develop291", help="ECOD reference version")
    parser.add_argument(
        "--classification-lookup",
        help="Path to domain_classification_lookup.tsv (default: derived from --reference)",
    )
    args = parser.parse_args()

    if args.classification_lookup:
        classification = load_classification_lookup(args.classification_lookup)
    else:
        classification = load_classification_lookup_for_version(args.reference)
    print(f"Loaded {len(classification):,} classification entries")

    rows = _read_input(args.input_tsv)
    print(f"Validating {len(rows)} reps...")

    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    results = validate(rows, classification, args.out_dir, args.summaries_dir)
    _write_output(results, args.output)

    # Summary tally
    tally: Dict[str, int] = {}
    for r in results:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    print("\n=== Verdict summary ===")
    for verdict in ("supported", "different", "unclassified", "error"):
        if verdict in tally:
            print(f"  {verdict}: {tally[verdict]}")
    print(f"Wrote {len(results)} rows to {args.output}")


if __name__ == "__main__":
    main()
