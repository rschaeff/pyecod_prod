#!/usr/bin/env python3
"""
Analyze partition results from PDB backfill 2023-2025.

Generates summary statistics for:
- Representative chains (those that were partitioned)
- All chains (including cluster members that can inherit results)
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict, Counter
import psycopg2
from psycopg2.extras import RealDictCursor
import sys

# Database connection
DB_CONFIG = {
    "host": "dione",
    "port": 45000,
    "database": "ecod_protein",
    "user": "rschaeff",
}

BACKFILL_DIR = Path("/data/ecod/pdb_updates/backfill_2023_2025")
PARTITION_DIR = BACKFILL_DIR / "blast" / "partitions"


def assess_quality(domain_count, coverage):
    """
    Apply ECOD quality thresholds (from partition_runner.py).
    """
    if domain_count == 0:
        return "no_domains"

    if coverage >= 0.80:
        return "good"
    elif coverage >= 0.50:
        return "low_coverage"
    else:
        return "fragmentary"


def parse_partition_xml(xml_path):
    """
    Parse partition XML to extract coverage and domain count.

    Returns:
        dict: {
            'pdb_id': str,
            'chain_id': str,
            'coverage': float,
            'domain_count': int,
            'quality': str,
            'algorithm_version': str
        }
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Extract metadata
        pdb_id = root.get("pdb_id", "")
        chain_id = root.get("chain_id", "")

        # Get coverage from <coverage> element or attribute
        coverage_elem = root.find("coverage")
        if coverage_elem is not None:
            coverage = float(coverage_elem.text or 0.0)
        else:
            coverage = float(root.get("coverage", 0.0))

        # Count domains
        domains = root.findall(".//domain")
        domain_count = len(domains)

        # Get algorithm version
        version_elem = root.find("version")
        if version_elem is not None:
            algorithm_version = version_elem.get("algorithm", "unknown")
        else:
            algorithm_version = root.get("algorithm_version", "unknown")

        quality = assess_quality(domain_count, coverage)

        return {
            "pdb_id": pdb_id,
            "chain_id": chain_id,
            "coverage": coverage,
            "domain_count": domain_count,
            "quality": quality,
            "algorithm_version": algorithm_version,
        }

    except Exception as e:
        print(f"Error parsing {xml_path}: {e}", file=sys.stderr)
        return None


