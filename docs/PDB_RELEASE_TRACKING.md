# PDB Release Tracking Schema

**Date**: 2025-10-21
**Status**: Schema designed and implemented, database deployment needed, gaps identified

---

## Overview

This document describes the database schema and workflows for tracking PDB weekly releases and their classification status in the ECOD pipeline. The goal is to maintain a comprehensive view of all protein structures from the last 5 years of PDB releases and their journey through the ECOD classification workflow.

---

## Requirements

### Core Tracking Needs

For each week of PDB releases (last 5 years), we need to track:

1. **Weekly release metadata**
   - Release date
   - Total structures added
   - Number of protein chains

2. **Per-chain classification status**
   - ✅ Does it have protein chains?
   - ✅ Has classification been attempted?
   - ⚠️ **Does it exist in ECOD?** (NOT YET TRACKED)
   - ⚠️ **Unclassified regions remaining?** (NOT YET TRACKED)
   - ✅ Flagged as unclassifiable?

3. **Temporal markers**
   - ⚠️ **LAST WEEK CLASSIFIED** marker (NOT YET TRACKED)
   - Distinguish "new" releases (after marker) vs "repair/reclassify" (before marker)

---

## Current Implementation

### Database Schema

**Location**: `sql/01_create_pdb_update_schema.sql`
**Status**: ✅ Implemented, ⚠️ Not yet deployed to production database

#### Tables

##### 1. `pdb_update.weekly_release`

Tracks each weekly PDB release processed by the pipeline.

```sql
CREATE TABLE pdb_update.weekly_release (
    release_date date PRIMARY KEY,              -- e.g., 2025-10-10
    pdb_status_path text NOT NULL,              -- /usr2/pdb/data/status/20251010
    batch_name text UNIQUE NOT NULL,            -- ecod_weekly_20251010
    batch_path text NOT NULL,                   -- /data/ecod/pdb_updates/batches/...

    -- Counts
    total_structures int,                       -- From added.pdb
    classifiable_chains int DEFAULT 0,          -- After filtering peptides/nucleic acids
    processed_structures int DEFAULT 0,         -- Completed

    -- Status tracking
    status text DEFAULT 'pending',              -- pending, processing, blast_complete, complete, failed

    -- Timestamps
    created_at timestamp DEFAULT now(),
    completed_at timestamp,
    notes text
);
```

**Coverage**: ✅ Handles weekly releases
**Missing**: ❌ No marker for "LAST WEEK CLASSIFIED"

##### 2. `pdb_update.chain_status`

Tracks individual protein chains through the classification pipeline.

```sql
CREATE TABLE pdb_update.chain_status (
    pdb_id text NOT NULL,
    chain_id text NOT NULL,
    release_date date NOT NULL REFERENCES pdb_update.weekly_release(release_date),

    -- Classification eligibility
    can_classify boolean DEFAULT true,          -- false for peptides, nucleic acids
    cannot_classify_reason text,                -- 'peptide', 'nucleic_acid', 'too_short'
    sequence_length int,

    -- BLAST processing
    blast_status text DEFAULT 'pending',        -- pending, running, complete, failed
    blast_coverage float,                       -- 0.0-1.0

    -- HHsearch processing
    needs_hhsearch boolean DEFAULT false,       -- true if blast_coverage < 0.90
    hhsearch_status text DEFAULT 'not_needed',  -- not_needed, pending, running, complete, failed

    -- Partitioning
    partition_status text DEFAULT 'pending',    -- pending, complete, failed
    partition_coverage float,                   -- Fraction covered by domains
    domain_count int,
    partition_quality text,                     -- 'good', 'low_coverage', 'fragmentary'

    -- File paths (relative to batch_path)
    fasta_path text,
    chain_blast_path text,
    domain_blast_path text,
    hhsearch_hhr_path text,
    summary_path text,
    partition_path text,

    PRIMARY KEY (pdb_id, chain_id, release_date)
);
```

