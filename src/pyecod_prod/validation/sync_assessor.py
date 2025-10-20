#!/usr/bin/env python3
"""
ECOD-PDB Synchronization Assessor

Analyzes the completeness and currency of ECOD classifications
relative to PDB holdings.

Key Questions:
1. What is the last classified PDB week?
2. How many PDB chains exist vs. are classified?
3. Which chains need NEW classification (update weeks)?
4. Which chains need RE-classification (repair weeks)?
5. Which chains are marked as non-classifiable and why?
"""

import psycopg2
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Set
from pathlib import Path


@dataclass
class SyncStatus:
    """Overall ECOD-PDB synchronization status"""

    # ECOD state
    current_ecod_version: str
    total_proteins_tracked: int
    total_domains_classified: int
    total_proteins_classified: int
    total_proteins_pending: int

    # PDB state (from /usr2/pdb/data/status/)
    latest_pdb_week: str
    total_pdb_chains_current: int

    # Gaps
    missing_chains: int  # In PDB but not tracked in ECOD
    unclassified_chains: int  # Tracked but not classified

    # Special cases
    nonclassifiable_chains: int  # Tracked as non-classifiable
    nonclassifiable_breakdown: Dict[str, int]  # By type (peptide, etc.)

    # Week classification
    update_weeks_pending: List[str]  # Weeks after last classified
    repair_weeks_incomplete: List[str]  # Weeks before last with gaps


@dataclass
class NonClassifiableReason:
    """Reasons a chain/domain cannot be classified"""

    code: str  # Short code: peptide, expression_tag, coil, etc.
    description: str
    sequence_range: Optional[str]  # Which part of chain
    auto_detectable: bool  # Can be detected automatically

    # Modern replacement for special_architecture


