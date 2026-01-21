#!/usr/bin/env python3
"""
Parse Pfam hmmscan results and generate F-group assignments.

This script:
1. Parses domtblout files from Pfam hmmscan
2. Extracts best hits per domain (top-scoring Pfam family)
3. Maps Pfam accessions to existing ECOD F-groups
4. Classifies domains into tracks:
   - Track 1: Existing F-group match
   - Track 2a: New F-group needed (single Pfam)
   - Track 2b: Composite Pfam (multiple families)
   - Track 3: No Pfam hit

Usage:
    # Parse results and generate assignments
    python scripts/parse_pfam_results.py \
        --batch-dir /data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026

    # With specific output file
    python scripts/parse_pfam_results.py \
        --batch-dir /data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026 \
        --output domain_pfam_assignments.tsv
"""

import sys
import os
import argparse
import logging
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple

import psycopg2

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database connection parameters
DEFAULT_CONNECTION_PARAMS = {
    'host': os.environ.get('ECOD_DB_HOST', 'dione'),
    'port': int(os.environ.get('ECOD_DB_PORT', '45000')),
    'user': os.environ.get('ECOD_DB_USER', 'ecod'),
    'password': os.environ.get('ECOD_DB_PASSWORD', ''),
    'dbname': os.environ.get('ECOD_DB_NAME', 'ecod_protein'),
}


def get_connection(connection_params: Dict = None):
    """Get database connection."""
    params = connection_params or DEFAULT_CONNECTION_PARAMS
    return psycopg2.connect(**params)


@dataclass
class PfamHit:
    """A single Pfam domain hit from hmmscan."""
    pfam_acc: str       # PF00001
    pfam_name: str      # 7tm_1
    evalue: float       # Domain-level E-value
    score: float        # Bit score
    ali_from: int       # Alignment start on query
    ali_to: int         # Alignment end on query
    env_from: int       # Envelope start on query
    env_to: int         # Envelope end on query


@dataclass
class DomainPfamResult:
    """Pfam results for a single ECOD domain."""
    domain_id: str
    ecod_uid: int
    domain_version: str
    sequence_length: int
    hits: List[PfamHit] = field(default_factory=list)

    @property
    def best_hit(self) -> Optional[PfamHit]:
        """Best hit by bit score."""
        if not self.hits:
            return None
        return max(self.hits, key=lambda h: h.score)

    @property
    def coverage(self) -> float:
        """Fraction of sequence covered by all hits."""
        if not self.hits or self.sequence_length == 0:
            return 0.0
        covered = set()
        for hit in self.hits:
            covered.update(range(hit.env_from, hit.env_to + 1))
        return len(covered) / self.sequence_length

    @property
    def track(self) -> str:
        """Classify into processing track."""
        if not self.hits:
            return "track3_no_pfam"

        # Check for multiple non-overlapping hits
        non_overlapping = self._get_non_overlapping_hits()
        if len(non_overlapping) > 1:
            return "track2b_composite"

        return "track1_or_2a"  # Single Pfam - need to check F-group existence

    def _get_non_overlapping_hits(self, overlap_threshold: int = 20) -> List[PfamHit]:
        """Get hits that don't overlap significantly."""
        if not self.hits:
            return []

        # Sort by score (best first)
        sorted_hits = sorted(self.hits, key=lambda h: -h.score)
        selected = []

        for hit in sorted_hits:
            overlaps = False
            for existing in selected:
                overlap = self._calc_overlap(hit, existing)
                if overlap > overlap_threshold:
                    overlaps = True
                    break
            if not overlaps:
                selected.append(hit)

        return selected

    def _calc_overlap(self, h1: PfamHit, h2: PfamHit) -> int:
        """Calculate overlap between two hits."""
        start = max(h1.env_from, h2.env_from)
        end = min(h1.env_to, h2.env_to)
        return max(0, end - start + 1)


def parse_domtblout(filepath: Path) -> Dict[str, DomainPfamResult]:
    """
    Parse hmmscan domtblout file.

    Returns dict mapping domain_id -> DomainPfamResult
    """
    results = {}

    with open(filepath, 'r') as f:
        for line in f:
            if line.startswith('#'):
                continue

            fields = line.split()
            if len(fields) < 22:
                continue

            # domtblout format (selected columns):
            # 0: target_name (Pfam name)
            # 1: target_accession (PF00001.21)
            # 2: tlen (target length)
            # 3: query_name (domain_id|ecod_uid|domain_version)
            # 4: query_accession (-)
            # 5: qlen (query length)
            # 6: full_E-value
            # 7: full_score
            # 8: full_bias
            # 9: #domains
            # 10: of (total domains)
            # 11: c-Evalue (conditional E-value)
            # 12: i-Evalue (independent E-value)
            # 13: dom_score
            # 14: dom_bias
            # 15: hmm_from
            # 16: hmm_to
            # 17: ali_from
            # 18: ali_to
            # 19: env_from
            # 20: env_to
            # 21: acc

            pfam_name = fields[0]
            pfam_acc = fields[1].split('.')[0]  # Remove version: PF00001.21 -> PF00001
            query_parts = fields[3].split('|')

            if len(query_parts) < 3:
                logger.warning(f"Unexpected query format: {fields[3]}")
                continue

            domain_id = query_parts[0]
            ecod_uid = int(query_parts[1])
            domain_version = query_parts[2]
            seq_length = int(fields[5])

            evalue = float(fields[12])
            score = float(fields[13])
            ali_from = int(fields[17])
            ali_to = int(fields[18])
            env_from = int(fields[19])
            env_to = int(fields[20])

            # Create or get result
            if domain_id not in results:
                results[domain_id] = DomainPfamResult(
                    domain_id=domain_id,
                    ecod_uid=ecod_uid,
                    domain_version=domain_version,
                    sequence_length=seq_length
                )

            # Add hit
            hit = PfamHit(
                pfam_acc=pfam_acc,
                pfam_name=pfam_name,
                evalue=evalue,
                score=score,
                ali_from=ali_from,
                ali_to=ali_to,
                env_from=env_from,
                env_to=env_to
            )
            results[domain_id].hits.append(hit)

    return results


