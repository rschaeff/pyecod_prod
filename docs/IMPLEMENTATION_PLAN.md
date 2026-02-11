# Complete System Implementation Plan
## PDB Update Tracking with ECOD Integration

**Date**: 2025-10-21
**Author**: AI Assistant (Claude)
**Status**: Draft for Review

---

## Executive Summary

This plan outlines the complete implementation of the PDB update tracking system with full ECOD integration. The system will:

1. **Track 5 years of PDB releases** (~260 weeks, ~260K structures)
2. **Populate ECOD inclusion status** by querying ecod_rep and ecod_commons
3. **Extract unclassified regions** by comparing domain assignments to PDB sequences
4. **Auto-sync** batch results to database during workflow execution
5. **Provide comprehensive reporting** for production classification status

---

## Phase 1: ECOD Status Lookup (Week 1-2)

### Objective
Populate `pdb_update.chain_status` columns (`ecod_status`, `ecod_version`) by querying existing ECOD databases.

### Data Sources and Hierarchy

**Critical Understanding**:
- **ecod_rep** = Authoritative hierarchy and ~30K representative domains
  - Low edit, high audit repository
  - Defines the ECOD hierarchy (T/H/X/F groups)
  - ~30K representative domains that define 2.7M total domains in ECOD
  - **In conflicts, ecod_rep ALWAYS wins**

- **ecod_commons** = Full classification clearinghouse (2.7M domains)
  - Contains all domains, including those derived from ecod_rep representatives
  - Receives accessioned domains from: pyecod_prod → pyecod_curation → QC → accession → ecod_commons
  - Working database for ongoing classification

**Important**: pyecod_prod and pyecod_mini generate domains consistent with ecod_rep hierarchy. There should be minimal/no conflicts between them and ecod_rep.

### Implementation Strategy

#### Approach 1: Query ecod_rep (Authoritative)

**Pros**:
- Represents official ECOD release
- Clean, well-defined structure
- Stable version tracking

**Cons**:
- Only includes already-accessioned domains
- Won't show recent work-in-progress

**Query Pattern**:
```sql
-- Match by PDB ID + chain ID
UPDATE pdb_update.chain_status cs
SET
    ecod_status = 'in_current_ecod',
    ecod_version = 'develop291'
FROM ecod_rep.domain d
JOIN ecod_rep.assembly a ON d.assembly_id = a.uid
WHERE cs.pdb_id = a.pdb
  AND cs.chain_id = d.chain_id
  AND cs.ecod_status = 'not_in_ecod';
```

#### Approach 2: Query ecod_commons (Active)

**Pros**:
- Includes work-in-progress
- Shows latest classification efforts
- More complete coverage

**Cons**:
- May include provisional/unverified assignments
- More complex schema

**Query Pattern**:
```sql
-- Match via pdb_chain_mappings
UPDATE pdb_update.chain_status cs
SET
    ecod_status = CASE
        WHEN d.classification_status = 'accessioned' THEN 'in_current_ecod'
        WHEN d.classification_status = 'pending' THEN 'in_previous_ecod'
        ELSE 'not_in_ecod'
    END,
    ecod_version = dv.version_name
FROM ecod_commons.domains d
JOIN ecod_commons.pdb_chain_mappings pcm ON d.protein_id = pcm.id
WHERE cs.pdb_id = pcm.pdb_id
  AND cs.chain_id = pcm.chain_id;
```

#### Recommended: Query ecod_commons Only

**Rationale**:
- ecod_commons contains ALL domains (including those from ecod_rep)
- ecod_rep contains only representative domains (~30K subset)
- No need for hybrid approach since ecod_commons is comprehensive
- Query ecod_commons to determine if chain exists in current ECOD

**Note**: If conflicts arise (unlikely), ecod_rep is authoritative. But for existence checking, ecod_commons is sufficient.

**Implementation**:
```python
# scripts/populate_ecod_status.py

def populate_ecod_status(release_date=None, connection_params=None):
    """
    Query ecod_commons to determine if chains exist in current ECOD.

    ecod_commons contains all domains (2.7M), including representatives from ecod_rep.
    """
    sql = """
    UPDATE pdb_update.chain_status cs
    SET
        ecod_status = CASE
            WHEN d.classification_status = 'accessioned' THEN 'in_current_ecod'
            WHEN d.classification_status = 'pending_accession' THEN 'in_previous_ecod'
            ELSE 'not_in_ecod'
        END,
        ecod_version = v.version_name
    FROM ecod_commons.domains d
    JOIN ecod_commons.pdb_chain_mappings pcm ON d.protein_id = pcm.protein_id
    LEFT JOIN ecod_commons.versions v ON d.version_id = v.id
    WHERE cs.pdb_id = pcm.pdb_id
      AND cs.chain_id = pcm.chain_id
      AND (cs.release_date = %s OR %s IS NULL)
      AND cs.ecod_status = 'not_in_ecod'
    RETURNING cs.pdb_id, cs.chain_id, cs.ecod_status
    """

    conn = psycopg2.connect(**connection_params)
    cursor = conn.cursor()

    cursor.execute(sql, (release_date, release_date))
    results = cursor.fetchall()

    conn.commit()

    logger.info(f"Updated {len(results)} chains with ECOD status")

    # Log statistics
    in_ecod = sum(1 for r in results if r[3] == 'in_current_ecod')
    logger.info(f"  - in_current_ecod: {in_ecod}")
    logger.info(f"  - in_previous_ecod: {len(results) - in_ecod}")

    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--release-date', help='Specific release date (YYYY-MM-DD)')
    parser.add_argument('--all', action='store_true', help='Process all releases')
    parser.add_argument('--dry-run', action='store_true', help='Report only, no updates')

    args = parser.parse_args()

    if args.all:
        # Get all release dates
        releases = get_all_release_dates()
        for release_date in releases:
            logger.info(f"Processing {release_date}...")
            populate_ecod_status(release_date)
    else:
        populate_ecod_status(args.release_date)
```

