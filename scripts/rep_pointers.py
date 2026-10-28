#!/usr/bin/env python3
"""
Check or reset representative pointers (ecod_commons.domains.representative_domain_id).

Policy: a non-rep domain's rep must be in its own F-group (database/rep_pointers.py).

  check  QC gate; exits 1 if any selected domain in a real F-group has no pointer or one
         outside its F-group. Run after F-group assignment, before marking a batch done.
  reset  point the selected domains at their F-group's current rep. For any step that
         changes f_group_assignments after accession (resolve_fgroups, Pfam passes,
         curation). Dry run unless --commit.

X.H.T.0 domains (policy unresolved) and non-F-group values such as EPP accessions are
counted, never failed or changed.

Usage:
    python scripts/rep_pointers.py check --uid-range 5347772-5352817
    python scripts/rep_pointers.py check --assigned-by 'pfam39%' --list failing.tsv
    python scripts/rep_pointers.py reset --assigned-since 2026-10-28 [--commit]
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import psycopg2

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.database.rep_pointers import (
    FGroupRepResolver,
    check_rep_pointers,
    reset_rep_pointers,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB = dict(host="dione", port=45000, database="ecod_protein", user="ecod",
          password=os.environ.get("PGPASSWORD"))


def main():
    ap = argparse.ArgumentParser(description="Check or reset representative pointers")
    ap.add_argument("action", choices=["check", "reset"])
    ap.add_argument("--uid-range", help="ecod_uid LO-HI (a batch's accessioned domains)")
    ap.add_argument("--assigned-by", help="f_group_assignments.assigned_by LIKE PATTERN")
    ap.add_argument("--assigned-since", help="f_group_assignments.assignment_date >= DATE")
    ap.add_argument("--list", help="check: write failing domains to this TSV")
    ap.add_argument("--commit", action="store_true", help="reset: write (default dry run)")
    args = ap.parse_args()

    select = dict(
        uid_range=tuple(int(x) for x in args.uid_range.split("-")) if args.uid_range else None,
        assigned_by=args.assigned_by, assigned_since=args.assigned_since)
    if not any(select.values()):
        ap.error("give --uid-range, --assigned-by and/or --assigned-since")

    conn = psycopg2.connect(**DB)
    try:
        if args.action == "check":
            counts, fails = check_rep_pointers(conn, **select)
            for k, v in counts.items():
                flag = "   FAIL" if v and k in ("no_pointer", "cross_f", "cross_h") else ""
                logger.info(f"  {k:<11}{v:>9,}{flag}")
            if args.list:
                with open(args.list, "w") as out:
                    out.write("domain_pk\tdomain_id\tf_group\tpointer\tissue\n")
                    for row in fails:
                        out.write("\t".join("" if x is None else str(x) for x in row) + "\n")
                logger.info(f"Failing domains written to {args.list}")
            if fails:
                logger.error(f"QC FAILED: {len(fails):,} domains violate the same-F-group rep policy")
                sys.exit(1)
            logger.info("QC passed")
        else:
            resolver = FGroupRepResolver(lambda: psycopg2.connect(**DB))
            counts = reset_rep_pointers(conn, resolver, dry_run=not args.commit, **select)
            logger.info(f"{'COMMITTED' if args.commit else 'DRY RUN'}: {counts}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