def get_clustering_stats(conn):
    """
    Query database for clustering statistics.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Get clustering run info
        cur.execute("""
            SELECT
                threshold,
                method,
                total_sequences,
                total_clusters,
                run_date
            FROM pdb_update.clustering_run
            ORDER BY run_date DESC
            LIMIT 1
        """)
        clustering_run = cur.fetchone()

        # Get representative counts by ECOD status
        cur.execute("""
            SELECT
                ecod_status,
                COUNT(*) as count
            FROM pdb_update.chain_status
            WHERE is_representative = TRUE
            GROUP BY ecod_status
            ORDER BY ecod_status
        """)
        rep_by_status = {row["ecod_status"]: row["count"] for row in cur.fetchall()}

        # Get cluster member counts by ECOD status
        cur.execute("""
            SELECT
                ecod_status,
                COUNT(*) as count
            FROM pdb_update.chain_status
            WHERE is_representative = FALSE
            GROUP BY ecod_status
            ORDER BY ecod_status
        """)
        member_by_status = {row["ecod_status"]: row["count"] for row in cur.fetchall()}

        # Get cluster size distribution for representatives
        cur.execute("""
            SELECT
                cluster_size,
                COUNT(*) as num_clusters
            FROM pdb_update.chain_status
            WHERE is_representative = TRUE AND cluster_size IS NOT NULL
            GROUP BY cluster_size
            ORDER BY cluster_size
        """)
        cluster_sizes = {row["cluster_size"]: row["num_clusters"] for row in cur.fetchall()}

    return {
        "clustering_run": clustering_run,
        "rep_by_status": rep_by_status,
        "member_by_status": member_by_status,
        "cluster_sizes": cluster_sizes,
    }


def main():
    print("=" * 80)
    print("PDB Backfill 2023-2025: Partition Analysis")
    print("=" * 80)
    print()

    # Connect to database
    print("Connecting to database...")
    conn = psycopg2.connect(**DB_CONFIG)

    # Get clustering statistics
    print("Fetching clustering statistics...")
    clustering_stats = get_clustering_stats(conn)

    print("\n" + "=" * 80)
    print("CLUSTERING SUMMARY")
    print("=" * 80)

    if clustering_stats["clustering_run"]:
        run = clustering_stats["clustering_run"]
        print(f"Method: {run['method']}")
        print(f"Threshold: {run['threshold']:.0%}")
        print(f"Total sequences: {run['total_sequences']:,}")
        print(f"Total clusters: {run['total_clusters']:,}")
        compression = (1 - run['total_clusters'] / run['total_sequences']) * 100
        print(f"Compression: {compression:.1f}% reduction")
        print(f"Run date: {run['run_date']}")
        print()

        print("Representatives by ECOD status:")
        for status, count in sorted(clustering_stats["rep_by_status"].items()):
            print(f"  {status:20s}: {count:6,}")

        print("\nCluster members by ECOD status:")
        for status, count in sorted(clustering_stats["member_by_status"].items()):
            print(f"  {status:20s}: {count:6,}")

        # Total chains
        total_reps = sum(clustering_stats["rep_by_status"].values())
        total_members = sum(clustering_stats["member_by_status"].values())
        total_chains = total_reps + total_members
        print(f"\nTotal chains: {total_chains:,} ({total_reps:,} reps + {total_members:,} members)")

    # Parse all partition XMLs
    print("\n" + "=" * 80)
    print("PARTITION ANALYSIS (REPRESENTATIVES ONLY)")
    print("=" * 80)
    print(f"Scanning: {PARTITION_DIR}")
    print()

    partition_files = list(PARTITION_DIR.glob("*.xml"))
    print(f"Found {len(partition_files):,} partition XML files")
    print("Parsing...")

    partitions = []
    for xml_file in partition_files:
        result = parse_partition_xml(xml_file)
        if result:
            partitions.append(result)

    print(f"Successfully parsed: {len(partitions):,} partitions\n")

    # Quality distribution
    quality_counts = Counter(p["quality"] for p in partitions)

    print("Quality Distribution (Representatives):")
    print(f"  {'good':20s}: {quality_counts['good']:6,} ({quality_counts['good']/len(partitions)*100:5.1f}%)")
    print(f"  {'low_coverage':20s}: {quality_counts['low_coverage']:6,} ({quality_counts['low_coverage']/len(partitions)*100:5.1f}%)")
    print(f"  {'fragmentary':20s}: {quality_counts['fragmentary']:6,} ({quality_counts['fragmentary']/len(partitions)*100:5.1f}%)")
    print(f"  {'no_domains':20s}: {quality_counts['no_domains']:6,} ({quality_counts['no_domains']/len(partitions)*100:5.1f}%)")
    print()

    # Coverage distribution
    coverage_bins = {
        "100%": 0,
        "90-99%": 0,
        "80-89%": 0,
        "70-79%": 0,
        "60-69%": 0,
        "50-59%": 0,
        "40-49%": 0,
        "30-39%": 0,
        "20-29%": 0,
        "10-19%": 0,
        "0-9%": 0,
        "0%": 0,
    }

    for p in partitions:
        cov = p["coverage"]
        if cov >= 1.0:
            coverage_bins["100%"] += 1
        elif cov >= 0.90:
            coverage_bins["90-99%"] += 1
        elif cov >= 0.80:
            coverage_bins["80-89%"] += 1
        elif cov >= 0.70:
            coverage_bins["70-79%"] += 1
        elif cov >= 0.60:
            coverage_bins["60-69%"] += 1
        elif cov >= 0.50:
            coverage_bins["50-59%"] += 1
        elif cov >= 0.40:
            coverage_bins["40-49%"] += 1
        elif cov >= 0.30:
            coverage_bins["30-39%"] += 1
        elif cov >= 0.20:
            coverage_bins["20-29%"] += 1
        elif cov >= 0.10:
            coverage_bins["10-19%"] += 1
        elif cov > 0.0:
            coverage_bins["0-9%"] += 1
        else:
            coverage_bins["0%"] += 1

    print("Coverage Distribution (Representatives):")
    for bin_name, count in coverage_bins.items():
        if count > 0:
            pct = count / len(partitions) * 100
            print(f"  {bin_name:10s}: {count:6,} ({pct:5.1f}%)")
    print()

    # Domain count distribution
    domain_counts = Counter(p["domain_count"] for p in partitions)
    print("Domain Count Distribution (Representatives):")
    for count in sorted(domain_counts.keys())[:10]:  # Show first 10
        num = domain_counts[count]
        pct = num / len(partitions) * 100
        print(f"  {count:2d} domains: {num:6,} ({pct:5.1f}%)")
    if len(domain_counts) > 10:
        print(f"  ... ({len(domain_counts) - 10} more)")
    print()

    # Algorithm version
    version_counts = Counter(p["algorithm_version"] for p in partitions)
    print("Algorithm Versions:")
    for version, count in version_counts.most_common():
        pct = count / len(partitions) * 100
        print(f"  {version:20s}: {count:6,} ({pct:5.1f}%)")
    print()

    # PROPAGATION POTENTIAL
    print("=" * 80)
    print("PROPAGATION POTENTIAL")
    print("=" * 80)
    print()

    # Get list of partitioned PDB IDs + chain IDs
    partitioned_chains = {(p["pdb_id"], p["chain_id"]) for p in partitions}

    # Query database for cluster members of these representatives
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Get cluster members for partitioned representatives
        cur.execute("""
            SELECT
                m.pdb_id,
                m.chain_id,
                m.representative_pdb_id,
                m.representative_chain_id,
                r.cluster_size
            FROM pdb_update.chain_status m
            JOIN pdb_update.chain_status r ON
                r.pdb_id = m.representative_pdb_id AND
                r.chain_id = m.representative_chain_id
            WHERE
                m.is_representative = FALSE AND
                m.representative_pdb_id IS NOT NULL
        """)

        all_members = cur.fetchall()

        # Filter to members whose representatives have been partitioned
        propagatable_members = [
            m for m in all_members
            if (m["representative_pdb_id"], m["representative_chain_id"]) in partitioned_chains
        ]

    print(f"Total partitioned representatives: {len(partitions):,}")
    print(f"Total cluster members (all): {len(all_members):,}")
    print(f"Propagatable members (reps partitioned): {len(propagatable_members):,}")
    print()

    # Calculate propagated quality distribution
    # Map rep to quality
    rep_quality = {(p["pdb_id"], p["chain_id"]): p["quality"] for p in partitions}

    propagated_quality_counts = defaultdict(int)
    for member in propagatable_members:
        rep_key = (member["representative_pdb_id"], member["representative_chain_id"])
        quality = rep_quality.get(rep_key, "unknown")
        propagated_quality_counts[quality] += 1

    print("Propagated Quality Distribution (Cluster Members):")
    total_prop = sum(propagated_quality_counts.values())
    for quality in ["good", "low_coverage", "fragmentary", "no_domains", "unknown"]:
        count = propagated_quality_counts[quality]
        if count > 0:
            pct = count / total_prop * 100
            print(f"  {quality:20s}: {count:6,} ({pct:5.1f}%)")
    print()

    # TOTAL IMPACT
    print("=" * 80)
    print("TOTAL IMPACT (Representatives + Propagated)")
    print("=" * 80)
    print()

    # Combine representative and propagated quality
    total_quality = defaultdict(int)
    for p in partitions:
        total_quality[p["quality"]] += 1
    for quality, count in propagated_quality_counts.items():
        total_quality[quality] += count

    total_chains_processed = sum(total_quality.values())

    print(f"Total chains processed: {total_chains_processed:,}")
    print()
    print("Combined Quality Distribution:")
    for quality in ["good", "low_coverage", "fragmentary", "no_domains", "unknown"]:
        count = total_quality[quality]
        if count > 0:
            pct = count / total_chains_processed * 100
            print(f"  {quality:20s}: {count:6,} ({pct:5.1f}%)")

    print()
    print("=" * 80)

    conn.close()


if __name__ == "__main__":
    main()