**Script**: `scripts/populate_ecod_status.py`
**Usage**:
```bash
# Populate for specific release
python scripts/populate_ecod_status.py --release-date 2025-09-05

# Populate for all releases
python scripts/populate_ecod_status.py --all

# Dry run (report without updating)
python scripts/populate_ecod_status.py --all --dry-run
```

### Testing

```bash
# Test with 2025-09-05 batch
python scripts/populate_ecod_status.py --release-date 2025-09-05

# Verify results
PGPASSWORD='ecod#badmin' psql -h dione -p 45000 -U ecod -d ecod_protein <<EOF
SELECT ecod_status, COUNT(*)
FROM pdb_update.chain_status
WHERE release_date = '2025-09-05'
GROUP BY ecod_status;
EOF
```

**Expected Results**:
- Most 2025-09-05 chains should be `not_in_ecod` (new release)
- A few may be `in_current_ecod` if they're updates/replacements

### Effort Estimate
- Script development: 4-6 hours
- Testing & validation: 2-4 hours
- **Total: 1-2 days**

---

## Phase 2: Unclassified Region Extraction (Week 2-3)

### Objective
Populate `pdb_update.unclassified_region` table with explicit residue ranges that lack domain assignments.

### Data Sources

**PDB Sequences**:
- Source: `/usr2/pdb/data/structures/divided/mmCIF/{middle_2}/{pdb_id}.cif.gz`
- Extract SEQRES (canonical sequence) from mmCIF
- Already have `sequence` in `pdb_update.chain_status` (from manifest)

