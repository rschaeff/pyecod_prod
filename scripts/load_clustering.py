#!/usr/bin/env python3
"""
Load CD-HIT clustering results to pdb_update schema.

This enables efficient production workflow by clustering proteins at sequence identity
thresholds (typically 70%) and processing only representatives, then propagating results
to cluster members.

**IMPORTANT**: Clustering data flows: pyecod_prod (generates) → pyecod_vis (consumes).
This script loads to pdb_update, NOT ecod_curation.

Usage:
    # Load CD-HIT cluster file for a release
    python scripts/load_clustering.py \
        --cluster-file /data/ecod/pdb_updates/batches/ecod_weekly_20250905/clustering/cdhit70.clstr \
        --release-date 2025-09-05 \
        --threshold 0.70

    # Show clustering efficiency
    python scripts/load_clustering.py --stats --release-date 2025-09-05

    # Show clustering for all releases
    python scripts/load_clustering.py --stats
"""

import sys
import re
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Error: psycopg2 not found. Install with: pip install psycopg2-binary")
    sys.exit(1)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_connection_params():
    """Get database connection parameters (default to dione)"""
    return {
        "host": "dione",
        "port": 45000,
        "database": "ecod_protein",
        "user": "ecod",
        "password": "ecod#badmin"
    }


def parse_cdhit_clstr(clstr_file: str) -> List[Dict]:
    """
    Parse CD-HIT .clstr file.

    Format:
    >Cluster 0
    0	64aa, >8s72_A... *
    1	225aa, >8s72_H... at 85%
    >Cluster 1
    0	293aa, >8yl2_A... *

    Args:
        clstr_file: Path to CD-HIT .clstr file

    Returns:
        List of cluster dicts with 'representative' and 'members'
    """
    clusters = []
    current_cluster = None

    with open(clstr_file) as f:
        for line in f:
            line = line.strip()

            if line.startswith('>Cluster'):
                if current_cluster:
                    clusters.append(current_cluster)
                current_cluster = {
                    'representative': None,
                    'members': []
                }
            else:
                # Parse member line: "0	64aa, >8s72_A... *"
                match = re.search(r'>(\S+)\.\.\. (.+)$', line)
                if match:
                    seq_id = match.group(1)  # e.g., "8s72_A"
                    status = match.group(2)

                    if status == '*':
                        # This is the representative
                        current_cluster['representative'] = seq_id
                    else:
                        # Parse identity: "at 85%"
                        identity_match = re.search(r'at (\d+(?:\.\d+)?)%', status)
                        identity = float(identity_match.group(1)) / 100.0 if identity_match else None

                        current_cluster['members'].append({
                            'seq_id': seq_id,
                            'identity': identity
                        })

        # Add last cluster
        if current_cluster:
            clusters.append(current_cluster)

    return clusters


def parse_mmseqs_clusters(cluster_tsv: str) -> List[Dict]:
    """
    Parse mmseqs2 cluster TSV file.

    Format (tab-separated):
    representative_id    member_id
    8s72_A              8s72_A
    8s72_A              8abc_A
    8s72_A              9xyz_B
    8yl2_A              8yl2_A

    Args:
        cluster_tsv: Path to mmseqs2 cluster TSV file

    Returns:
        List of cluster dicts with 'representative' and 'members'
    """
    clusters_dict = {}  # rep_id -> cluster dict

    with open(cluster_tsv) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split('\t')
            if len(parts) != 2:
                logger.warning(f"Skipping malformed line: {line}")
                continue

            rep_id, member_id = parts

            # Create cluster if not exists
            if rep_id not in clusters_dict:
                clusters_dict[rep_id] = {
                    'representative': rep_id,
                    'members': []
                }

            # Add member (if it's not the representative itself)
            if member_id != rep_id:
                # mmseqs2 doesn't report exact identity in TSV
                # We set to None (will be stored as NULL in database)
                clusters_dict[rep_id]['members'].append({
                    'seq_id': member_id,
                    'identity': None
                })

    return list(clusters_dict.values())


def parse_chain_key(seq_id: str) -> Tuple[str, str]:
    """
    Parse chain key like '8s72_A' into (pdb_id, chain_id).

    Args:
        seq_id: Sequence identifier (e.g., '8s72_A')

    Returns:
        Tuple of (pdb_id, chain_id)
    """
    parts = seq_id.split('_')
    if len(parts) != 2:
        raise ValueError(f"Invalid seq_id format: {seq_id} (expected PDB_CHAIN)")

    return (parts[0].lower(), parts[1])  # Normalize PDB ID to lowercase


