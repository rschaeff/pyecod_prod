# Clustering Strategy for Historical Backfill

**Date**: 2025-10-21
**Status**: Decision needed for Phase 4 implementation

---

## Problem Statement

When backfilling 2 years of PDB data (~104 weeks, ~100K chains), clustering is **essential** - not optional. The question is: **how should we cluster**?

As noted: *"Looking at raw results is good for no one."*

---

## Option 1: Per-Week Clustering (Current Approach)

### Strategy

Cluster each weekly release independently at 70% identity:

```bash
# For each week:
cd-hit -i 2025-09-05_sequences.fa -o 2025-09-05_clusters_70 -c 0.70
cd-hit -i 2025-09-12_sequences.fa -o 2025-09-12_clusters_70 -c 0.70
# ... repeat for 104 weeks
```

### Database Schema

```sql
-- clustering_run: One row per week
INSERT INTO pdb_update.clustering_run (release_date, ...)
VALUES ('2025-09-05', ...), ('2025-09-12', ...), ...;

-- chain_status: Clustering fields relative to week's release
UPDATE pdb_update.chain_status
SET cluster_id = 5, is_representative = TRUE, ...
WHERE release_date = '2025-09-05';
```

### Pros ✅

1. **Separation by release**: Clear boundaries, easy to reason about
2. **Convenient when caught up**: Weekly workflow just works
3. **Resumable**: Can process weeks independently
4. **Incremental**: Add new weeks without re-clustering old data
5. **Schema already supports it**: `clustering_run.release_date` is the natural key

### Cons ❌

1. **Redundant clustering across weeks**: Chain X in week 1 and week 2 might be in different clusters
2. **Misses cross-week redundancy**: Identical chains across weeks not clustered together
3. **More work overall**: 104 separate CD-HIT runs instead of 1
4. **Less efficient for bulk operations**: Can't leverage clustering across entire dataset

### Typical Reduction

**Per week**: 30-40% reduction
- Week 1: 1,000 chains → 650 representatives (35% reduction)
- Week 2: 1,000 chains → 680 representatives (32% reduction)
- **Total**: 2,000 chains → 1,330 reps (33.5% reduction)

---

## Option 2: Global Clustering (All 2 Years)

### Strategy

Cluster entire 2-year dataset as one batch:

```bash
# Combine all sequences
cat 2023-10-21_to_2025-10-21/*.fa > all_2_years.fa

# Single CD-HIT run
cd-hit -i all_2_years.fa -o all_2_years_clusters_70 -c 0.70 -M 32000 -T 16
```

### Database Schema

```sql
-- Single clustering_run for all releases
INSERT INTO pdb_update.clustering_run (release_date, ...)
VALUES (NULL, ...);  -- NULL means global clustering

-- OR use sentinel date
VALUES ('2023-10-21', ...);  -- Start date of range

-- chain_status: Clustering fields across all releases
UPDATE pdb_update.chain_status
SET cluster_id = 42, is_representative = TRUE, ...
WHERE pdb_id = '8abc' AND chain_id = 'A'  -- No release_date filter
```

### Pros ✅

1. **Maximum deduplication**: Identical chains across weeks clustered together
2. **Better reduction**: 50-70% instead of 30-40%
3. **Single CD-HIT run**: Simpler workflow
4. **More efficient for bulk ops**: Process 50K reps instead of 70K

### Cons ❌

1. **Breaks per-week semantics**: Can't easily say "cluster for 2025-09-05"
2. **Not incrementally addable**: Adding new week requires re-clustering (expensive!)
3. **Schema changes needed**: `clustering_run.release_date` becomes range or NULL
4. **Complex propagation**: Chain in week 1 might have rep from week 52
5. **All-or-nothing**: Can't process weeks independently

### Typical Reduction

**Global**: 50-70% reduction
- 100,000 chains (2 years) → 35,000-50,000 representatives
- **Much better** than per-week

---

## Option 3: Hybrid Approach (Recommended)

### Strategy

**Initial backfill**: Global clustering
**Ongoing weekly**: Per-week clustering

```bash
# Phase 4 backfill (one-time)
cat 2023-10-21_to_2025-10-21/*.fa > historical_2y.fa
cd-hit -i historical_2y.fa -o historical_2y_70 -c 0.70

# Load with special marker
python scripts/load_clustering.py \
    --cluster-file historical_2y_70.clstr \
    --release-date 2023-10-21 \
    --threshold 0.70 \
    --method cd-hit-global

# Ongoing weeks (business as usual)
cd-hit -i 2025-10-28_sequences.fa -o 2025-10-28_70 -c 0.70
python scripts/load_clustering.py --release-date 2025-10-28 ...
```

### Database Schema

```sql
-- Support multiple clustering methods
ALTER TABLE pdb_update.clustering_run
ADD COLUMN is_global BOOLEAN DEFAULT FALSE;

-- Hybrid query: Check global first, then per-week
SELECT * FROM pdb_update.chain_status cs
LEFT JOIN pdb_update.clustering_run cr_global
    ON cr_global.is_global = TRUE
    AND cs.cluster_id IS NOT NULL
LEFT JOIN pdb_update.clustering_run cr_week
    ON cr_week.release_date = cs.release_date
WHERE cs.release_date = '2024-05-10';
```

### Pros ✅

1. **Best of both worlds**: Maximum reduction for backfill, convenient for ongoing
2. **One-time cost**: Re-clustering only for initial 2-year batch
3. **Future flexibility**: Weekly clustering after caught up
4. **Schema backward compatible**: Per-week clustering still works

### Cons ❌