**Domain Assignments**:
- **From pyecod_prod**: partition XML files (partitions/*.partition.xml)
- **From ecod_commons**: `ecod_commons.domain_ranges` table (for existing ECOD domains)

### Strategy

#### Option 1: Parse Partition XMLs

**Source**: `/data/ecod/pdb_updates/batches/ecod_weekly_*/partitions/*.partition.xml`

**Approach**:
1. Parse partition XML to extract domain ranges
2. Build coverage bitmap (1 = covered, 0 = uncovered)
3. Identify contiguous uncovered regions
4. Insert into `unclassified_region` table

**Pros**:
- Directly reflects pyecod_prod results
- Includes all chains (new and old)
- Single source of truth

**Cons**:
- Requires parsing XML for every chain
- Slower for large batches

**Example**:
```python
def extract_unclassified_regions(partition_xml, sequence_length):
    """
    Parse partition XML and identify uncovered regions.

    Returns: List[(start, end, reason)]
    """
    import xml.etree.ElementTree as ET

    tree = ET.parse(partition_xml)
    root = tree.getroot()

    # Build coverage bitmap
    covered = [False] * sequence_length

    for domain in root.findall('.//domain'):
        range_str = domain.get('range')  # e.g., "10-150,200-300"
        for segment in range_str.split(','):
            start, end = map(int, segment.split('-'))
            for i in range(start-1, end):  # Convert to 0-indexed
                covered[i] = True

    # Find uncovered regions
    regions = []
    in_region = False
    region_start = None

    for i, is_covered in enumerate(covered):
        if not is_covered and not in_region:
            # Start of uncovered region
            in_region = True
            region_start = i + 1  # Convert to 1-indexed
        elif is_covered and in_region:
            # End of uncovered region
            regions.append((region_start, i, 'no_domain_assigned'))
            in_region = False

    # Handle region extending to end
    if in_region:
        regions.append((region_start, sequence_length, 'no_domain_assigned'))

    return regions
```

#### Option 2: Query ecod_commons.domain_ranges

**Source**: `ecod_commons.domain_ranges` (for chains already in ECOD)

**Approach**:
1. Query ecod_commons for domain ranges
2. Compare to sequence length
3. Identify gaps

**Pros**:
- Fast database query
- Authoritative for existing ECOD chains

**Cons**:
- Only works for chains already in ecod_commons
- Doesn't cover new classifications

#### Recommended: Combined Approach

1. **Primary**: Parse partition XMLs for all chains with `partition_status = 'complete'`
2. **Fallback**: Query ecod_commons for chains with `ecod_status != 'not_in_ecod'` but no partition XML
3. **Reasoning assignment** (keep simple for initial implementation):
   - `fragment` - Main reason, from partition_quality = 'fragmentary'
   - `peptide` - From cannot_classify_reason = 'peptide'
   - `no_blast_hits` - If blast_coverage < 0.3 or null
   - `low_confidence` - If partition_quality = 'low_coverage'
   - `unclassified` - Default for other cases

**Future enhancements** (out of scope for now):
   - `linker` - Predicted linker regions
   - `disorder` - Intrinsic disorder predicted
   - `synthetic` - Synthetic/engineered sequences

### Implementation

**Script**: `scripts/populate_unclassified_regions.py`

```python
def populate_unclassified_regions(release_date, batch_path):
    """
    Extract and populate unclassified regions for a release.
    """
    conn = psycopg2.connect(...)
    cursor = conn.cursor()

    # Get chains with completed partitioning
    cursor.execute("""
        SELECT pdb_id, chain_id, sequence_length, partition_coverage,
               partition_quality, blast_coverage
        FROM pdb_update.chain_status
        WHERE release_date = %s
          AND partition_status = 'complete'
          AND partition_coverage < 1.0
    """, (release_date,))

    for row in cursor.fetchall():
        pdb_id, chain_id, seq_len, cov, qual, blast_cov = row

        # Parse partition XML
        partition_xml = f"{batch_path}/partitions/{pdb_id}_{chain_id}.partition.xml"

        if os.path.exists(partition_xml):
            regions = extract_unclassified_regions(partition_xml, seq_len)

            # Assign reason based on context
            for start, end, _ in regions:
                reason = determine_reason(blast_cov, qual)

                # Insert region
                cursor.execute("""
                    INSERT INTO pdb_update.unclassified_region
                        (pdb_id, chain_id, release_date, region_start, region_end, reason)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (pdb_id, chain_id, release_date, region_start)
                    DO UPDATE SET region_end = EXCLUDED.region_end, reason = EXCLUDED.reason
                """, (pdb_id, chain_id, release_date, start, end, reason))

        conn.commit()

def determine_reason(blast_coverage, partition_quality, cannot_classify_reason):
    """
    Assign reason for unclassified region.
    Keep simple: main reasons are fragment and peptide.
    """
    if cannot_classify_reason == 'peptide':
        return 'peptide'
    elif partition_quality == 'fragmentary':
        return 'fragment'
    elif blast_coverage is None or blast_coverage < 0.3:
        return 'no_blast_hits'
    elif partition_quality == 'low_coverage':
        return 'low_confidence'
    else:
        return 'unclassified'
```

**Usage**:
```bash
# Populate for specific release
python scripts/populate_unclassified_regions.py \
    --release-date 2025-09-05 \
    --batch-path /data/ecod/pdb_updates/batches/ecod_weekly_20250905

# Populate for all releases
python scripts/populate_unclassified_regions.py --all

# Dry run
python scripts/populate_unclassified_regions.py --all --dry-run
```

### Testing

```bash
# Test with 2025-09-05 batch
python scripts/populate_unclassified_regions.py \
    --release-date 2025-09-05 \
    --batch-path /data/ecod/pdb_updates/batches/ecod_weekly_20250905

# Verify results
PGPASSWORD='ecod#badmin' psql -h dione -p 45000 -U ecod -d ecod_protein <<EOF
-- Chains with unclassified regions
SELECT COUNT(*) FROM pdb_update.chains_with_unclassified_regions
WHERE release_date = '2025-09-05';

-- Distribution by reason
SELECT reason, COUNT(*), SUM(region_length) as total_residues
FROM pdb_update.unclassified_region
WHERE release_date = '2025-09-05'
GROUP BY reason;

-- Sample chains
SELECT * FROM pdb_update.chains_with_unclassified_regions
WHERE release_date = '2025-09-05'
ORDER BY percent_unclassified DESC
LIMIT 10;
EOF
```

### Effort Estimate
- Script development: 6-8 hours
- XML parsing validation: 2-3 hours
- Testing & edge cases: 3-4 hours
- **Total: 2-3 days**

---

## Phase 3: Auto-Sync Integration (Week 3)

### Objective
Automatically sync batch results to database during workflow execution.

### Integration Points

#### Option 1: Post-Partition Sync (Recommended)

**Location**: `src/pyecod_prod/batch/weekly_batch.py:run_partitioning()`

**Timing**: After all chains are partitioned, before workflow completes

**Approach**:
```python
def run_partitioning(self, sync_to_database=True):
    """Run partitioning and optionally sync to database"""

    # ... existing partitioning code ...

    if sync_to_database:
        logger.info("Syncing batch to database...")
        try:
            from pyecod_prod.database import DatabaseSync

            with DatabaseSync() as db_sync:
                db_sync.sync_weekly_batch(str(self.batch_path), overwrite=True)
                logger.info(f"✓ Synced {self.batch_name} to database")
        except Exception as e:
            logger.error(f"Failed to sync to database: {e}")
            # Don't fail the batch due to sync error
```

**Pros**:
- Single sync at end of workflow
- All data complete before sync
- Minimal workflow disruption

**Cons**:
- No intermediate status updates
- Sync failure means re-running manually

#### Option 2: Progressive Sync

**Location**: Multiple points in workflow

**Approach**:
1. Sync after BLAST completion
2. Sync after HHsearch completion
3. Sync after partition completion

**Pros**:
- Real-time status updates
- Can monitor progress during long runs

**Cons**:
- More complex integration
- Multiple database connections
- Potential for incomplete data

#### Recommended: Sync for New Releases Only

**Strategy**:
1. **Auto-sync for new releases** (after LAST WEEK CLASSIFIED marker)
2. **Manual sync for repair batches** (avoid futile cycles on unclassifiable chains)

**Rationale**:
- New releases: Need database tracking for monitoring progress
- Repair batches: May iterate multiple times; sync only when truly complete to avoid churning on chains that can't be classified

**Implementation**:
```python
class WeeklyBatch:
    def __init__(self, ..., auto_sync='auto'):
        """
        auto_sync options:
        - 'auto': Sync if this is a new release (after LAST_WEEK_CLASSIFIED)
        - True: Always sync
        - False: Never sync
        """
        self.auto_sync = auto_sync
        self._is_new_release = None

    def _should_sync(self):
        """Determine if batch should auto-sync to database"""
        if self.auto_sync is False:
            return False
        elif self.auto_sync is True:
            return True
        elif self.auto_sync == 'auto':
            # Check if this is a new release
            if self._is_new_release is None:
                self._is_new_release = self._check_if_new_release()
            return self._is_new_release
        else:
            return False

    def _check_if_new_release(self):
        """Query database to check if release_date > LAST_WEEK_CLASSIFIED"""
        try:
            from pyecod_prod.database import DatabaseSync
            with DatabaseSync() as db:
                conn = db.connect()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT release_date >
                        (SELECT last_week_classified FROM pdb_update.classification_status WHERE status_key = 'current')
                    FROM pdb_update.weekly_release
                    WHERE release_date = %s
                """, (self.release_date,))
                result = cursor.fetchone()
                return result[0] if result else True  # Default to True if not in DB yet
        except:
            return True  # Default to sync on error

    def _sync_if_enabled(self):
        """Sync to database if enabled"""
        if not self._should_sync():
            logger.info("Auto-sync disabled for this batch (repair/manual mode)")
            return

        try:
            from pyecod_prod.database import DatabaseSync
            with DatabaseSync() as db_sync:
                db_sync.sync_weekly_batch(str(self.batch_path), overwrite=True)
                logger.info(f"✓ Database synced: {self.batch_name}")
        except Exception as e:
            logger.warning(f"Database sync failed: {e}")

    def process_blast_results(self):
        # ... existing code ...
        self._sync_if_enabled(stage='blast')

    def process_hhsearch_results(self):
        # ... existing code ...
        self._sync_if_enabled(stage='hhsearch')

    def run_partitioning(self):
        # ... existing code ...
        self._sync_if_enabled(stage='partition')

    def run_complete_workflow(self, ...):
        # ... existing code ...
        self._sync_if_enabled()  # Final sync
```

**Usage**:
```python
# Default: auto-sync only for new releases
batch = WeeklyBatch(release_date="2025-10-19", ...)
batch.run_complete_workflow()

# Force sync (even for repair batches)
batch = WeeklyBatch(release_date="2025-10-19", auto_sync=True, ...)

# Disable auto-sync (manual control)
batch = WeeklyBatch(release_date="2025-10-19", auto_sync=False, ...)
```

### Configuration

Add to `WeeklyBatch` or global config:
```python
# src/pyecod_prod/config.py
DATABASE_SYNC_ENABLED = True
DATABASE_SYNC_PROGRESSIVE = False
DATABASE_SYNC_ON_ERROR = 'warn'  # 'warn', 'fail', 'ignore'
```

### Testing

```bash
# Test auto-sync with small batch
python scripts/run_small_test.py

# Verify database was updated
python scripts/sync_to_database.py --status

# Test with auto-sync disabled
python -c "
from pyecod_prod.batch.weekly_batch import WeeklyBatch
batch = WeeklyBatch(..., auto_sync=False)
batch.run_complete_workflow()
"
```

### Effort Estimate
- Code integration: 3-4 hours
- Testing (small/medium batches): 2-3 hours
- Error handling & logging: 1-2 hours
- **Total: 1 day**

---

## Phase 4: Historical Data Backfill (Week 4-8)

### Objective
Populate database with 5 years of PDB release history (~260 weeks).

### Scope Analysis

**Date Range**: 2023-10-21 to 2025-10-21 (2 years) - Initial scope
**Estimated Releases**: ~104 weeks (52 weeks/year × 2 years)
**Estimated Structures**: ~104,000 total (assuming ~1,000/week average)

**Long-term responsibility**:
- Ultimately responsible back to 2014 (and even 1970)
- Start with 2 years as proof of concept
- Expand to full historical range in future phases

**Data Availability**:
- PDB status files: `/usr2/pdb/data/status/{YYYYMMDD}/added.pdb`
- mmCIF files: `/usr2/pdb/data/structures/divided/mmCIF/`
- ECOD databases: ecod_rep, ecod_commons

### Strategy: Three-Tier Approach

#### Tier 1: Metadata-Only Population (Fast)

**Purpose**: Create skeleton records for all 260 weeks
**Source**: PDB status files only
**Time**: 1-2 days

**Process**:
1. Scan `/usr2/pdb/data/status/` for all dates 2020-10-21 to 2025-10-21
2. Parse `added.pdb` files to get PDB IDs
3. Parse mmCIF headers to get chains (no sequence extraction)
4. Insert into `pdb_update.weekly_release` and `pdb_update.chain_status`
5. Mark all as `status='pending'`

**Script**: `scripts/backfill_metadata.py`

```python
def backfill_metadata(start_date, end_date):
    """
    Populate metadata for all PDB releases in date range.
    """
    for release_date in get_pdb_release_dates(start_date, end_date):
        status_dir = f"/usr2/pdb/data/status/{release_date.strftime('%Y%m%d')}"
        added_file = f"{status_dir}/added.pdb"

        if not os.path.exists(added_file):
            continue

        # Parse added.pdb
        pdb_ids = parse_added_pdb(added_file)

        # For each PDB, extract chains from mmCIF
        chains = []
        for pdb_id in pdb_ids:
            mmcif_path = get_mmcif_path(pdb_id)
            chain_ids = extract_chains_from_mmcif(mmcif_path)
            chains.extend([(pdb_id, chain_id) for chain_id in chain_ids])

        # Insert weekly_release
        insert_weekly_release(release_date, len(pdb_ids), len(chains))

        # Insert chain_status (minimal data)
        insert_chain_status_bulk(release_date, chains, status='pending')
```

**Output**: Database populated with ~260 weeks, all marked `status='pending'`

#### Tier 2: ECOD Status Population (Medium)

**Purpose**: Identify which chains already exist in ECOD
**Source**: ecod_rep, ecod_commons
**Time**: 2-3 days

**Process**:
1. Run `scripts/populate_ecod_status.py --all`
2. Update `ecod_status`, `ecod_version` for all chains
3. Mark chains with `ecod_status != 'not_in_ecod'` as lower priority

**Output**: All chains labeled with ECOD inclusion status

#### Tier 3: Selective Processing (Slow)

**Purpose**: Actually classify high-priority chains
**Source**: Run full pyecod_prod workflow
**Time**: Weeks to months (depending on priority)

**Priority Criteria**:
1. **High**: Chains `not_in_ecod` from last 6 months
2. **Medium**: Chains `not_in_ecod` from 6-24 months ago
3. **Low**: Chains `not_in_ecod` from >24 months ago
4. **Skip**: Chains already `in_current_ecod`

**Process**:
```bash
# Process high-priority weeks (last 6 months)
python scripts/process_update_weeks.py \
    --start-date 2025-04-21 \
    --submit

# Process medium-priority (next 18 months)
python scripts/process_update_weeks.py \
    --start-date 2023-10-21 \
    --end-date 2025-04-21 \
    --max-batches 10 \
    --submit
```

### Implementation Plan

**Week 4**: Tier 1 - Metadata backfill
```bash
# Backfill 2 years of metadata (proof of concept)
python scripts/backfill_metadata.py \
    --start-date 2023-10-21 \
    --end-date 2025-10-21

# Verify
python scripts/sync_to_database.py --status
```

**Week 5**: Tier 2 - ECOD status population
```bash
# Populate ECOD status for all chains
python scripts/populate_ecod_status.py --all

# Verify
PGPASSWORD='ecod#badmin' psql -h dione -p 45000 -U ecod -d ecod_protein <<EOF
SELECT ecod_status, COUNT(*)
FROM pdb_update.chain_status
GROUP BY ecod_status;
EOF
```

**Weeks 6-8**: Tier 3 - Selective processing
```bash
# Identify new chains not in ECOD (focus on recent releases)
PGPASSWORD='ecod#badmin' psql -h dione -p 45000 -U ecod -d ecod_protein <<EOF
SELECT release_date, COUNT(*) as new_chains
FROM pdb_update.chain_status
WHERE ecod_status = 'not_in_ecod'
  AND can_classify = true
  AND release_date >= '2024-10-21'  -- Last 1 year
GROUP BY release_date
ORDER BY release_date DESC;
EOF

# Process recent weeks first (newest data)
python scripts/process_update_weeks.py \
    --start-date 2024-10-21 \
    --submit

# Caution: For repair batches, avoid futile cycles on unclassifiable chains
```

### Resource Requirements

**Storage** (2-year scope):
- Metadata only: ~40 MB (104 weeks × ~1000 chains × minimal data)
- With sequences: ~200 MB (add FASTA sequences)
- With results: ~20 GB (BLAST XMLs, HHsearch HHRs, partitions)

**Compute**:
- Metadata population: Negligible (local file parsing)
- ECOD status lookup: Minutes (database query)
- Full classification: Weeks (SLURM cluster time)

### Effort Estimate
- Metadata backfill script: 1 day
- ECOD status population: 0.5 day
- Testing & validation: 1 day
- Selective processing setup: 0.5 day
- **Total: 3 days development + weeks of compute**

---

## Phase 5: Monitoring & Reporting (Ongoing)

### Objective
Provide dashboards and reports for production tracking.

### Key Metrics

1. **Classification Progress**
   - Chains processed per week
   - Coverage by partition quality
   - Success/failure rates

2. **ECOD Integration**
   - New structures not in ECOD
   - Structures awaiting accession
   - Obsoleted/replaced structures

3. **Quality Assessment**
   - Low-coverage chains
   - No-domain chains
   - Fragmentary classifications

### Tools

#### SQL Views (Already Created)

```sql
-- Progress tracking
SELECT * FROM pdb_update.release_summary ORDER BY release_date DESC;

-- New work vs repair
SELECT * FROM pdb_update.release_classification_view;

-- Quality issues
SELECT * FROM pdb_update.chains_with_unclassified_regions
ORDER BY percent_unclassified DESC;
```

#### Reporting Script

**Script**: `scripts/generate_report.py`

**Output**:
- Text format (simple, readable)
- Saved to local directory: `reports/weekly_report_{date}.txt`
- Optionally emailed to user

```python
def generate_weekly_report(output_dir='reports', email=None):
    """Generate comprehensive weekly status report"""

    conn = DatabaseSync()
    timestamp = datetime.now().strftime('%Y%m%d')
    output_file = f"{output_dir}/weekly_report_{timestamp}.txt"

    report = []
    report.append("=" * 80)
    report.append("ECOD PRODUCTION WEEKLY REPORT")
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 80)

    # Overall statistics
    report.append("\nOVERALL STATISTICS")
    report.append("-" * 80)
    stats = conn.get_batch_summary()
    for batch in stats[:5]:  # Most recent 5 batches
        report.append(f"{batch['release_date']}: {batch['processed_structures']}/{batch['classifiable_chains']} chains ({batch['percent_complete']:.1f}%)")

    # New releases needing classification
    report.append("\nNEW RELEASES (AFTER LAST WEEK CLASSIFIED)")
    report.append("-" * 80)
    # Query pdb_update.new_releases ...

    # Chains not in ECOD
    report.append("\nCHAINS NOT IN ECOD (NEED CLASSIFICATION)")
    report.append("-" * 80)
    # Query chains with ecod_status = 'not_in_ecod' ...

    # Quality issues (fragments, peptides, low coverage)
    report.append("\nQUALITY ISSUES")
    report.append("-" * 80)
    # Query low_coverage, fragmentary, no_domains, peptides ...

    # Save to file
    os.makedirs(output_dir, exist_ok=True)
    with open(output_file, 'w') as f:
        f.write('\n'.join(report))

    print(f"Report saved to: {output_file}")

    # Email if requested
    if email:
        send_email(email, "ECOD Weekly Report", '\n'.join(report))
        print(f"Report emailed to: {email}")

    return output_file
```

**Usage**:
```bash
# Generate report (saved to reports/ directory)
python scripts/generate_report.py

# Generate and email
python scripts/generate_report.py --email user@example.com

# Cron job (weekly on Monday 9am)
0 9 * * 1 cd /home/rschaeff/dev/pyecod_prod && python scripts/generate_report.py --email user@example.com
```

### Dashboards (Future)

**Option 1**: pgAdmin queries
**Option 2**: Grafana + PostgreSQL
**Option 3**: Custom web app (Flask/Django)

### Effort Estimate
- Reporting script: 1 day
- Dashboard setup (optional): 2-3 days
- **Total: 1-3 days**

---

## Summary Timeline

| Phase | Task | Duration | Dependencies |
|-------|------|----------|--------------|
| **1** | ECOD Status Lookup | 1-2 days | Database deployed |
| **2** | Unclassified Region Extraction | 2-3 days | Phase 1 |
| **3** | Auto-Sync Integration | 1 day | Database deployed |
| **4a** | Metadata Backfill | 1-2 days | - |
| **4b** | ECOD Status for Historical | 0.5 day | Phase 1, 4a |
| **4c** | Selective Processing | Weeks (ongoing) | Phase 4a, 4b |
| **5** | Monitoring & Reporting | 1-3 days | All phases |

**Total Development Time**: ~2 weeks (excluding selective processing compute time)

---

## Implementation Order (Recommended)

### Sprint 1 (Week 1)
1. ✅ Deploy schema (DONE)
2. ✅ Test sync with existing batch (DONE)
3. Implement Phase 1: ECOD status lookup
4. Test with 2025-09-05 batch

### Sprint 2 (Week 2)
1. Implement Phase 2: Unclassified region extraction
2. Test with 2025-09-05 batch
3. Implement Phase 3: Auto-sync integration
4. End-to-end test with small batch

### Sprint 3 (Week 3)
1. Implement Phase 4a: Metadata backfill script
2. Run metadata backfill for 5 years
3. Implement Phase 4b: Populate ECOD status for all
4. Validate historical data

### Sprint 4 (Week 4)
1. Implement Phase 5: Reporting tools
2. Set up monitoring queries
3. Document workflows
4. Production deployment

### Ongoing
1. Run selective processing for high-priority weeks
2. Monitor progress via reports
3. Adjust priorities based on ECOD needs

---

## Success Criteria

### Phase 1
- ✅ 100% of chains in 2025-09-05 have `ecod_status` populated
- ✅ Query time < 5 seconds for full batch
- ✅ Logging shows which database(s) were queried

### Phase 2
- ✅ All chains with `partition_coverage < 1.0` have entries in `unclassified_region`
- ✅ Total unclassified residues matches (1.0 - coverage) × sequence_length
- ✅ `chains_with_unclassified_regions` view returns correct statistics

### Phase 3
- ✅ Batches auto-sync without manual intervention
- ✅ Sync failures log warnings but don't crash workflow
- ✅ Database status matches manifest after workflow completes

### Phase 4
- ✅ All 260 weeks from 2020-2025 in database
- ✅ ECOD status populated for all chains
- ✅ Priority classification list generated

### Phase 5
- ✅ Weekly reports generated automatically
- ✅ Queries run in < 10 seconds
- ✅ Stakeholders can access reports

---

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| ecod_rep schema changes | High | Low | Abstract queries, version check |
| mmCIF parsing failures | Medium | Medium | Error handling, logging, skip bad files |
| Database connection issues | High | Low | Retry logic, connection pooling |
| SLURM cluster downtime | Medium | Medium | Resumable workflow, queue monitoring |
| Storage exhaustion | High | Low | Monitor disk usage, archive old batches |
| 5-year backfill takes too long | Medium | High | Tier approach, prioritize recent data |

---

## Decisions Made (Based on Discussion)

1. **ECOD Status Priority**: ✅ RESOLVED
   - Query ecod_commons (contains all 2.7M domains)
   - ecod_rep is authoritative in conflicts, but ecod_commons is comprehensive
   - No hybrid approach needed

2. **Unclassified Region Reasons**: ✅ RESOLVED
   - Keep simple: `fragment`, `peptide` as main reasons
   - Others: `no_blast_hits`, `low_confidence`, `unclassified`
   - Future: `linker`, `disorder`, `synthetic` (out of scope for now)

3. **Historical Backfill Scope**: ✅ RESOLVED
   - Start with 2 years (2023-10-21 to 2025-10-21)
   - Ultimately responsible back to 2014 (or 1970), but later phases

4. **Auto-Sync Timing**: ✅ RESOLVED
   - Focus on newest releases (auto-sync for new, manual for repair)
   - Avoid futile cycles on unclassifiable chains in repair batches
   - Default: 'auto' (sync if release > LAST_WEEK_CLASSIFIED)

5. **Reporting**: ✅ RESOLVED
   - User receives reports
   - Text format, saved to `reports/` directory
   - Optional email delivery

---

## Next Steps

**Immediate** (after plan review):
1. Discuss and finalize approach for each phase
2. Prioritize phases (if timeline needs adjustment)
3. Begin Phase 1 implementation

**Questions to Resolve**:
1. Confirm ecod_rep and ecod_commons query patterns
2. Verify mmCIF parsing strategy for historical data
3. Decide on backfill scope (full 5 years vs partial)
4. Set up test/staging environment if needed

---

## Files to Create

### Phase 1
- `scripts/populate_ecod_status.py`
- `tests/test_ecod_status_lookup.py`

### Phase 2
- `scripts/populate_unclassified_regions.py`
- `src/pyecod_prod/parsers/partition_parser.py` (if not exists)
- `tests/test_unclassified_regions.py`

### Phase 3
- Modify: `src/pyecod_prod/batch/weekly_batch.py`
- Add: `src/pyecod_prod/config.py` (if not exists)
- `tests/test_auto_sync.py`

### Phase 4
- `scripts/backfill_metadata.py`
- `scripts/prioritize_processing.py`
- `tests/test_historical_backfill.py`

### Phase 5
- `scripts/generate_report.py`
- `sql/queries/weekly_stats.sql`
- `docs/MONITORING.md`

---

**End of Implementation Plan - Updated with Clustering Integration**

---

## Phase 0: Clustering Foundation (CRITICAL - Week 0)

### Objective
Establish CD-HIT 70% sequence clustering infrastructure in pdb_update schema to reduce processing workload and improve automation efficiency.

**This phase is FOUNDATIONAL** - it affects all subsequent phases and must be implemented first.

### Why Clustering Matters

**Workload Reduction**:
- Typical clustering reduces workload by 40-60%
- Instead of running BLAST/HHsearch on 1,600 chains, run on ~600-900 representatives
- Propagate results to cluster members (near-identical sequences)

**Data Flow** (Separation of Concerns):
- pyecod_prod (pdb_update): **GENERATES** clusters
- pyecod_vis (ecod_curation): **CONSUMES** clusters (does not generate its own)
- This is critical for maintaining separation of concerns

**Current Problem**:
- Clustering code exists in `scripts/run_production_week_with_cdhit.py`
- BUT clustering data goes to `ecod_curation` schema (WRONG - violates separation)
- `pdb_update.chain_status` has NO clustering fields
- Only tracked in manifest's `cluster_representative` field (limited)

### Schema Changes Required

**SQL File**: `sql/04_add_clustering_support.sql` (CREATED)

**Changes**:
1. Add clustering fields to `chain_status`:
   - `cluster_id` - Cluster identifier within release
   - `is_representative` - Boolean flag
   - `representative_pdb_id`, `representative_chain_id` - Link to representative
   - `sequence_identity_to_rep` - Percent identity to representative

2. Create `clustering_run` table:
   - Tracks each CD-HIT run (method, threshold, statistics)
   - Records efficiency metrics (reduction factor, cluster sizes)

3. Create `cluster_member` table:
   - Detailed membership tracking
   - Historical record of clustering

4. Create views:
   - `cluster_representatives` - All reps for a release
   - `cluster_members_needing_propagation` - Members whose reps are complete
   - `clustering_efficiency` - Reduction metrics
   - `cluster_summary` - Cluster composition

5. Create functions:
   - `get_cluster_representative()` - Get rep for any chain
   - `propagate_partition_to_cluster()` - Copy rep results to members

### Integration with Existing Workflow

**Script Updates Required**:

1. **`scripts/load_clustering.py`**:
   - Currently loads to `ecod_curation.sequence_cluster` (WRONG)
   - Update to load to `pdb_update.clustering_run` and `cluster_member`
   - Populate `chain_status` clustering fields

2. **`scripts/run_production_week_with_cdhit.py`**:
   - Already runs CD-HIT at 70% identity
   - Update to call updated `load_clustering.py`
   - Ensure clustering data goes to pdb_update

3. **`src/pyecod_prod/batch/weekly_batch.py`**:
   - Add clustering step to workflow
   - Filter BLAST/HHsearch jobs to representatives only
   - Propagate results to cluster members after partitioning

### Implementation Steps

**Step 1: Deploy Schema** (1 hour)
```bash
# Deploy clustering schema additions
PGPASSWORD='ecod#badmin' psql -h dione -p 45000 -U ecod -d ecod_protein \
    -f sql/04_add_clustering_support.sql

# Verify tables created
PGPASSWORD='ecod#badmin' psql -h dione -p 45000 -U ecod -d ecod_protein \
    -c "\\dt pdb_update.cluster*"
```

**Step 2: Update load_clustering.py** (2-3 hours)
```python
# scripts/load_clustering.py

def load_clustering_to_pdb_update(cluster_file, release_date, method='cd-hit', identity_threshold=0.70):
    """
    Load CD-HIT clustering results to pdb_update schema.

    Replaces loading to ecod_curation schema.
    """
    conn = psycopg2.connect(...)
    cursor = conn.cursor()

    # Parse .clstr file
    clusters = parse_cd_hit_clusters(cluster_file)

    # Insert clustering_run
    cursor.execute("""
        INSERT INTO pdb_update.clustering_run
            (release_date, method, identity_threshold, total_chains, classifiable_chains,
             total_clusters, representative_count, singleton_clusters, avg_cluster_size,
             max_cluster_size, cluster_file_path)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (release_date, method, identity_threshold, ...))

    clustering_run_id = cursor.fetchone()[0]

    # Insert cluster members
    for cluster_id, members in enumerate(clusters):
        representative = members[0]  # First member is representative

        for member in members:
            pdb_id, chain_id = parse_chain_key(member['chain_key'])
            is_rep = (member == representative)
            identity = member.get('identity', 1.0 if is_rep else None)

            # Insert to cluster_member
            cursor.execute("""
                INSERT INTO pdb_update.cluster_member
                    (clustering_run_id, cluster_id, pdb_id, chain_id, release_date,
                     is_representative, sequence_identity_to_rep)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (clustering_run_id, cluster_id, pdb_id, chain_id, release_date, is_rep, identity))

            # Update chain_status
            cursor.execute("""
                UPDATE pdb_update.chain_status
                SET cluster_id = %s,
                    is_representative = %s,
                    representative_pdb_id = %s,
                    representative_chain_id = %s,
                    sequence_identity_to_rep = %s
                WHERE pdb_id = %s AND chain_id = %s AND release_date = %s
            """, (cluster_id, is_rep,
                  representative['pdb_id'] if not is_rep else None,
                  representative['chain_id'] if not is_rep else None,
                  identity, pdb_id, chain_id, release_date))

    conn.commit()
    logger.info(f"Loaded {len(clusters)} clusters to pdb_update schema")
```

**Step 3: Test on Existing Batch** (1-2 hours)
```bash
# Test with 2025-09-05 batch
python scripts/load_clustering.py \
    --cluster-file /data/ecod/pdb_updates/batches/ecod_weekly_20250905/clustering/cdhit70.clstr \
    --release-date 2025-09-05

# Verify results
PGPASSWORD='ecod#badmin' psql -h dione -p 45000 -U ecod -d ecod_protein <<EOF
-- Check clustering efficiency
SELECT * FROM pdb_update.clustering_efficiency WHERE release_date = '2025-09-05';

-- Check representatives
SELECT COUNT(*) FROM pdb_update.cluster_representatives WHERE release_date = '2025-09-05';

-- Verify chain_status updated
SELECT is_representative, COUNT(*)
FROM pdb_update.chain_status
WHERE release_date = '2025-09-05'
GROUP BY is_representative;
EOF
```

**Step 4: Update Workflow Integration** (2-3 hours)
```python
# src/pyecod_prod/batch/weekly_batch.py

class WeeklyBatch:
    def run_complete_workflow(self, submit_blast=True, submit_hhsearch=True, use_clustering=True):
        """
        Run complete workflow with optional clustering.
        """
        # ... existing steps 1-2 (parse, generate FASTAs) ...

        # NEW STEP: Run clustering
        if use_clustering:
            self.run_clustering()

        # Step 3: Submit BLAST (filter to representatives if clustering enabled)
        if submit_blast:
            if use_clustering:
                # Only run BLAST on cluster representatives
                representatives = self.manifest.get_cluster_representatives()
                chain_filter = [f"{c['pdb_id']}_{c['chain_id']}" for c in representatives]
                self.run_blast(chain_filter=chain_filter)
            else:
                self.run_blast()

        # ... continue with HHsearch, partitioning ...

        # NEW: Propagate results to cluster members
        if use_clustering:
            self.propagate_to_cluster_members()

    def run_clustering(self):
        """Run CD-HIT clustering at 70% identity"""
        from pyecod_prod.clustering import ClusteringRunner

        runner = ClusteringRunner(
            fasta_dir=self.dirs.fastas_dir,
            output_dir=self.dirs.clustering_dir,
            identity_threshold=0.70
        )

        cluster_file = runner.run_clustering()

        # Load results to database
        from scripts.load_clustering import load_clustering_to_pdb_update
        load_clustering_to_pdb_update(cluster_file, self.release_date)

        # Update manifest
        clusters = runner.parse_clusters(cluster_file)
        self.manifest.update_clustering(clusters)

    def propagate_to_cluster_members(self):
        """Propagate partition results from representatives to cluster members"""
        logger.info("Propagating results to cluster members...")

        from pyecod_prod.database import DatabaseSync
        with DatabaseSync() as db:
            conn = db.connect()
            cursor = conn.cursor()

            # Get all representatives with completed partitioning
            cursor.execute("""
                SELECT pdb_id, chain_id, release_date
                FROM pdb_update.chain_status
                WHERE release_date = %s
                  AND is_representative = TRUE
                  AND partition_status = 'complete'
            """, (self.release_date,))

            propagated = 0
            for row in cursor.fetchall():
                pdb_id, chain_id, release_date = row

                # Use propagation function
                cursor.execute("""
                    SELECT pdb_update.propagate_partition_to_cluster(
                        %s, %s, %s
                    )
                """, (pdb_id, chain_id, release_date))

                count = cursor.fetchone()[0]
                propagated += count

            conn.commit()
            logger.info(f"Propagated results to {propagated} cluster members")
```

### Cascade Effects on Other Phases

**Phase 1: ECOD Status Lookup**
- Query ECOD status for representatives FIRST
- Propagate to cluster members
- Reduces database query load by 40-60%

**Phase 2: Unclassified Region Extraction**
- Extract from representative partitions
- Propagate regions to cluster members (or mark as "same as representative")
- Faster processing

**Phase 3: Auto-Sync Integration**
- Sync clustering data along with processing status
- Track clustering efficiency metrics

**Phase 4: Historical Backfill**
- Question: Should we cluster old data?
  - Option A: Yes - improves historical analysis
  - Option B: No - focus on new releases only
  - **Recommend**: Cluster for consistency, but low priority

**Phase 5: Monitoring & Reporting**
- Add clustering efficiency metrics to reports
- Show workload reduction statistics
- Track representative vs member processing

### Testing

```bash
# Deploy schema
PGPASSWORD='ecod#badmin' psql -h dione -p 45000 -U ecod -d ecod_protein \
    -f sql/04_add_clustering_support.sql

# Test clustering on 2025-09-05
python scripts/run_production_week_with_cdhit.py --release-date 2025-09-05

# Verify clustering in database
python -c "
from pyecod_prod.database import DatabaseSync
with DatabaseSync() as db:
    conn = db.connect()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM pdb_update.clustering_efficiency
        WHERE release_date = ''2025-09-05''
    ''')
    result = cursor.fetchone()
    print(f'Reduction: {result[9]}%')
    print(f'Representatives: {result[6]} / {result[4]} chains')
"
```

### Effort Estimate
- Schema deployment: 0.5 hour
- Update load_clustering.py: 2-3 hours
- Update workflow integration: 2-3 hours
- Testing: 1-2 hours
- **Total: 1 day**

### Success Criteria
- ✅ Schema deployed successfully
- ✅ Clustering data loads to pdb_update (NOT ecod_curation)
- ✅ chain_status has clustering fields populated
- ✅ Workflow runs BLAST/HHsearch on representatives only
- ✅ Results propagate to cluster members correctly
- ✅ Workload reduction matches expectations (40-60%)

---

## Updated Implementation Order

### Sprint 0 (IMMEDIATE - Day 1)
1. ✅ Deploy clustering schema (`sql/04_add_clustering_support.sql`)
2. Update `scripts/load_clustering.py` to target pdb_update
3. Test clustering on 2025-09-05 batch
4. Verify clustering data in database

### Sprint 1 (Week 1)
1. Update workflow integration in `weekly_batch.py`
2. Test end-to-end workflow with clustering
3. Implement Phase 1: ECOD status lookup (with clustering awareness)
4. Test Phase 1 on 2025-09-05

### Sprint 2 (Week 2)
1. Implement Phase 2: Unclassified region extraction (with clustering)
2. Test with 2025-09-05 batch
3. Implement Phase 3: Auto-sync (include clustering data)
4. End-to-end test with small batch

### Sprint 3 (Week 3)
1. Implement Phase 4a: Metadata backfill (decide on clustering for historical)
2. Run metadata backfill for 2 years
3. Implement Phase 4b: Populate ECOD status for all
4. Validate historical data

### Sprint 4 (Week 4)
1. Implement Phase 5: Reporting (include clustering metrics)
2. Set up monitoring queries
3. Document workflows
4. Production deployment

---

## Updated Files to Create/Modify

### Phase 0 (Clustering)
- ✅ **CREATE**: `sql/04_add_clustering_support.sql` (DONE)
- **MODIFY**: `scripts/load_clustering.py` (redirect to pdb_update)
- **MODIFY**: `src/pyecod_prod/batch/weekly_batch.py` (add clustering step)
- **CREATE**: `src/pyecod_prod/clustering/cluster_runner.py` (optional abstraction)
- **CREATE**: `tests/test_clustering_integration.py`

### Phase 1 (with clustering awareness)
- **MODIFY**: `scripts/populate_ecod_status.py` (process reps first)
- **CREATE**: `tests/test_ecod_status_with_clustering.py`

### Phase 2 (with clustering awareness)
- **MODIFY**: `scripts/populate_unclassified_regions.py` (process reps, propagate)
- **CREATE**: `tests/test_unclassified_regions_clustering.py`

### Phase 3 (sync clustering data)
- **MODIFY**: `src/pyecod_prod/database/sync.py` (sync clustering fields)
- **MODIFY**: `tests/test_auto_sync.py` (verify clustering synced)

### Phase 4 (historical clustering decision)
- **MODIFY**: `scripts/backfill_metadata.py` (optionally include clustering)
- **CREATE**: `scripts/cluster_historical.py` (if clustering old data)

### Phase 5 (clustering metrics)
- **MODIFY**: `scripts/generate_report.py` (add clustering efficiency section)
- **CREATE**: `sql/queries/clustering_stats.sql`

---

**End of Implementation Plan - Updated with Clustering Integration**

Ready for review and discussion!