**Coverage**:
- ✅ Has protein chains (via `can_classify` + `cannot_classify_reason`)
- ✅ Classification attempted (via `blast_status`, `hhsearch_status`, `partition_status`)
- ✅ Flagged as unclassifiable (via `can_classify = false`)
- ⚠️ Partial coverage for unclassified regions (via `partition_coverage`)

**Missing**:
- ❌ No link to ECOD (no foreign key or flag indicating "exists in current ECOD")
- ❌ No explicit "unclassified regions" tracking (regions 1-50, 150-200)
- ❌ No differentiation between "not yet classified" vs "classified but low coverage"

##### 3. `pdb_update.repair_batch`

Tracks reprocessing/repair batches.

```sql
CREATE TABLE pdb_update.repair_batch (
    batch_name text PRIMARY KEY,                -- ecod_repair_20251019
    batch_path text NOT NULL,
    created_at timestamp DEFAULT now(),
    completed_at timestamp,
    reason text,                                -- 'algorithm_update', 'error_fix', etc.
    status text DEFAULT 'pending',
    notes text
);
```

##### 4. `pdb_update.repair_chain`

Tracks chains in repair batches.

```sql
CREATE TABLE pdb_update.repair_chain (
    batch_name text NOT NULL REFERENCES pdb_update.repair_batch(batch_name),
    pdb_id text NOT NULL,
    chain_id text NOT NULL,
    rerun_blast boolean DEFAULT false,
    rerun_hhsearch boolean DEFAULT false,
    rerun_partition boolean DEFAULT true,
    status text DEFAULT 'pending',
    PRIMARY KEY (batch_name, pdb_id, chain_id)
);
```

#### Views

```sql
-- Summary of all weekly releases
pdb_update.release_summary

-- Chains needing HHsearch
pdb_update.chains_needing_hhsearch

-- Failed chains across all batches
pdb_update.failed_chains
```

### Python Implementation

**Module**: `src/pyecod_prod/database/sync.py`
**Status**: ✅ Fully implemented

**Key Functions**:
- `DatabaseSync.sync_weekly_batch()` - Sync batch manifest to database
- `DatabaseSync.sync_all_batches()` - Sync all batches from directory
- `DatabaseSync.get_batch_summary()` - Query batch statistics
- `DatabaseSync.get_chains_needing_hhsearch()` - Find chains needing HHsearch
- `DatabaseSync.get_failed_chains()` - Find all failed chains

**Script**: `scripts/sync_to_database.py`
**Usage**:
```bash
# Sync all batches
python scripts/sync_to_database.py --all --base-path /data/ecod/pdb_updates/batches

# Check database status
python scripts/sync_to_database.py --status
```

### Documentation

**Files**:
- `docs/production_workflows.md` - Complete workflow documentation
- `docs/CURATION_INTEGRATION_STATUS.md` - Curation workflow status
- `CLAUDE.md` - High-level overview

**Coverage**: ✅ Comprehensive documentation of current implementation

---

## Gap Analysis

### ✅ Implemented

| Requirement | Implementation | Location |
|-------------|----------------|----------|
| Weekly releases (5 years) | `weekly_release` table | `sql/01_create_pdb_update_schema.sql:15` |
| Has protein chains | `can_classify` boolean | `sql/01_create_pdb_update_schema.sql:48` |
| Classification attempted | `blast_status`, `partition_status` | `sql/01_create_pdb_update_schema.sql:53-67` |
| Flagged unclassifiable | `cannot_classify_reason` | `sql/01_create_pdb_update_schema.sql:49` |
| Unclassified regions (partial) | `partition_coverage` | `sql/01_create_pdb_update_schema.sql:69` |

### ❌ Missing / Not Yet Implemented

| Requirement | Status | Recommendation |
|-------------|--------|----------------|
| Exists in ECOD | ❌ Not tracked | Add `ecod_status` column + foreign key |
| Unclassified regions (explicit) | ❌ Not tracked | Add `unclassified_regions` table |
| LAST WEEK CLASSIFIED marker | ❌ Not tracked | Add `classification_status` table + config |

---

## Proposed Enhancements

### 1. Track ECOD Inclusion Status

