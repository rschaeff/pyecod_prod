# PDB Update Database - Deployment Status

**Date**: 2025-10-21
**Database**: `dione:45000/ecod_protein`
**Schema**: `pdb_update`
**Status**: ✅ **DEPLOYED AND OPERATIONAL**

---

## Deployment Summary

### What Was Deployed

#### 1. Core Schema (`sql/01_create_pdb_update_schema.sql`)

**Tables**:
- ✅ `weekly_release` - Tracks each weekly PDB release
- ✅ `chain_status` - Tracks individual protein chains through pipeline
- ✅ `repair_batch` - Tracks repair/reprocessing batches
- ✅ `repair_chain` - Tracks chains in repair batches

**Views**:
- ✅ `release_summary` - Batch statistics
- ✅ `chains_needing_hhsearch` - Chains needing HHsearch processing
- ✅ `failed_chains` - All failed chains across batches

#### 2. Enhanced Tracking (`sql/03_add_tracking_enhancements.sql`)

**New Columns on `chain_status`**:
- ✅ `ecod_status` - Tracks if chain exists in ECOD (not_in_ecod, in_current_ecod, in_previous_ecod, obsolete)
- ✅ `ecod_uid` - Foreign key to ECOD domain UID
- ✅ `ecod_version` - ECOD version containing this chain

**New Tables**:
- ✅ `unclassified_region` - Explicit tracking of unclassified residue ranges
- ✅ `classification_status` - LAST WEEK CLASSIFIED marker (singleton table)

**New Views**:
- ✅ `chains_with_unclassified_regions` - Chains with coverage gaps
- ✅ `new_releases` - Releases AFTER last classified week (NEW work)
- ✅ `repair_candidates` - Releases AT/BEFORE last classified week (REPAIR work)
- ✅ `release_classification_view` - Combined NEW/REPAIR view

**Functions**:
- ✅ `update_last_week_classified()` - Helper to update temporal marker

#### 3. Schema Fixes Applied

- ✅ Updated `valid_blast_status` constraint to allow `'not_needed'` (for peptides)
- ✅ Updated `valid_partition_status` constraint to allow `'not_needed'` (for peptides)

### Current Database State

**Connection**:
```
Host: dione
Port: 45000
Database: ecod_protein
Schema: pdb_update
User: ecod
```

**Data Loaded**:
- 1 weekly release synced: **2025-09-05**
- 1,660 chains tracked (1,632 classifiable + 28 peptides)
- All processing status from production batch

**Temporal Marker**:
```sql
LAST WEEK CLASSIFIED: 2025-09-05
ECOD VERSION: develop291
```

---

## Current Statistics (2025-09-05 Release)

### Release Summary
| Metric | Count | Percentage |
|--------|-------|------------|
| Total chains | 1,660 | 100% |
| Classifiable chains | 1,632 | 98.3% |
| Peptides (filtered) | 28 | 1.7% |
| Partitioning complete | 1,480 | 88.3% |
| Chains needing HHsearch | 56 | 3.4% |

### Partition Quality Distribution
| Quality | Chains | Avg Coverage | Avg Length |
|---------|--------|--------------|------------|
| **good** | 1,043 | 98.7% | 295 aa |
| **low_coverage** | 114 | 70.3% | 523 aa |
| **fragmentary** | 48 | 40.0% | 632 aa |
| **no_domains** | 275 | 0.0% | 291 aa |
| *(pending)* | 152 | - | 316 aa |

**Key Insights**:
- 63.9% of classifiable chains have good quality partitions (≥80% coverage)
- Low coverage and fragmentary chains tend to be longer (500+ residues)
- 275 chains yielded no domains (may be all-alpha, disordered, etc.)

---

## Queries to Answer Your Requirements

### 1. Which PDBs have protein chains?

```sql
SELECT wr.release_date, COUNT(*) as protein_chains
FROM pdb_update.weekly_release wr
JOIN pdb_update.chain_status cs ON wr.release_date = cs.release_date
WHERE cs.can_classify = true
GROUP BY wr.release_date
ORDER BY wr.release_date DESC;
```

**Current Result**: 2025-09-05 has 1,632 protein chains

### 2. Exist in ECOD?

```sql
SELECT ecod_status, COUNT(*) as count
FROM pdb_update.chain_status
WHERE can_classify = true
GROUP BY ecod_status;
```