def load_clustering_to_pdb_update(
    cluster_file: str,
    release_date: str,
    method: str = 'cd-hit',
    identity_threshold: float = 0.70,
    word_length: int = 5,
    memory_mb: int = 8000,
    threads: int = 4
) -> Dict:
    """
    Load clustering results to pdb_update schema.

    Supports both CD-HIT (.clstr) and mmseqs2 (TSV) formats.

    Args:
        cluster_file: Path to cluster file (.clstr for CD-HIT, .tsv for mmseqs2)
        release_date: Release date (YYYY-MM-DD)
        method: Clustering method ('cd-hit' or 'mmseqs2', default: cd-hit)
        identity_threshold: Sequence identity threshold (default: 0.70)
        word_length: CD-HIT word length parameter (ignored for mmseqs2)
        memory_mb: Memory limit in MB (ignored for mmseqs2)
        threads: Thread count (ignored for mmseqs2)

    Returns:
        Dict with loading statistics
    """
    conn_params = get_connection_params()
    conn = psycopg2.connect(**conn_params)
    cursor = conn.cursor()

    try:
        # Parse cluster file based on method
        logger.info(f"Parsing {cluster_file} ({method} format)...")
        if method == 'cd-hit':
            clusters = parse_cdhit_clstr(cluster_file)
        elif method == 'mmseqs2':
            clusters = parse_mmseqs_clusters(cluster_file)
        else:
            raise ValueError(f"Unsupported clustering method: {method}. Use 'cd-hit' or 'mmseqs2'.")
        logger.info(f"  Found {len(clusters)} clusters")

        # Calculate statistics
        total_chains = sum(1 + len(c['members']) for c in clusters)
        representative_count = len(clusters)
        singleton_clusters = sum(1 for c in clusters if len(c['members']) == 0)
        cluster_sizes = [1 + len(c['members']) for c in clusters]
        avg_cluster_size = sum(cluster_sizes) / len(cluster_sizes) if cluster_sizes else 0
        max_cluster_size = max(cluster_sizes) if cluster_sizes else 0

        # Get classifiable chain count from chain_status
        cursor.execute("""
            SELECT COUNT(*)
            FROM pdb_update.chain_status
            WHERE release_date = %s AND can_classify = TRUE
        """, (release_date,))
        classifiable_chains = cursor.fetchone()[0]

        # Insert clustering_run record
        logger.info(f"Creating clustering_run record...")
        cursor.execute("""
            INSERT INTO pdb_update.clustering_run
                (release_date, method, identity_threshold, total_chains, classifiable_chains,
                 total_clusters, representative_count, singleton_clusters, avg_cluster_size,
                 max_cluster_size, word_length, memory_mb, threads, cluster_file_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (release_date, method, identity_threshold) DO UPDATE SET
                total_chains = EXCLUDED.total_chains,
                classifiable_chains = EXCLUDED.classifiable_chains,
                total_clusters = EXCLUDED.total_clusters,
                representative_count = EXCLUDED.representative_count,
                singleton_clusters = EXCLUDED.singleton_clusters,
                avg_cluster_size = EXCLUDED.avg_cluster_size,
                max_cluster_size = EXCLUDED.max_cluster_size,
                cluster_file_path = EXCLUDED.cluster_file_path
            RETURNING id
        """, (
            release_date, method, identity_threshold, total_chains, classifiable_chains,
            len(clusters), representative_count, singleton_clusters, avg_cluster_size,
            max_cluster_size, word_length, memory_mb, threads, cluster_file
        ))

        clustering_run_id = cursor.fetchone()[0]
        logger.info(f"  Clustering run ID: {clustering_run_id}")

        # Load cluster memberships
        logger.info(f"Loading {total_chains} cluster members...")

        loaded_reps = 0
        loaded_members = 0
        missing_chains = []
        updated_chain_status = 0

        for cluster_id, cluster in enumerate(clusters):
            rep_seq_id = cluster['representative']

            try:
                rep_pdb_id, rep_chain_id = parse_chain_key(rep_seq_id)
            except ValueError as e:
                logger.warning(f"Skipping cluster {cluster_id}: {e}")
                continue

            # Insert representative to cluster_member
            cursor.execute("""
                INSERT INTO pdb_update.cluster_member
                    (clustering_run_id, cluster_id, pdb_id, chain_id, release_date,
                     is_representative, sequence_identity_to_rep)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (clustering_run_id, cluster_id, pdb_id, chain_id) DO NOTHING
            """, (clustering_run_id, cluster_id, rep_pdb_id, rep_chain_id, release_date, True, 1.0))

            # Update chain_status for representative
            cursor.execute("""
                UPDATE pdb_update.chain_status
                SET cluster_id = %s,
                    is_representative = TRUE,
                    representative_pdb_id = NULL,
                    representative_chain_id = NULL,
                    sequence_identity_to_rep = NULL
                WHERE pdb_id = %s AND chain_id = %s AND release_date = %s
                RETURNING pdb_id
            """, (cluster_id, rep_pdb_id, rep_chain_id, release_date))

            if cursor.fetchone():
                loaded_reps += 1
                updated_chain_status += 1
            else:
                missing_chains.append(rep_seq_id)

            # Insert cluster members
            for member in cluster['members']:
                member_seq_id = member['seq_id']
                identity = member['identity']

                try:
                    member_pdb_id, member_chain_id = parse_chain_key(member_seq_id)
                except ValueError as e:
                    logger.warning(f"Skipping member {member_seq_id}: {e}")
                    continue

                # Insert to cluster_member
                cursor.execute("""
                    INSERT INTO pdb_update.cluster_member
                        (clustering_run_id, cluster_id, pdb_id, chain_id, release_date,
                         is_representative, sequence_identity_to_rep)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (clustering_run_id, cluster_id, pdb_id, chain_id) DO NOTHING
                """, (clustering_run_id, cluster_id, member_pdb_id, member_chain_id, release_date, False, identity))

                # Update chain_status for member
                cursor.execute("""
                    UPDATE pdb_update.chain_status
                    SET cluster_id = %s,
                        is_representative = FALSE,
                        representative_pdb_id = %s,
                        representative_chain_id = %s,
                        sequence_identity_to_rep = %s
                    WHERE pdb_id = %s AND chain_id = %s AND release_date = %s
                    RETURNING pdb_id
                """, (cluster_id, rep_pdb_id, rep_chain_id, identity, member_pdb_id, member_chain_id, release_date))

                if cursor.fetchone():
                    loaded_members += 1
                    updated_chain_status += 1
                else:
                    missing_chains.append(member_seq_id)

        conn.commit()

        # Calculate reduction factor
        reduction_factor = (1.0 - (representative_count / total_chains)) * 100 if total_chains > 0 else 0

        logger.info(f"✓ Clustering loaded successfully")
        logger.info(f"  Total clusters: {len(clusters)}")
        logger.info(f"  Representatives: {loaded_reps}")
        logger.info(f"  Members: {loaded_members}")
        logger.info(f"  Workload reduction: {reduction_factor:.1f}%")

        if missing_chains:
            logger.warning(f"  Missing chains (not in chain_status): {len(missing_chains)}")
            if len(missing_chains) <= 10:
                for chain in missing_chains:
                    logger.warning(f"    - {chain}")
            else:
                for chain in missing_chains[:10]:
                    logger.warning(f"    - {chain}")
                logger.warning(f"    ... and {len(missing_chains) - 10} more")

        return {
            'clustering_run_id': clustering_run_id,
            'total_clusters': len(clusters),
            'representatives_loaded': loaded_reps,
            'members_loaded': loaded_members,
            'missing_chains': missing_chains,
            'reduction_factor': reduction_factor,
            'updated_chain_status': updated_chain_status
        }

    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"Failed to load clustering: {e}") from e

    finally:
        cursor.close()
        conn.close()