def get_pfam_to_fgroup_mapping(conn) -> Dict[str, int]:
    """
    Get mapping from Pfam accession to existing ECOD F-group ID.

    Returns dict mapping pfam_acc -> f_group_id
    """
    cursor = conn.cursor()

    # Query ecod_rep.cluster for F-groups with Pfam annotations
    cursor.execute("""
        SELECT pfam_acc, id
        FROM ecod_rep.cluster
        WHERE type = 'F'
        AND pfam_acc IS NOT NULL
        AND pfam_acc != ''
    """)

    mapping = {}
    for pfam_acc, f_group_id in cursor:
        # Handle potential multi-Pfam entries
        for acc in pfam_acc.split(','):
            acc = acc.strip()
            if acc and acc.startswith('PF'):
                mapping[acc] = f_group_id

    cursor.close()
    logger.info(f"Loaded {len(mapping)} Pfam -> F-group mappings")
    return mapping


def get_domain_db_ids(conn, domain_version_pattern: str) -> Dict[str, int]:
    """Get mapping from domain_id -> database ID."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT domain_id, id
        FROM ecod_commons.domains
        WHERE domain_version LIKE %s
    """, (domain_version_pattern,))

    mapping = {}
    for domain_id, db_id in cursor:
        mapping[domain_id] = db_id

    cursor.close()
    return mapping


def classify_domains(
    results: Dict[str, DomainPfamResult],
    pfam_to_fgroup: Dict[str, int],
    domain_db_ids: Dict[str, int]
) -> Dict[str, List[Dict]]:
    """
    Classify domains into processing tracks.

    Returns dict with keys: track1, track2a, track2b, track3
    """
    classified = {
        'track1': [],      # Existing F-group match
        'track2a': [],     # New F-group needed
        'track2b': [],     # Composite Pfam
        'track3': []       # No Pfam hit
    }

    for domain_id, result in results.items():
        db_id = domain_db_ids.get(domain_id)
        if not db_id:
            logger.warning(f"Domain {domain_id} not found in database")
            continue

        best_hit = result.best_hit
        track = result.track

        entry = {
            'domain_id': domain_id,
            'ecod_uid': result.ecod_uid,
            'domain_version': result.domain_version,
            'db_id': db_id,
            'sequence_length': result.sequence_length,
            'coverage': result.coverage,
            'best_pfam_acc': best_hit.pfam_acc if best_hit else None,
            'best_pfam_name': best_hit.pfam_name if best_hit else None,
            'best_score': best_hit.score if best_hit else None,
            'best_evalue': best_hit.evalue if best_hit else None,
            'num_hits': len(result.hits)
        }

        if track == "track3_no_pfam":
            classified['track3'].append(entry)
        elif track == "track2b_composite":
            # Add info about all non-overlapping hits
            entry['all_pfam'] = [
                {'acc': h.pfam_acc, 'name': h.pfam_name, 'score': h.score}
                for h in result._get_non_overlapping_hits()
            ]
            classified['track2b'].append(entry)
        else:
            # Track 1 or 2a - check if Pfam maps to existing F-group
            if best_hit and best_hit.pfam_acc in pfam_to_fgroup:
                entry['f_group_id'] = pfam_to_fgroup[best_hit.pfam_acc]
                classified['track1'].append(entry)
            else:
                classified['track2a'].append(entry)

    return classified