class ECODSyncAssessor:
    """
    Assess ECOD-PDB synchronization state.

    Connects to both:
    - ECOD postgres database (ecod_commons schema)
    - PDB status files (/usr2/pdb/data/status/)
    """

    def __init__(
        self,
        db_host: str = "dione",
        db_port: int = 45000,
        db_name: str = "ecod_protein",
        db_user: str = "ecod",
        db_password: str = "ecod#badmin",
        pdb_status_base: str = "/usr2/pdb/data/status",
    ):
        """
        Initialize assessor.

        Args:
            db_host: PostgreSQL host
            db_port: PostgreSQL port
            db_name: Database name
            db_user: Database user
            db_password: Database password
            pdb_status_base: Base directory for PDB status files
        """
        self.db_config = {
            "host": db_host,
            "port": db_port,
            "database": db_name,
            "user": db_user,
            "password": db_password,
        }
        self.pdb_status_base = Path(pdb_status_base)

    def _get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(**self.db_config)

    def get_current_version(self) -> Dict:
        """
        Get current ECOD version information.

        Returns:
            Dict with version name and counts

        Note: Version system in ecod_commons is in flux.
        Active version is v293, but tracking is incomplete.
        """
        with self._get_db_connection() as conn:
            with conn.cursor() as cur:
                # Get total domain/protein counts (entire ecod_commons)
                cur.execute("""
                    SELECT
                        COUNT(DISTINCT d.id) as domain_count,
                        COUNT(DISTINCT d.protein_id) as protein_count
                    FROM ecod_commons.domains d;
                """)

                counts = cur.fetchone()
                domain_count, protein_count = counts if counts else (0, 0)

                return {
                    "version_name": "v293",  # Active version per user
                    "domain_count": domain_count,
                    "protein_count": protein_count,
                }

    def get_protein_stats(self) -> Dict:
        """
        Get protein tracking statistics.

        Returns:
            Dict with total proteins, PDB vs AlphaFold breakdown, etc.
        """
        with self._get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) as total_proteins,
                        COUNT(*) FILTER (WHERE source_type = 'pdb') as pdb_proteins,
                        COUNT(*) FILTER (WHERE source_type = 'afdb') as afdb_proteins,
                        COUNT(*) FILTER (WHERE domain_count > 0) as proteins_with_domains,
                        COUNT(*) FILTER (WHERE domain_count = 0) as proteins_without_domains,
                        COUNT(*) FILTER (WHERE is_multidomain = true) as multidomain_proteins
                    FROM ecod_commons.proteins;
                """)

                row = cur.fetchone()
                return {
                    "total_proteins": row[0],
                    "pdb_proteins": row[1],
                    "afdb_proteins": row[2],
                    "proteins_with_domains": row[3],
                    "proteins_without_domains": row[4],
                    "multidomain_proteins": row[5],
                }

    def get_domain_classification_stats(self) -> Dict:
        """
        Get domain classification statistics.

        Returns:
            Dict with classified/unclassified counts, methods, etc.
        """
        with self._get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) as total_domains,
                        COUNT(*) FILTER (WHERE classification_status = 'classified') as classified,
                        COUNT(*) FILTER (WHERE classification_status = 'unclassified') as unclassified,
                        COUNT(*) FILTER (WHERE classification_status = 'manual') as manual,
                        COUNT(*) FILTER (WHERE is_representative = true) as representatives,
                        COUNT(*) FILTER (WHERE is_manual_representative = true) as manual_reps,
                        COUNT(*) FILTER (WHERE is_provisional_representative = true) as provisional_reps
                    FROM ecod_commons.domains;
                """)

                row = cur.fetchone()
                return {
                    "total_domains": row[0],
                    "classified": row[1],
                    "unclassified": row[2],
                    "manual": row[3],
                    "representatives": row[4],
                    "manual_representatives": row[5],
                    "provisional_representatives": row[6],
                }

    def get_legacy_special_architecture_stats(self) -> Dict[str, int]:
        """
        Get statistics from legacy special_architecture table (public schema).

        This is the archaic system being replaced.

        Returns:
            Dict mapping type -> count
        """
        with self._get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COALESCE(type, 'unknown') as type,
                        COUNT(*) as count
                    FROM public.special_architecture
                    GROUP BY type
                    ORDER BY count DESC;
                """)

                return {row[0]: row[1] for row in cur.fetchall()}

    def find_pdb_weeks(self) -> List[str]:
        """
        Find all PDB weekly release directories.

        Returns:
            List of week identifiers (YYYYMMDD) sorted chronologically
        """
        if not self.pdb_status_base.exists():
            return []

        weeks = []
        for path in self.pdb_status_base.iterdir():
            if path.is_dir() and path.name.isdigit() and len(path.name) == 8:
                weeks.append(path.name)

        return sorted(weeks)

    def get_latest_pdb_week(self) -> Optional[str]:
        """
        Get the most recent PDB weekly release.

        Returns:
            Week identifier (YYYYMMDD) or None
        """
        weeks = self.find_pdb_weeks()
        return weeks[-1] if weeks else None

    def get_pdb_ids_for_week(self, week: str) -> Set[str]:
        """
        Get all PDB IDs from a specific week's added.pdb file.

        Args:
            week: Week identifier (YYYYMMDD)

        Returns:
            Set of PDB IDs (lowercase)
        """
        week_dir = self.pdb_status_base / week
        added_pdb = week_dir / "added.pdb"

        if not added_pdb.exists():
            return set()

        pdb_ids = set()
        with open(added_pdb) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    pdb_id = line[:4].lower()
                    if len(pdb_id) == 4:
                        pdb_ids.add(pdb_id)

        return pdb_ids

    def get_all_pdb_ids_from_ecod(self) -> Dict[str, int]:
        """
        Get all PDB IDs currently tracked in ECOD.

        Returns:
            Dict mapping PDB ID -> number of chains tracked
        """
        with self._get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pdb_id, COUNT(*) as chain_count
                    FROM ecod_commons.proteins
                    WHERE source_type = 'pdb' AND pdb_id IS NOT NULL
                    GROUP BY pdb_id
                    ORDER BY pdb_id;
                """)

                return {row[0]: row[1] for row in cur.fetchall()}

    def get_pdb_chains_from_ecod(self) -> Set[str]:
        """
        Get all PDB chain identifiers currently tracked in ECOD.

        Returns:
            Set of chain identifiers (e.g., "8s72_A")
        """
        with self._get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pdb_id, chain_id
                    FROM ecod_commons.proteins
                    WHERE source_type = 'pdb'
                      AND pdb_id IS NOT NULL
                      AND chain_id IS NOT NULL;
                """)

                return {f"{row[0]}_{row[1]}" for row in cur.fetchall()}

    def find_last_classified_week(self, coverage_threshold: float = 0.5) -> Optional[str]:
        """
        Find the last PDB week that was substantially classified.

        Args:
            coverage_threshold: Minimum fraction of entries in ECOD (default: 50%)

        Returns:
            Week identifier (YYYYMMDD) or None
        """
        all_weeks = self.find_pdb_weeks()
        ecod_pdb_ids = self.get_all_pdb_ids_from_ecod()

        # Scan backwards from most recent
        for week in reversed(all_weeks):
            pdb_ids_this_week = self.get_pdb_ids_for_week(week)
            if not pdb_ids_this_week:
                continue

            in_ecod = sum(1 for pid in pdb_ids_this_week if pid in ecod_pdb_ids)
            coverage = in_ecod / len(pdb_ids_this_week)

            if coverage >= coverage_threshold:
                return week

        return None

    def find_repair_weeks(
        self, last_classified_week: str, sample_rate: int = 10
    ) -> List[tuple]:
        """
        Find weeks before last classified that have gaps (need repair).

        Args:
            last_classified_week: Week identifier for last classified week
            sample_rate: Check every Nth week (default: 10)

        Returns:
            List of tuples: (week, total_entries, missing_entries, coverage_pct)
        """
        all_weeks = self.find_pdb_weeks()
        ecod_pdb_ids = self.get_all_pdb_ids_from_ecod()

        last_idx = all_weeks.index(last_classified_week)
        repair_weeks = []

        for i, week in enumerate(all_weeks[:last_idx]):
            if i % sample_rate != 0:
                continue

            pdb_ids_this_week = self.get_pdb_ids_for_week(week)
            if not pdb_ids_this_week:
                continue

            missing = [pid for pid in pdb_ids_this_week if pid not in ecod_pdb_ids]
            if missing:
                coverage_pct = (
                    (len(pdb_ids_this_week) - len(missing))
                    / len(pdb_ids_this_week)
                    * 100
                )
                repair_weeks.append(
                    (week, len(pdb_ids_this_week), len(missing), coverage_pct)
                )

        return repair_weeks

    def assess_synchronization(self) -> SyncStatus:
        """
        Perform complete ECOD-PDB synchronization assessment.

        Returns:
            SyncStatus object with all statistics
        """
        # Get ECOD state
        version = self.get_current_version()
        protein_stats = self.get_protein_stats()
        domain_stats = self.get_domain_classification_stats()
        special_arch = self.get_legacy_special_architecture_stats()

        # Get PDB state
        latest_week = self.get_latest_pdb_week()
        all_weeks = self.find_pdb_weeks()

        # Find last classified week
        print("Finding last classified PDB week...")
        last_classified = self.find_last_classified_week()

        # Determine update weeks and count entries
        update_weeks = []
        update_entries_count = 0
        if last_classified:
            last_idx = all_weeks.index(last_classified)
            update_weeks = all_weeks[last_idx + 1 :]

            print(f"Counting entries in {len(update_weeks)} update weeks...")
            for week in update_weeks:
                pdb_ids = self.get_pdb_ids_for_week(week)
                update_entries_count += len(pdb_ids)

        # Find repair weeks (sampled)
        print("Scanning for repair weeks (sampling every 10th week)...")
        repair_weeks = []
        if last_classified:
            repair_data = self.find_repair_weeks(last_classified, sample_rate=10)
            repair_weeks = [w[0] for w in repair_data]  # Just week identifiers

        status = SyncStatus(
            current_ecod_version=version["version_name"] if version else "unknown",
            total_proteins_tracked=protein_stats["total_proteins"],
            total_domains_classified=domain_stats["classified"],
            total_proteins_classified=protein_stats["proteins_with_domains"],
            total_proteins_pending=protein_stats["proteins_without_domains"],
            latest_pdb_week=latest_week or "unknown",
            total_pdb_chains_current=update_entries_count,  # Approximate
            missing_chains=update_entries_count,  # Update week entries
            unclassified_chains=domain_stats["unclassified"],
            nonclassifiable_chains=sum(special_arch.values()),
            nonclassifiable_breakdown=special_arch,
            update_weeks_pending=update_weeks,
            repair_weeks_incomplete=repair_weeks,
        )

        return status

    def generate_report(self) -> str:
        """
        Generate human-readable synchronization report.

        Returns:
            Formatted report string
        """
        status = self.assess_synchronization()

        report = f"""