def show_clustering_stats(release_date: Optional[str] = None):
    """
    Show clustering efficiency statistics.

    Args:
        release_date: Optional specific release (YYYY-MM-DD)
    """
    conn_params = get_connection_params()
    conn = psycopg2.connect(**conn_params)
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        if release_date:
            cursor.execute("""
                SELECT * FROM pdb_update.clustering_efficiency
                WHERE release_date = %s
                ORDER BY release_date DESC
            """, (release_date,))
        else:
            cursor.execute("""
                SELECT * FROM pdb_update.clustering_efficiency
                ORDER BY release_date DESC
            """)

        rows = cursor.fetchall()
        if not rows:
            logger.info("No clustering data found.")
            return

        print("\n" + "=" * 90)
        print("Clustering Efficiency Statistics")
        print("=" * 90)
        print(f"{'Release':<12} {'Threshold':<10} {'Chains':<10} {'Clusters':<10} {'Reps':<10} {'Reduction':<12}")
        print("-" * 90)

        for row in rows:
            release = str(row['release_date'])
            threshold = f"{row['identity_threshold']*100:.0f}%"
            chains = row['classifiable_chains']
            clusters = row['total_clusters']
            reps = row['representative_count']
            reduction = f"{row['reduction_percent']:.1f}%"

            print(f"{release:<12} {threshold:<10} {chains:<10} {clusters:<10} {reps:<10} {reduction:<12}")

        print("=" * 90)

        # Detailed view for specific release
        if release_date and len(rows) == 1:
            row = rows[0]
            print(f"\nDetailed Statistics for {release_date}:")
            print(f"  Method: {row['method']}")
            print(f"  Identity threshold: {row['identity_threshold']*100:.0f}%")
            print(f"  Total chains: {row['total_chains']}")
            print(f"  Classifiable chains: {row['classifiable_chains']}")
            print(f"  Total clusters: {row['total_clusters']}")
            print(f"  Singleton clusters: {row['singleton_clusters']}")
            print(f"  Average cluster size: {row['avg_cluster_size']:.1f}")
            print(f"  Max cluster size: {int(row['max_cluster_size'])}")
            print(f"  Representative count: {row['representative_count']}")
            print(f"  Workload reduction: {row['reduction_percent']:.1f}%")
            print(f"    (Process {row['representative_count']} reps instead of {row['classifiable_chains']} chains)")
            print()

    finally:
        cursor.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Load clustering results to pdb_update schema (supports mmseqs2 and CD-HIT)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Load mmseqs2 clustering (recommended)
    python scripts/load_clustering.py \\
        --cluster-file clustering_70pct_cluster.tsv \\
        --release-date 2025-10-21 \\
        --method mmseqs2 \\
        --threshold 0.70

    # Load CD-HIT clustering
    python scripts/load_clustering.py \\
        --cluster-file cdhit70.fasta.clstr \\
        --release-date 2025-09-05 \\
        --method cd-hit \\
        --threshold 0.70

    # Show efficiency for specific release
    python scripts/load_clustering.py --stats --release-date 2025-09-05

    # Show efficiency for all releases
    python scripts/load_clustering.py --stats
        """
    )

    parser.add_argument('--cluster-file', help='Path to cluster file (.clstr for CD-HIT, .tsv for mmseqs2)')
    parser.add_argument('--release-date', help='Release date (YYYY-MM-DD)')
    parser.add_argument('--method', choices=['cd-hit', 'mmseqs2'], default='cd-hit',
                       help='Clustering method (default: cd-hit)')
    parser.add_argument('--threshold', type=float, default=0.70, help='Sequence identity threshold (default: 0.70)')
    parser.add_argument('--stats', action='store_true', help='Show clustering statistics')
    parser.add_argument('--word-length', type=int, default=5, help='CD-HIT word length (default: 5, ignored for mmseqs2)')
    parser.add_argument('--memory', type=int, default=8000, help='Memory in MB (default: 8000, ignored for mmseqs2)')
    parser.add_argument('--threads', type=int, default=4, help='Threads (default: 4, ignored for mmseqs2)')

    args = parser.parse_args()

    if args.stats:
        show_clustering_stats(args.release_date)
        return 0

    if not args.cluster_file or not args.release_date:
        parser.error("--cluster-file and --release-date are required (or use --stats)")

    # Load clustering to database
    result = load_clustering_to_pdb_update(
        cluster_file=args.cluster_file,
        release_date=args.release_date,
        method=args.method,
        identity_threshold=args.threshold,
        word_length=args.word_length,
        memory_mb=args.memory,
        threads=args.threads
    )

    print(f"\n{'=' * 70}")
    print("Clustering loaded successfully!")
    print(f"{'=' * 70}")
    print(f"  Clustering run ID: {result['clustering_run_id']}")
    print(f"  Total clusters: {result['total_clusters']}")
    print(f"  Representatives loaded: {result['representatives_loaded']}")
    print(f"  Members loaded: {result['members_loaded']}")
    print(f"  Chain status updated: {result['updated_chain_status']}")
    print(f"  Workload reduction: {result['reduction_factor']:.1f}%")

    if result['missing_chains']:
        print(f"\n  WARNING: {len(result['missing_chains'])} chains not found in chain_status")
        print("  (These chains may have been filtered as peptides or not classifiable)")

    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