**Purpose**: Know whether a chain already exists in the current ECOD release.

**Schema Addition**:
```sql
-- Add to pdb_update.chain_status
ALTER TABLE pdb_update.chain_status
ADD COLUMN ecod_status text DEFAULT 'not_in_ecod';
-- Values: 'not_in_ecod', 'in_current_ecod', 'in_previous_ecod', 'obsolete'

ALTER TABLE pdb_update.chain_status
ADD COLUMN ecod_uid integer;
-- Foreign key to ecod_commons.domain.uid (if exists)

ALTER TABLE pdb_update.chain_status
ADD COLUMN ecod_version text;
-- Which ECOD version contains this chain (e.g., 'develop291')

-- Add constraint
ALTER TABLE pdb_update.chain_status
ADD CONSTRAINT valid_ecod_status
CHECK (ecod_status IN ('not_in_ecod', 'in_current_ecod', 'in_previous_ecod', 'obsolete'));
```

**Implementation**:
1. Query `ecod_rep` or `ecod_commons` during sync
2. Match by PDB ID + chain ID
3. Set `ecod_status` and `ecod_uid` if found

### 2. Track Unclassified Regions Explicitly

**Purpose**: Identify specific residue ranges that remain unclassified after partitioning.

**Schema Addition**:
```sql
CREATE TABLE pdb_update.unclassified_region (
    pdb_id text NOT NULL,
    chain_id text NOT NULL,
    release_date date NOT NULL,
    region_start integer NOT NULL,
    region_end integer NOT NULL,
    region_length integer GENERATED ALWAYS AS (region_end - region_start + 1) STORED,
    reason text,
    -- Reasons: 'no_blast_hits', 'low_confidence', 'disorder_predicted',
    --          'linker', 'unstructured', 'analysis_pending'

    PRIMARY KEY (pdb_id, chain_id, release_date, region_start),
    FOREIGN KEY (pdb_id, chain_id, release_date)
        REFERENCES pdb_update.chain_status(pdb_id, chain_id, release_date)
);

-- Index for finding chains with unclassified regions
CREATE INDEX idx_unclassified_region_lookup
ON pdb_update.unclassified_region(pdb_id, chain_id, release_date);

-- View: Chains with unclassified regions
CREATE VIEW pdb_update.chains_with_unclassified_regions AS
SELECT
    pdb_id,
    chain_id,
    release_date,
    COUNT(*) as region_count,
    SUM(region_length) as total_unclassified_residues,
    ROUND(100.0 * SUM(region_length) / cs.sequence_length, 1) as percent_unclassified
FROM pdb_update.unclassified_region ur
JOIN pdb_update.chain_status cs USING (pdb_id, chain_id, release_date)
GROUP BY pdb_id, chain_id, release_date, cs.sequence_length
ORDER BY percent_unclassified DESC;
```

**Implementation**:
1. Parse partition XML to identify gaps in domain coverage
2. Insert unclassified regions during `partition_status` update
3. Query view to find chains needing manual curation

### 3. LAST WEEK CLASSIFIED Marker

**Purpose**: Distinguish new releases (need classification) from old releases (repair/reclassify).

**Schema Addition**:
```sql
CREATE TABLE pdb_update.classification_status (
    status_key text PRIMARY KEY DEFAULT 'current',
    last_week_classified date NOT NULL,
    last_ecod_version text NOT NULL,
    last_updated timestamp DEFAULT now(),
    notes text
);

-- Insert initial value
INSERT INTO pdb_update.classification_status
    (status_key, last_week_classified, last_ecod_version, notes)
VALUES
    ('current', '2025-09-05', 'develop291', 'Initial baseline from develop291 release');

-- View: New releases (after last classified)
CREATE VIEW pdb_update.new_releases AS
SELECT *
FROM pdb_update.weekly_release
WHERE release_date > (
    SELECT last_week_classified
    FROM pdb_update.classification_status
    WHERE status_key = 'current'
)
ORDER BY release_date;

-- View: Repair candidates (before last classified)
CREATE VIEW pdb_update.repair_candidates AS
SELECT *
FROM pdb_update.weekly_release
WHERE release_date <= (
    SELECT last_week_classified
    FROM pdb_update.classification_status
    WHERE status_key = 'current'
)
ORDER BY release_date DESC;
```