1. **More complex**: Two clustering strategies to maintain
2. **Transition period**: Need to handle gap between global and per-week
3. **Schema changes**: Add `is_global` flag and query logic

---

## Performance Comparison

### Scenario: 2-Year Backfill (100K chains)

| Metric | Per-Week (Option 1) | Global (Option 2) | Hybrid (Option 3) |
|--------|---------------------|-------------------|-------------------|
| **CD-HIT runs** | 104 | 1 | 1 + ongoing weekly |
| **Representatives** | ~67,000 (33% reduction) | ~35,000-50,000 (50-65% reduction) | ~40,000 initially (60% reduction) |
| **BLAST jobs** | 67,000 | 40,000 | 40,000 |
| **Savings vs raw** | 33,000 jobs (33%) | 60,000 jobs (60%) | 60,000 jobs (60%) |
| **Compute time saved** | ~2 weeks | ~4 weeks | ~4 weeks |
| **Incrementally addable** | ✅ Yes | ❌ No | ⚠️ After transition |

---

## Recommendation

### For Phase 4 Historical Backfill

**Use Option 2 (Global Clustering)** for the 2-year backfill:

1. **Why**: Maximum efficiency for one-time bulk operation
2. **Pragmatic**: Don't need weekly semantics for historical data
3. **Simpler**: One clustering run, straightforward to implement

**Implementation**:
```bash
# Step 1: Backfill metadata (Phase 4a)
python scripts/backfill_metadata.py --start-date 2023-10-21 --end-date 2025-10-21

# Step 2: Extract all sequences
python scripts/extract_all_sequences.py \
    --start-date 2023-10-21 \
    --end-date 2025-10-21 \
    --output /data/ecod/clustering/historical_2y.fa

# Step 3: Run global CD-HIT (on big memory node)
cd-hit -i historical_2y.fa \
    -o historical_2y_70 \
    -c 0.70 \
    -n 5 \
    -M 64000 \
    -T 32 \
    -d 0

# Step 4: Load clustering (mark as global)
python scripts/load_clustering.py \
    --cluster-file historical_2y_70.clstr \
    --release-date 2023-10-21 \  # Sentinel: start of range
    --threshold 0.70 \
    --method cd-hit-global

# Step 5: Run ECOD status lookup (clustering-aware!)
python scripts/populate_ecod_status.py --all
```

### For Ongoing Weekly Production

**Use Option 1 (Per-Week)** after backfill is complete:

1. **Why**: Convenient, incrementally addable
2. **Acceptable reduction**: 30-40% still significant for ~1,600 chains/week
3. **Already implemented**: Clustering schema supports it

**Transition Strategy**:
- Mark historical clustering as `method='cd-hit-global'`
- New weeks use `method='cd-hit'` (default)
- `populate_ecod_status.py` already handles both (checks `clustering_run` table)

---

## Schema Updates Needed for Hybrid

### Minimal Changes

```sql
-- Add method field (already exists!)
-- ALTER TABLE pdb_update.clustering_run ADD COLUMN method VARCHAR(50);

-- Add is_global flag for clarity
ALTER TABLE pdb_update.clustering_run
ADD COLUMN is_global BOOLEAN DEFAULT FALSE;

-- Mark historical clustering
UPDATE pdb_update.clustering_run
SET is_global = TRUE
WHERE method = 'cd-hit-global';
```

### Query Updates

```python
# populate_ecod_status.py already checks clustering_run by release_date
# No changes needed! It will work for both global and per-week
```

---

## Decision Matrix

| Criterion | Per-Week | Global | Hybrid | Winner |
|-----------|----------|--------|--------|--------|
| **Max efficiency (backfill)** | 33% | **60%** | **60%** | Global/Hybrid |
| **Incrementally addable** | ✅ | ❌ | ⚠️ | Per-Week |
| **Simple to implement** | ✅ | **✅** | ❌ | Per-Week/Global |
| **Future flexibility** | ✅ | ❌ | **✅** | Hybrid |
| **Good for one-time bulk** | ❌ | **✅** | **✅** | Global/Hybrid |
| **Good for ongoing weekly** | **✅** | ❌ | **✅** | Hybrid |

---

## Final Recommendation

**For Phase 4**: Use **Option 2 (Global Clustering)** for simplicity and maximum efficiency

**Rationale**:
1. This is a **one-time** backfill operation
2. 60% reduction >> 33% reduction (saves ~4 weeks of compute)
3. Simpler to implement than hybrid
4. We can always switch to per-week for new data later

**After backfill**: Evaluate switching to per-week or continuing global clustering based on:
- How often we need to add new data
- Whether cross-week redundancy continues to matter
- Operational complexity tolerance

---

## Implementation Checklist

✅ **Schema supports both** (clustering_run table flexible)
✅ **populate_ecod_status.py is clustering-aware** (just deployed!)
⚠️ **Need script to extract all sequences** (for global clustering)
⚠️ **Need to decide on global clustering marker** (release_date sentinel vs NULL vs is_global flag)
⚠️ **Test CD-HIT on 100K sequences** (memory/time requirements)

---

## Next Steps

1. **User decision**: Confirm global clustering for Phase 4
2. **Create extraction script**: `scripts/extract_all_sequences.py`
3. **Test CD-HIT scalability**: Run on subset (10K chains) first
4. **Update load_clustering.py**: Support global clustering marker
5. **Document transition**: How to switch to per-week after backfill

---

**Last Updated**: 2025-10-21
**Status**: Awaiting user decision on clustering strategy
**Recommendation**: Global clustering for Phase 4 backfill
