#!/usr/bin/env python3
"""
Check that PDB domain ranges are seqid ranges (positions in the chain's construct sequence).

QC gate after auto-accession; exits 1 on any failure. See validation/seqid_ranges.py for
the classes. query_not_construct means the batch searched and partitioned the chain
against something other than its construct sequence (the modeled-residue bug): every
range on that chain is suspect, not only the ones that fail structurally.

Parses each entry's mmCIF once: a quarterly batch (~2,200 entries) takes a while on one
core. Split it with --shard/--nshards, e.g. under SLURM:

    sbatch --array=0-15 --wrap 'python scripts/seqid_ranges.py --uid-range LO-HI \
        --shard $SLURM_ARRAY_TASK_ID --nshards 16 --list fail_$SLURM_ARRAY_TASK_ID.tsv'

Usage:
    python scripts/seqid_ranges.py --uid-range 5347772-5352817 --list failing.tsv
    python scripts/seqid_ranges.py --domain-version 'pyecod_prod_ecod_q4_2026%'
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import psycopg2

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.validation.seqid_ranges import FAIL_CLASSES, check_seqid_ranges

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB = dict(host="dione", port=45000, database="ecod_protein", user="ecod",
          password=os.environ.get("PGPASSWORD"))


def main():
    ap = argparse.ArgumentParser(description="Check PDB domain ranges are seqid ranges")
    ap.add_argument("--uid-range", help="ecod_uid LO-HI (a batch's accessioned domains)")
    ap.add_argument("--domain-version", help="domains.domain_version LIKE PATTERN")
    ap.add_argument("--shard", type=int, default=0, help="this shard (by entry)")
    ap.add_argument("--nshards", type=int, default=1, help="number of shards")
    ap.add_argument("--list", help="write failing domains to this TSV")
    args = ap.parse_args()

    select = dict(
        uid_range=tuple(int(x) for x in args.uid_range.split("-")) if args.uid_range else None,
        domain_version=args.domain_version)
    if not any(select.values()):
        ap.error("give --uid-range and/or --domain-version")

    conn = psycopg2.connect(**DB)
    try:
        counts, fails = check_seqid_ranges(conn, shard=args.shard, nshards=args.nshards, **select)
    finally:
        conn.close()
    for k, v in counts.items():
        logger.info(f"  {k:<20}{v:>9,}{'   FAIL' if v and k in FAIL_CLASSES else ''}")
    if args.list:
        with open(args.list, "w") as out:
            out.write("domain_pk\tdomain_id\tecod_uid\tpdb_id\tchain_id\trange\tissue\n")
            for row in fails:
                out.write("\t".join(str(x) for x in row) + "\n")
        logger.info(f"Failing domains written to {args.list}")
    if fails:
        logger.error(f"QC FAILED: {len(fails):,} domains have ranges that are not seqid ranges")
        sys.exit(1)
    logger.info("QC passed")


if __name__ == "__main__":
    main()
