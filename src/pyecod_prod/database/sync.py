"""
Database synchronization for pyECOD Production Framework.

This module syncs batch manifests to PostgreSQL database for:
- Indexing and coordination
- Progress tracking across batches
- Historical analysis
- ECOD integration preparation

The database is OPTIONAL - the framework can work from YAML manifests alone.
"""

from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List
import yaml

try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


class DatabaseSync:
    """Sync batch manifests to PostgreSQL database"""

    def __init__(self, connection_params: Optional[Dict] = None):
        """
        Initialize database connection.

        Args:
            connection_params: Dict with keys: host, port, database, user, password
                             If None, uses environment variables or defaults
        """
        if not PSYCOPG2_AVAILABLE:
            raise ImportError("psycopg2 is required for database sync. Install with: pip install psycopg2-binary")

        if connection_params is None:
            # Use defaults (can be overridden with env vars)
            connection_params = {
                "host": "localhost",
                "port": 5432,
                "database": "update_protein",
                "user": "ecod",
                "password": None  # Will use .pgpass or other auth
            }

        self.conn_params = connection_params
        self.conn = None

    def connect(self):
        """Establish database connection"""
        if self.conn is None or self.conn.closed:
            self.conn = psycopg2.connect(**self.conn_params)
            self.conn.autocommit = False  # Use transactions
        return self.conn

    def close(self):
        """Close database connection"""
        if self.conn and not self.conn.closed:
            self.conn.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.close()

    def sync_weekly_batch(self, batch_path: str, overwrite=False):
        """
        Sync a weekly batch manifest to database.

        Args:
            batch_path: Path to batch directory containing batch_manifest.yaml
            overwrite: If True, update existing records; if False, skip if exists
        """
        batch_path = Path(batch_path)
        manifest_path = batch_path / "batch_manifest.yaml"

        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)

        # Extract batch metadata
        batch_name = manifest["batch_name"]
        batch_type = manifest.get("batch_type", "weekly")

        if batch_type != "weekly":
            raise ValueError(f"Expected weekly batch, got {batch_type}")

        release_date = manifest.get("release_date")
        if not release_date:
            # Parse from batch name (ecod_weekly_20251019)
            release_date = batch_name.split("_")[-1]
            release_date = f"{release_date[:4]}-{release_date[4:6]}-{release_date[6:8]}"

        pdb_status_path = manifest.get("pdb_status_path", "")
        created_at = manifest.get("created")
        processing_status = manifest.get("processing_status", {})

        # Insert or update weekly_release record
        cursor = self.conn.cursor()

        try:
            # Check if exists
            cursor.execute(
                "SELECT release_date FROM pdb_update.weekly_release WHERE release_date = %s",
                (release_date,)
            )
            exists = cursor.fetchone() is not None

            if exists and not overwrite:
                print(f"Batch {release_date} already in database (use overwrite=True to update)")
                return

            # Insert/update weekly_release
            cursor.execute("""
                INSERT INTO pdb_update.weekly_release
                    (release_date, pdb_status_path, batch_name, batch_path,
                     total_structures, classifiable_chains, processed_structures,
                     status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (release_date) DO UPDATE SET
                    pdb_status_path = EXCLUDED.pdb_status_path,
                    batch_name = EXCLUDED.batch_name,
                    batch_path = EXCLUDED.batch_path,
                    total_structures = EXCLUDED.total_structures,
                    classifiable_chains = EXCLUDED.classifiable_chains,
                    processed_structures = EXCLUDED.processed_structures,
                    status = EXCLUDED.status
            """, (
                release_date,
                pdb_status_path,
                batch_name,
                str(batch_path),
                processing_status.get("total_structures", 0),
                processing_status.get("total_structures", 0),  # classifiable_chains
                processing_status.get("partition_complete", 0),  # processed_structures
                self._determine_batch_status(manifest),
                created_at
            ))

            # Insert/update chain_status records
            chains_synced = 0
            for chain_key, chain_data in manifest.get("chains", {}).items():
                self._sync_chain_status(cursor, release_date, chain_data, overwrite)
                chains_synced += 1

            self.conn.commit()
            print(f"✓ Synced batch {release_date}: {chains_synced} chains")

        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Failed to sync batch {release_date}: {e}") from e
        finally:
            cursor.close()

    def _sync_chain_status(self, cursor, release_date: str, chain_data: Dict, overwrite: bool):
        """Sync individual chain status to database"""

        pdb_id = chain_data["pdb_id"]
        chain_id = chain_data["chain_id"]

        # Check if exists
        cursor.execute(
            "SELECT pdb_id FROM pdb_update.chain_status WHERE pdb_id = %s AND chain_id = %s AND release_date = %s",
            (pdb_id, chain_id, release_date)
        )
        exists = cursor.fetchone() is not None

        if exists and not overwrite:
            return  # Skip

        # Prepare chain data
        can_classify = chain_data.get("can_classify", True)
        cannot_classify_reason = chain_data.get("cannot_classify_reason")
        sequence_length = chain_data.get("sequence_length")

        blast_status = chain_data.get("blast_status", "pending")
        blast_coverage = chain_data.get("blast_coverage")

        needs_hhsearch = chain_data.get("needs_hhsearch", False)
        hhsearch_status = chain_data.get("hhsearch_status", "not_needed")

        partition_status = chain_data.get("partition_status", "pending")
        partition_coverage = chain_data.get("partition_coverage")
        domain_count = chain_data.get("domain_count")
        partition_quality = chain_data.get("partition_quality")

        # File paths (relative)
        files = chain_data.get("files", {})

        cursor.execute("""
            INSERT INTO pdb_update.chain_status
                (pdb_id, chain_id, release_date,
                 can_classify, cannot_classify_reason, sequence_length,
                 blast_status, blast_coverage,
                 needs_hhsearch, hhsearch_status,
                 partition_status, partition_coverage, domain_count, partition_quality,
                 fasta_path, chain_blast_path, domain_blast_path,
                 hhsearch_hhr_path, summary_path, partition_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (pdb_id, chain_id, release_date) DO UPDATE SET
                can_classify = EXCLUDED.can_classify,
                cannot_classify_reason = EXCLUDED.cannot_classify_reason,
                sequence_length = EXCLUDED.sequence_length,
                blast_status = EXCLUDED.blast_status,
                blast_coverage = EXCLUDED.blast_coverage,
                needs_hhsearch = EXCLUDED.needs_hhsearch,
                hhsearch_status = EXCLUDED.hhsearch_status,
                partition_status = EXCLUDED.partition_status,
                partition_coverage = EXCLUDED.partition_coverage,
                domain_count = EXCLUDED.domain_count,
                partition_quality = EXCLUDED.partition_quality,
                fasta_path = EXCLUDED.fasta_path,
                chain_blast_path = EXCLUDED.chain_blast_path,
                domain_blast_path = EXCLUDED.domain_blast_path,
                hhsearch_hhr_path = EXCLUDED.hhsearch_hhr_path,
                summary_path = EXCLUDED.summary_path,
                partition_path = EXCLUDED.partition_path,
                updated_at = now()
        """, (
            pdb_id, chain_id, release_date,
            can_classify, cannot_classify_reason, sequence_length,
            blast_status, blast_coverage,
            needs_hhsearch, hhsearch_status,
            partition_status, partition_coverage, domain_count, partition_quality,
            files.get("fasta"),
            files.get("chain_blast"),
            files.get("domain_blast"),
            files.get("hhsearch"),
            files.get("summary"),
            files.get("partition")
        ))

    def _determine_batch_status(self, manifest: Dict) -> str:
        """Determine overall batch status from manifest"""
        processing_status = manifest.get("processing_status", {})

        total = processing_status.get("total_structures", 0)
        partition_complete = processing_status.get("partition_complete", 0)
        blast_complete = processing_status.get("blast_complete", 0)

        if partition_complete == total and total > 0:
            return "complete"
        elif blast_complete == total and total > 0:
            return "blast_complete"
        elif blast_complete > 0 or partition_complete > 0:
            return "processing"
        else:
            return "pending"

    def sync_all_batches(self, base_path: str, overwrite=False):
        """
        Sync all batches from a directory to database.

        Args:
            base_path: Base path containing batch directories
            overwrite: Whether to update existing records
        """
        base_path = Path(base_path)
        synced = 0
        failed = 0

        for batch_dir in sorted(base_path.glob("ecod_weekly_*")):
            if not batch_dir.is_dir():
                continue

            try:
                print(f"Syncing {batch_dir.name}...")
                self.sync_weekly_batch(str(batch_dir), overwrite=overwrite)
                synced += 1
            except Exception as e:
                print(f"✗ Failed to sync {batch_dir.name}: {e}")
                failed += 1

        print(f"\nSummary: {synced} synced, {failed} failed")

    def get_batch_summary(self, release_date: Optional[str] = None) -> List[Dict]:
        """
        Get summary of batches from database.

        Args:
            release_date: Specific release date, or None for all

        Returns:
            List of batch summary dicts
        """
        cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            if release_date:
                cursor.execute("SELECT * FROM pdb_update.release_summary WHERE release_date = %s", (release_date,))
            else:
                cursor.execute("SELECT * FROM pdb_update.release_summary ORDER BY release_date DESC")

            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def get_chains_needing_hhsearch(self, release_date: Optional[str] = None) -> List[Dict]:
        """Get chains that need HHsearch processing"""
        cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            if release_date:
                cursor.execute(
                    "SELECT * FROM pdb_update.chains_needing_hhsearch WHERE release_date = %s",
                    (release_date,)
                )
            else:
                cursor.execute("SELECT * FROM pdb_update.chains_needing_hhsearch")

            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def get_failed_chains(self) -> List[Dict]:
        """Get all chains that failed processing"""
        cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            cursor.execute("SELECT * FROM pdb_update.failed_chains")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()
