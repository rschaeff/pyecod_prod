#!/usr/bin/env python3
"""
Generate quality statistics for domain classification results.

This tool analyzes partition results to provide:
- Coverage distribution (BLAST, HHsearch, partition)
- Domain count statistics
- Quality breakdown
- Outlier detection
- Per-PDB and per-chain analysis

Usage:
    # Analyze specific batch
    python scripts/batch_quality_stats.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905

    # Show detailed statistics
    python scripts/batch_quality_stats.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --detailed

    # Show outliers (low coverage, high domain count, etc.)
    python scripts/batch_quality_stats.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --outliers

    # Export to CSV
    python scripts/batch_quality_stats.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --csv output.csv

    # JSON output
    python scripts/batch_quality_stats.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --json
"""

import sys
import csv
import json
import argparse
from pathlib import Path
from collections import Counter, defaultdict
import statistics

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pyecod_prod.batch.manifest import BatchManifest


def analyze_quality(batch_path: str):
    """
    Analyze domain classification quality from batch.

    Returns:
        dict with quality statistics
    """
    batch_path = Path(batch_path)
    manifest = BatchManifest(str(batch_path))
    data = manifest.data

    # Collect data for analysis
    blast_coverages = []
    hhsearch_coverages = []
    partition_coverages = []
    domain_counts = []
    sequence_lengths = []

    quality_counts = Counter()
    chains_by_quality = defaultdict(list)

    # Per-chain data for export
    chain_details = []

    # Coverage bins
    coverage_bins = {
        "0-25%": 0,
        "25-50%": 0,
        "50-75%": 0,
        "75-90%": 0,
        "90-100%": 0,
    }

    # Domain count distribution
    domain_distribution = Counter()

    for chain_key, chain_data in data["chains"].items():
        if not chain_data.get("can_classify", True):
            continue

        if chain_data.get("partition_status") != "complete":
            continue

        pdb_id = chain_data["pdb_id"]
        chain_id = chain_data["chain_id"]

        # Coverage
        blast_cov = chain_data.get("blast_coverage")
        hhsearch_cov = chain_data.get("hhsearch_coverage")
        partition_cov = chain_data.get("partition_coverage")

        if blast_cov is not None:
            blast_coverages.append(blast_cov)

        if hhsearch_cov is not None:
            hhsearch_coverages.append(hhsearch_cov)

        if partition_cov is not None:
            partition_coverages.append(partition_cov)

            # Bin partition coverage
            if partition_cov < 0.25:
                coverage_bins["0-25%"] += 1
            elif partition_cov < 0.50:
                coverage_bins["25-50%"] += 1
            elif partition_cov < 0.75:
                coverage_bins["50-75%"] += 1
            elif partition_cov < 0.90:
                coverage_bins["75-90%"] += 1
            else:
                coverage_bins["90-100%"] += 1

        # Domain count
        domain_count = chain_data.get("domain_count")
        if domain_count is not None:
            domain_counts.append(domain_count)
            domain_distribution[domain_count] += 1

        # Sequence length
        seq_len = chain_data.get("sequence_length")
        if seq_len is not None:
            sequence_lengths.append(seq_len)

        # Quality
        quality = chain_data.get("partition_quality", "unknown")
        quality_counts[quality] += 1
        chains_by_quality[quality].append(chain_key)

        # Chain details
        chain_details.append({
            "pdb_id": pdb_id,
            "chain_id": chain_id,
            "sequence_length": seq_len,
            "blast_coverage": blast_cov,
            "hhsearch_coverage": hhsearch_cov,
            "partition_coverage": partition_cov,
            "domain_count": domain_count,
            "quality": quality,
        })

    # Calculate statistics
    def calc_stats(values):
        if not values:
            return {
                "count": 0,
                "mean": 0,
                "median": 0,
                "min": 0,
                "max": 0,
                "stdev": 0,
            }
        return {
            "count": len(values),
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0,
        }

    return {
        "batch_name": data.get("batch_name"),
        "batch_type": data.get("batch_type"),
        "total_chains": len([c for c in data["chains"].values() if c.get("partition_status") == "complete"]),
        "coverage": {
            "blast": calc_stats(blast_coverages),
            "hhsearch": calc_stats(hhsearch_coverages),
            "partition": calc_stats(partition_coverages),
            "partition_bins": coverage_bins,
        },
        "domains": {
            "statistics": calc_stats(domain_counts),
            "distribution": dict(domain_distribution),
        },
        "sequence_length": calc_stats(sequence_lengths),
        "quality": {
            "counts": dict(quality_counts),
            "chains_by_quality": {k: len(v) for k, v in chains_by_quality.items()},
        },
        "chain_details": chain_details,
    }