**Usage**:
```sql
-- Get new releases needing classification
SELECT * FROM pdb_update.new_releases;

-- Get older releases for repair/reclassification
SELECT * FROM pdb_update.repair_candidates;

-- Update marker after completing classification
UPDATE pdb_update.classification_status
SET last_week_classified = '2025-10-10',
    last_ecod_version = 'develop292',
    last_updated = now()
WHERE status_key = 'current';
```

---

## Database Deployment Status

### Schema Files Created

✅ `sql/01_create_pdb_update_schema.sql` - Main schema (complete)
✅ `sql/02_add_curation_metadata.sql` - Curation extensions (complete)

### Database Instances

| Database | Host | Port | Schema Status | Notes |
|----------|------|------|---------------|-------|
| `update_protein` | localhost | 5432 | ⚠️ Unknown | May not be created yet |
| `ecod_protein` | dione | 45000 | ✅ Deployed | Contains `ecod_curation` schema |

**Action Needed**:
1. Create `update_protein` database if not exists
2. Deploy `sql/01_create_pdb_update_schema.sql`
3. Verify with `scripts/sync_to_database.py --status`

### Deployment Commands

```bash
# Create database (if not exists)
createdb -U ecod update_protein

# Deploy schema
psql -U ecod -d update_protein -f sql/01_create_pdb_update_schema.sql

# Verify
psql -U ecod -d update_protein -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'pdb_update';"

# Test sync
python scripts/sync_to_database.py --status
```

---

## Historical Data Population

### Scope: Last 5 Years of PDB Releases

**Date Range**: ~2020-10-21 to 2025-10-21
**Estimated Releases**: ~260 weeks (5 years × 52 weeks/year)
**Estimated Structures**: ~260,000 total (assuming ~1,000 structures/week average)

### Data Sources

1. **PDB Status Files**: `/usr2/pdb/data/status/{YYYYMMDD}/added.pdb`
2. **Existing Batches**: `/data/ecod/pdb_updates/batches/ecod_weekly_*`
3. **ECOD Current Release**: `ecod_rep` database or XML dump

### Population Strategy

#### Option 1: Sync Existing Processed Batches

```bash
# Sync all completed batches (if they exist)
python scripts/sync_to_database.py \
    --all \
    --base-path /data/ecod/pdb_updates/batches

# Result: Only covers weeks already processed
```

**Pros**: Fast, data already validated
**Cons**: Likely missing most of 5-year history

#### Option 2: Process Historical Releases

```bash
# Process all weeks from 2020-10-21 to present
python scripts/process_update_weeks.py \
    --start-date 2020-10-21 \
    --submit \
    --base-path /data/ecod/pdb_updates/batches

# After completion, sync to database
python scripts/sync_to_database.py --all
```

**Pros**: Complete 5-year history
**Cons**: Time-intensive (weeks of compute)

#### Option 3: Hybrid - Metadata Only for Historical

Create script to populate basic metadata without full processing:

```python
# scripts/populate_historical_metadata.py
"""
Scan PDB status files for last 5 years and populate:
- pdb_update.weekly_release (metadata only)
- pdb_update.chain_status (basic info, no processing)
- Set ecod_status by querying ecod_rep
"""

# For each week 2020-2025:
#   1. Parse /usr2/pdb/data/status/{YYYYMMDD}/added.pdb
#   2. Extract chains from mmCIF files
#   3. Check if exists in ecod_rep (set ecod_status)
#   4. Insert records with status='pending'
#   5. Mark as ready for processing
```

**Pros**: Fast metadata population, identifies gaps
**Cons**: Still need to process for actual classification

### Recommended Approach

**Phase 1: Populate Metadata (1-2 days)**
```bash
# Create and run historical metadata loader
python scripts/populate_historical_metadata.py \
    --start-date 2020-10-21 \
    --end-date 2025-10-21 \
    --ecod-version develop291
```