def write_assignments(
    classified: Dict[str, List[Dict]],
    output_path: Path
) -> None:
    """Write domain assignments to TSV file."""
    with open(output_path, 'w') as f:
        # Header
        f.write("domain_id\tecod_uid\tdomain_version\ttrack\tpfam_acc\tpfam_name\t")
        f.write("score\tevalue\tf_group_id\tnum_hits\tcoverage\n")

        for track, entries in classified.items():
            for entry in entries:
                f.write(f"{entry['domain_id']}\t")
                f.write(f"{entry['ecod_uid']}\t")
                f.write(f"{entry['domain_version']}\t")
                f.write(f"{track}\t")
                f.write(f"{entry.get('best_pfam_acc', '')}\t")
                f.write(f"{entry.get('best_pfam_name', '')}\t")
                f.write(f"{entry.get('best_score', '')}\t")
                f.write(f"{entry.get('best_evalue', '')}\t")
                f.write(f"{entry.get('f_group_id', '')}\t")
                f.write(f"{entry.get('num_hits', 0)}\t")
                f.write(f"{entry.get('coverage', 0):.4f}\n")


def write_report(
    classified: Dict[str, List[Dict]],
    output_path: Path
) -> None:
    """Write JSON summary report."""
    report = {
        'timestamp': datetime.now().isoformat(),
        'summary': {
            'track1_existing_fgroup': len(classified['track1']),
            'track2a_new_fgroup': len(classified['track2a']),
            'track2b_composite': len(classified['track2b']),
            'track3_no_pfam': len(classified['track3']),
            'total': sum(len(v) for v in classified.values())
        },
        'track2a_pfam_families': {},
        'track2b_samples': []
    }

    # Count unique Pfam families needing new F-groups
    pfam_counts = defaultdict(int)
    for entry in classified['track2a']:
        pfam = entry.get('best_pfam_acc')
        if pfam:
            pfam_counts[pfam] += 1
    report['track2a_pfam_families'] = dict(sorted(pfam_counts.items(), key=lambda x: -x[1]))
    report['track2a_unique_pfam'] = len(pfam_counts)

    # Sample of composite Pfam domains
    for entry in classified['track2b'][:10]:
        report['track2b_samples'].append({
            'domain_id': entry['domain_id'],
            'pfam_families': entry.get('all_pfam', [])
        })

    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Parse Pfam hmmscan results and classify domains"
    )
    parser.add_argument(
        "--batch-dir", type=Path,
        default=Path("/data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026"),
        help="Batch directory with Pfam results"
    )
    parser.add_argument(
        "--domain-version-pattern", default="pyecod_prod_ecod_q4_2025_q1_2026%",
        help="Domain version pattern (LIKE syntax)"
    )
    parser.add_argument(
        "--output", type=str, default="domain_pfam_assignments.tsv",
        help="Output TSV file name"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Pfam Results Parser")
    logger.info("=" * 60)
    logger.info(f"Batch directory: {args.batch_dir}")
    logger.info(f"Domain version pattern: {args.domain_version_pattern}")
    logger.info("=" * 60)

    # Find domtblout files
    pfam_dir = args.batch_dir / "pfam"
    domtblout_files = sorted(pfam_dir.glob("hmmscan_*.domtblout"))

    if not domtblout_files:
        logger.error(f"No domtblout files found in {pfam_dir}")
        return 1

    logger.info(f"Found {len(domtblout_files)} domtblout files")

    # Parse all results
    all_results = {}
    for filepath in domtblout_files:
        logger.info(f"Parsing {filepath.name}...")
        results = parse_domtblout(filepath)
        all_results.update(results)

    logger.info(f"Parsed {len(all_results)} domains with Pfam hits")

    # Connect to database
    logger.info("Connecting to database...")
    conn = get_connection()

    # Get Pfam -> F-group mapping
    pfam_to_fgroup = get_pfam_to_fgroup_mapping(conn)

    # Get domain database IDs
    domain_db_ids = get_domain_db_ids(conn, args.domain_version_pattern)
    logger.info(f"Loaded {len(domain_db_ids)} domain database IDs")

    conn.close()

    # Classify domains
    logger.info("Classifying domains into tracks...")
    classified = classify_domains(all_results, pfam_to_fgroup, domain_db_ids)

    # Add track 3 entries for domains without any Pfam hits
    # (domains not in all_results)
    domains_with_hits = set(all_results.keys())
    for domain_id, db_id in domain_db_ids.items():
        if domain_id not in domains_with_hits:
            classified['track3'].append({
                'domain_id': domain_id,
                'db_id': db_id,
                'ecod_uid': 0,  # Would need to fetch
                'domain_version': '',
                'sequence_length': 0,
                'coverage': 0,
                'num_hits': 0
            })

    # Write outputs
    output_tsv = args.batch_dir / "pfam" / args.output
    output_json = args.batch_dir / "pfam" / "pfam_classification_report.json"

    logger.info(f"Writing assignments to {output_tsv}...")
    write_assignments(classified, output_tsv)

    logger.info(f"Writing report to {output_json}...")
    write_report(classified, output_json)

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Classification Summary")
    logger.info("=" * 60)
    logger.info(f"Track 1 (existing F-group): {len(classified['track1'])}")
    logger.info(f"Track 2a (new F-group needed): {len(classified['track2a'])}")
    logger.info(f"Track 2b (composite Pfam): {len(classified['track2b'])}")
    logger.info(f"Track 3 (no Pfam hit): {len(classified['track3'])}")
    logger.info(f"Total: {sum(len(v) for v in classified.values())}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