**Current Result**:
- `not_in_ecod`: 1,632 (100% - because we haven't populated ECOD status yet)

**Next Step**: Need to implement ECOD status lookup (query `ecod_rep` or `ecod_commons` and update)

### 3. Has classification been attempted?

```sql
SELECT
    CASE
        WHEN blast_status != 'not_needed' THEN 'attempted'
        ELSE 'not attempted'
    END as classification_attempted,
    COUNT(*) as chains
FROM pdb_update.chain_status
WHERE can_classify = true
GROUP BY classification_attempted;
```

**Current Result**: All 1,632 classifiable chains have attempted classification

### 4. Unclassified regions remaining?

```sql
-- Chains with < 100% coverage (have unclassified regions)
SELECT
    pdb_id,
    chain_id,
    sequence_length,
    partition_coverage,
    (1.0 - partition_coverage) * sequence_length as unclassified_residues
FROM pdb_update.chain_status
WHERE partition_coverage < 1.0
  AND partition_coverage IS NOT NULL
ORDER BY unclassified_residues DESC
LIMIT 20;
```

**Current Result**: 589 chains (36%) have some unclassified residues

**Note**: Need to populate `unclassified_region` table with explicit residue ranges (not yet implemented)

### 5. Flagged as unclassifiable?

```sql
SELECT cannot_classify_reason, COUNT(*) as count
FROM pdb_update.chain_status
WHERE can_classify = false
GROUP BY cannot_classify_reason;
```

**Current Result**: 28 peptides (< 20 residues)

### 6. LAST WEEK CLASSIFIED marker

```sql
-- Current marker
SELECT * FROM pdb_update.classification_status;

-- New releases (need classification)
SELECT * FROM pdb_update.new_releases;

-- Repair candidates (already classified, may need rework)
SELECT * FROM pdb_update.repair_candidates;
```

**Current Marker**: 2025-09-05 (develop291)
**New Releases**: 0 (none after marker)
**Repair Candidates**: 1 (2025-09-05 itself)

---

## What's Working ✅

1. **Schema deployed** - All tables, views, constraints, indexes created
2. **Data syncing** - Can sync batch manifests to database
3. **Status tracking** - BLAST, HHsearch, partition status tracked per chain
4. **Quality assessment** - Partition quality and coverage metrics available
5. **Temporal marker** - LAST WEEK CLASSIFIED distinguishes new vs repair work
6. **Separation of concerns** - `pdb_update` (pyecod_prod) separate from `ecod_curation` (pyecod_vis)

## What's Not Yet Implemented ❌

1. **ECOD status population** - Need to query `ecod_rep`/`ecod_commons` and set `ecod_status`, `ecod_uid`, `ecod_version`
2. **Unclassified regions tracking** - Need to parse partition XMLs and populate `unclassified_region` table with explicit ranges
3. **Historical data** - Only have one week (2025-09-05), need 5-year backfill
4. **Auto-sync on batch completion** - Currently manual, could integrate into `WeeklyBatch.run_partitioning()`

---

## Code Changes Made

### Updated Files

1. **`src/pyecod_prod/database/sync.py`**:
   - Changed default connection to `dione:45000/ecod_protein`
   - Added password `ecod#badmin`
   - Fixed manifest parsing to handle new `batch_info` structure

2. **`scripts/sync_to_database.py`**:
   - Changed default host to `dione`
   - Changed default port to `45000`
   - Changed default database to `ecod_protein`
   - Added password `ecod#badmin`

3. **Database schema**:
   - Added `'not_needed'` to `valid_blast_status` constraint
   - Added `'not_needed'` to `valid_partition_status` constraint

### New Files Created

1. **`docs/PDB_RELEASE_TRACKING.md`** - Comprehensive documentation
2. **`sql/03_add_tracking_enhancements.sql`** - Enhanced tracking features
3. **`docs/DATABASE_DEPLOYMENT_STATUS.md`** - This file

---

## Usage Examples

### Check database status
```bash
source ~/.bashrc
python scripts/sync_to_database.py --status
```

### Sync a batch
```bash
python scripts/sync_to_database.py --batch /data/ecod/pdb_updates/batches/ecod_weekly_20250905
```

### Sync all batches
```bash
python scripts/sync_to_database.py --all --base-path /data/ecod/pdb_updates/batches
```

### Update LAST WEEK CLASSIFIED marker
```sql
SELECT pdb_update.update_last_week_classified(
    '2025-10-10',
    'develop292',
    'Completed October 2025 classification cycle'
);
```

### Query chains not in ECOD
```sql
SELECT pdb_id, chain_id, partition_quality, partition_coverage
FROM pdb_update.chain_status
WHERE ecod_status = 'not_in_ecod'
  AND can_classify = true
  AND partition_status = 'complete'
ORDER BY release_date DESC;
```

---

## Next Steps

### Immediate (This Week)

1. ✅ Deploy schema - **DONE**
2. ✅ Test sync with production batch - **DONE**
3. ⚠️ Implement ECOD status lookup
4. ⚠️ Test with additional weeks if available

### Short Term (Next Sprint)

1. ❌ Create script to populate ECOD status from `ecod_rep`
2. ❌ Create script to populate `unclassified_region` from partition XMLs
3. ❌ Create historical metadata loader for 5-year backfill
4. ❌ Integrate auto-sync into `WeeklyBatch` workflow

### Medium Term (Next Month)

1. ❌ Backfill historical PDB releases (5 years)
2. ❌ Create monitoring dashboards
3. ❌ Integrate with curation workflow
4. ❌ Build reporting tools for weekly updates

---

## Database Access

**Connection String**:
```
postgresql://ecod:ecod#badmin@dione:45000/ecod_protein
```

**psql Command**:
```bash
PGPASSWORD='ecod#badmin' psql -h dione -p 45000 -U ecod -d ecod_protein
```

**Python (using DatabaseSync)**:
```python
from pyecod_prod.database import DatabaseSync

# Uses default connection to dione
with DatabaseSync() as db:
    summary = db.get_batch_summary()
    print(summary)
```

---

## Success Metrics

✅ **Schema deployed**: All 13 tables/views created
✅ **Data synced**: 1,660 chains from 2025-09-05 release
✅ **Queries working**: All requirement queries functioning
✅ **Temporal tracking**: LAST WEEK CLASSIFIED marker operational
✅ **Separation maintained**: `pdb_update` separate from `ecod_curation`

**Overall Status**: 🟢 **System is operational and ready for production use**

---

## Support

- **Schema files**: `sql/01_create_pdb_update_schema.sql`, `sql/03_add_tracking_enhancements.sql`
- **Sync module**: `src/pyecod_prod/database/sync.py`
- **Sync script**: `scripts/sync_to_database.py`
- **Documentation**: `docs/PDB_RELEASE_TRACKING.md`, `docs/production_workflows.md`