**Phase 2: Backfill Classifications (weeks to months)**
```bash
# Process high-priority weeks (new structures not in ECOD)
python scripts/process_update_weeks.py \
    --start-date 2024-10-21 \
    --submit

# Lower priority: older weeks, repair batches
```

---

## Queries for Production Use

### Find New Structures Not in ECOD

```sql
SELECT wr.release_date, COUNT(*) as new_chains
FROM pdb_update.weekly_release wr
JOIN pdb_update.chain_status cs ON wr.release_date = cs.release_date
WHERE cs.ecod_status = 'not_in_ecod'
  AND cs.can_classify = true
  AND wr.release_date > (SELECT last_week_classified FROM pdb_update.classification_status WHERE status_key = 'current')
GROUP BY wr.release_date
ORDER BY wr.release_date DESC;
```

### Find Chains with Unclassified Regions

```sql
SELECT pdb_id, chain_id, release_date,
       partition_coverage,
       (1.0 - partition_coverage) * sequence_length as unclassified_residues
FROM pdb_update.chain_status
WHERE partition_status = 'complete'
  AND partition_coverage < 0.90
  AND can_classify = true
ORDER BY unclassified_residues DESC
LIMIT 100;
```

### Progress Tracking

```sql
-- Overall progress by week
SELECT
    release_date,
    status,
    classifiable_chains,
    processed_structures,
    ROUND(100.0 * processed_structures / NULLIF(classifiable_chains, 0), 1) as percent_complete
FROM pdb_update.weekly_release
WHERE release_date >= '2024-01-01'
ORDER BY release_date DESC;
```

---

## Next Steps

### Immediate (This Week)

1. ✅ Document current schema and gaps (this document)
2. ⚠️ Deploy schema to `update_protein` database
3. ⚠️ Test sync with existing batches
4. ⚠️ Verify database connectivity and queries

### Short Term (Next Sprint)

1. ❌ Implement ECOD status tracking (schema enhancement #1)
2. ❌ Implement unclassified regions table (schema enhancement #2)
3. ❌ Implement LAST WEEK CLASSIFIED marker (schema enhancement #3)
4. ❌ Create historical metadata loader script
5. ❌ Test with sample 5-year date range

### Medium Term (Next Month)

1. ❌ Populate complete 5-year metadata
2. ❌ Backfill classifications for high-priority weeks
3. ❌ Integrate with curation workflow
4. ❌ Create monitoring dashboards

---

## Files Reference

### Schema
- `sql/01_create_pdb_update_schema.sql` - Main schema
- `sql/02_add_curation_metadata.sql` - Curation extensions

### Code
- `src/pyecod_prod/database/sync.py` - Database sync module
- `scripts/sync_to_database.py` - Sync script
- `scripts/process_update_weeks.py` - Batch processing

### Documentation
- `docs/production_workflows.md` - Workflow documentation
- `docs/CURATION_INTEGRATION_STATUS.md` - Curation status
- `CLAUDE.md` - Project overview

---

## Summary

### What Exists ✅

- Comprehensive SQL schema for tracking weekly releases and chain status
- Python implementation for syncing batch manifests to database
- Documentation of workflows and processes
- Support for tracking classification attempts and quality

### What's Missing ❌

- **ECOD inclusion status** - No tracking of whether chains exist in current ECOD
- **Unclassified regions** - No explicit tracking of residue ranges without classification
- **LAST WEEK CLASSIFIED marker** - No temporal boundary for new vs repair work
- **Database deployment** - Schema exists but may not be deployed yet
- **Historical data** - No 5-year backfill yet

### Recommendations

1. **Deploy enhancements** - Add proposed schema extensions for ECOD status, unclassified regions, and classification marker
2. **Deploy database** - Create `update_protein` database and deploy schema
3. **Populate metadata** - Create historical loader for 5-year PDB release metadata
4. **Integrate workflow** - Connect classification pipeline to database tracking
5. **Create dashboards** - Build monitoring tools for production tracking