def find_outliers(chain_details, coverage_threshold=0.5, domain_threshold=10):
    """Find outlier chains"""
    outliers = {
        "low_coverage": [],
        "high_domain_count": [],
        "zero_domains": [],
        "fragmentary": [],
    }

    for chain in chain_details:
        # Low coverage
        if chain["partition_coverage"] is not None and chain["partition_coverage"] < coverage_threshold:
            outliers["low_coverage"].append(chain)

        # High domain count
        if chain["domain_count"] is not None and chain["domain_count"] > domain_threshold:
            outliers["high_domain_count"].append(chain)

        # Zero domains
        if chain["domain_count"] == 0:
            outliers["zero_domains"].append(chain)

        # Fragmentary quality
        if chain["quality"] == "fragmentary":
            outliers["fragmentary"].append(chain)

    return outliers


def print_statistics(stats, detailed=False, show_outliers=False):
    """Print formatted statistics"""
    print(f"\n{'='*70}")
    print(f"Quality Statistics: {stats['batch_name']}")
    print(f"{'='*70}")
    print(f"Batch type: {stats['batch_type']}")
    print(f"Total chains analyzed: {stats['total_chains']}")

    # Coverage statistics
    print(f"\n{'='*70}")
    print("Coverage Statistics")
    print(f"{'='*70}")

    print(f"\nBLAST Coverage:")
    blast = stats['coverage']['blast']
    if blast['count'] > 0:
        print(f"  Chains: {blast['count']}")
        print(f"  Mean: {blast['mean']:.1%} ± {blast['stdev']:.1%}")
        print(f"  Median: {blast['median']:.1%}")
        print(f"  Range: {blast['min']:.1%} - {blast['max']:.1%}")

    if stats['coverage']['hhsearch']['count'] > 0:
        print(f"\nHHsearch Coverage:")
        hhsearch = stats['coverage']['hhsearch']
        print(f"  Chains: {hhsearch['count']}")
        print(f"  Mean: {hhsearch['mean']:.1%} ± {hhsearch['stdev']:.1%}")
        print(f"  Median: {hhsearch['median']:.1%}")
        print(f"  Range: {hhsearch['min']:.1%} - {hhsearch['max']:.1%}")

    print(f"\nPartition Coverage:")
    partition = stats['coverage']['partition']
    if partition['count'] > 0:
        print(f"  Chains: {partition['count']}")
        print(f"  Mean: {partition['mean']:.1%} ± {partition['stdev']:.1%}")
        print(f"  Median: {partition['median']:.1%}")
        print(f"  Range: {partition['min']:.1%} - {partition['max']:.1%}")

    print(f"\nPartition Coverage Distribution:")
    for bin_range, count in stats['coverage']['partition_bins'].items():
        pct = (count / partition['count'] * 100) if partition['count'] > 0 else 0
        bar = '█' * int(pct / 2)
        print(f"  {bin_range:10} {count:5} ({pct:5.1f}%) {bar}")

    # Domain statistics
    print(f"\n{'='*70}")
    print("Domain Statistics")
    print(f"{'='*70}")

    domains = stats['domains']['statistics']
    if domains['count'] > 0:
        print(f"  Chains with domains: {domains['count']}")
        print(f"  Mean domains/chain: {domains['mean']:.2f} ± {domains['stdev']:.2f}")
        print(f"  Median: {domains['median']:.0f}")
        print(f"  Range: {domains['min']:.0f} - {domains['max']:.0f}")

    if detailed:
        print(f"\nDomain Count Distribution:")
        dist = stats['domains']['distribution']
        for domain_count in sorted(dist.keys())[:15]:  # Show first 15
            count = dist[domain_count]
            pct = (count / domains['count'] * 100) if domains['count'] > 0 else 0
            bar = '█' * min(int(pct), 50)
            print(f"  {domain_count:2} domains: {count:5} ({pct:5.1f}%) {bar}")

    # Quality statistics
    print(f"\n{'='*70}")
    print("Quality Distribution")
    print(f"{'='*70}")

    quality_counts = stats['quality']['counts']
    total_quality = sum(quality_counts.values())
    for quality in sorted(quality_counts.keys()):
        count = quality_counts[quality]
        pct = (count / total_quality * 100) if total_quality > 0 else 0
        bar = '█' * int(pct / 2)
        print(f"  {quality:20} {count:5} ({pct:5.1f}%) {bar}")

    # Sequence length
    if detailed:
        print(f"\n{'='*70}")
        print("Sequence Length Statistics")
        print(f"{'='*70}")
        seq_len = stats['sequence_length']
        if seq_len['count'] > 0:
            print(f"  Chains: {seq_len['count']}")
            print(f"  Mean: {seq_len['mean']:.0f} ± {seq_len['stdev']:.0f} residues")
            print(f"  Median: {seq_len['median']:.0f}")
            print(f"  Range: {seq_len['min']:.0f} - {seq_len['max']:.0f}")

    # Outliers
    if show_outliers:
        print(f"\n{'='*70}")
        print("Outliers")
        print(f"{'='*70}")

        outliers = find_outliers(stats['chain_details'])

        print(f"\nLow Coverage (<50%):")
        print(f"  Count: {len(outliers['low_coverage'])}")
        if outliers['low_coverage']:
            for chain in sorted(outliers['low_coverage'], key=lambda x: x['partition_coverage'])[:10]:
                print(f"    {chain['pdb_id']}_{chain['chain_id']}: {chain['partition_coverage']:.1%} coverage, {chain['domain_count']} domains")
            if len(outliers['low_coverage']) > 10:
                print(f"    ... and {len(outliers['low_coverage']) - 10} more")

        print(f"\nHigh Domain Count (>10 domains):")
        print(f"  Count: {len(outliers['high_domain_count'])}")
        if outliers['high_domain_count']:
            for chain in sorted(outliers['high_domain_count'], key=lambda x: x['domain_count'], reverse=True)[:10]:
                print(f"    {chain['pdb_id']}_{chain['chain_id']}: {chain['domain_count']} domains, {chain['sequence_length']} residues")
            if len(outliers['high_domain_count']) > 10:
                print(f"    ... and {len(outliers['high_domain_count']) - 10} more")

        print(f"\nZero Domains:")
        print(f"  Count: {len(outliers['zero_domains'])}")
        if outliers['zero_domains']:
            for chain in outliers['zero_domains'][:10]:
                print(f"    {chain['pdb_id']}_{chain['chain_id']}: {chain['partition_coverage']:.1%} coverage")
            if len(outliers['zero_domains']) > 10:
                print(f"    ... and {len(outliers['zero_domains']) - 10} more")

        print(f"\nFragmentary Quality:")
        print(f"  Count: {len(outliers['fragmentary'])}")

    print()


def export_csv(stats, output_file):
    """Export chain details to CSV"""
    with open(output_file, 'w', newline='') as f:
        if not stats['chain_details']:
            print(f"No chain details to export")
            return

        fieldnames = stats['chain_details'][0].keys()
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(stats['chain_details'])

    print(f"Exported {len(stats['chain_details'])} chains to {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate quality statistics for domain classification results"
    )
    parser.add_argument(
        "batch_path",
        help="Path to batch directory"
    )
    parser.add_argument(
        "--detailed", "-d",
        action="store_true",
        help="Show detailed statistics"
    )
    parser.add_argument(
        "--outliers", "-o",
        action="store_true",
        help="Show outlier chains"
    )
    parser.add_argument(
        "--csv",
        help="Export chain details to CSV file"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON"
    )

    args = parser.parse_args()

    try:
        stats = analyze_quality(args.batch_path)

        if args.json:
            # Remove chain_details from JSON output (too verbose)
            output = {k: v for k, v in stats.items() if k != 'chain_details'}
            output['chain_count'] = len(stats['chain_details'])
            print(json.dumps(output, indent=2))
        else:
            print_statistics(stats, detailed=args.detailed, show_outliers=args.outliers)

        if args.csv:
            export_csv(stats, args.csv)

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