ECOD-PDB Synchronization Assessment Report
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'=' * 70}

ECOD State:
-----------
Current Version: {status.current_ecod_version}
Total Proteins Tracked: {status.total_proteins_tracked:,}
  - With Classifications: {status.total_proteins_classified:,}
  - Pending Classification: {status.total_proteins_pending:,}

Total Domains Classified: {status.total_domains_classified:,}
Unclassified Domains: {status.unclassified_chains:,}

Non-Classifiable Chains: {status.nonclassifiable_chains:,}
Top Reasons:
"""

        # Top 10 non-classifiable reasons
        for reason, count in sorted(
            status.nonclassifiable_breakdown.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]:
            report += f"  - {reason}: {count:,}\n"

        # Determine last classified week from update weeks
        last_classified = "unknown"
        if status.update_weeks_pending:
            # Last classified is the week before first update week
            all_weeks = self.find_pdb_weeks()
            first_update_idx = all_weeks.index(status.update_weeks_pending[0])
            if first_update_idx > 0:
                last_classified = all_weeks[first_update_idx - 1]

        report += f"""
PDB State:
----------
Latest PDB Week: {status.latest_pdb_week}
Last Classified Week: {last_classified}
Weeks Since Last Classification: {len(status.update_weeks_pending)}

Synchronization Gaps:
---------------------
UPDATE WEEKS (new PDB releases needing classification):
  Weeks: {len(status.update_weeks_pending)}
  Date range: {status.update_weeks_pending[0] if status.update_weeks_pending else 'N/A'} to {status.update_weeks_pending[-1] if status.update_weeks_pending else 'N/A'}
  PDB entries needing classification: {status.missing_chains:,}

REPAIR WEEKS (historical gaps needing re-classification):
  Weeks with gaps (sampled): {len(status.repair_weeks_incomplete)}
  Sample weeks: {', '.join(status.repair_weeks_incomplete[:5])}{'...' if len(status.repair_weeks_incomplete) > 5 else ''}

TOTAL WORK NEEDED:
  Update week entries: ~{status.missing_chains:,} PDB entries
  Repair week entries: (requires full scan)

{'=' * 70}
"""

        return report


def main():
    """Command-line interface"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Assess ECOD-PDB synchronization"
    )
    parser.add_argument(
        "--pdb-status-dir",
        default="/usr2/pdb/data/status",
        help="PDB status directory",
    )
    parser.add_argument(
        "--output",
        help="Output file (default: stdout)",
    )

    args = parser.parse_args()

    assessor = ECODSyncAssessor(pdb_status_base=args.pdb_status_dir)
    report = assessor.generate_report()

    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        print(f"Report written to: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
