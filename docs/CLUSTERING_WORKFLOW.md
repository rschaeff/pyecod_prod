# Sequence Clustering for Efficient Curation

**Purpose**: Reduce curation workload by clustering redundant sequences and curating only representatives.

## Problem

PDB releases contain highly redundant sequences:
- 100 proteins in batch → maybe only 15-20 unique sequences at 70% identity
- Curating all 100 individually wastes time
- Most share identical domain architectures

## Solution

1. **Cluster sequences** at 70% identity (CD-HIT in pyecod_prod)
2. **Curate representatives only** (15-20 proteins instead of 100)
3. **Propagate decisions** to cluster members automatically

## Schema Support

### Tables

#### `sequence_cluster`
Stores clustering runs at different thresholds (70%, 90%, etc.)

```sql
SELECT * FROM ecod_curation.sequence_cluster;
```

| Field | Purpose |
|-------|---------|
| `cluster_name` | Unique identifier (e.g., "weekly_20250905_70pct") |
| `sequence_identity_threshold` | 0.70 for 70% identity |
| `total_proteins` | How many proteins in this clustering |
| `total_clusters` | How many clusters formed |
| `representative_count` | How many to curate (1 per cluster) |

#### `cluster_membership`
Maps proteins to clusters and representatives

```sql
-- Get all members of a cluster
SELECT * FROM ecod_curation.cluster_membership
WHERE representative_protein_id = 123;
```

| Field | Purpose |
|-------|---------|
| `protein_id` | Protein in ecod_curation |
| `is_representative` | True if this protein should be curated |
| `representative_protein_id` | Which representative this belongs to |
| `sequence_identity_to_rep` | % identity to representative |

#### `curation_propagation`
Audit trail of propagated curation decisions

```sql
-- What was propagated from rep to members?
SELECT * FROM ecod_curation.curation_propagation
WHERE source_protein_id = 123;
```

| Field | Purpose |
|-------|---------|
| `source_protein_id` | Representative that was manually curated |
| `target_protein_id` | Cluster member that received propagation |
| `domains_propagated` | How many domains copied |
| `f_groups_propagated` | How many F-groups assigned |

### Views

#### `cluster_representatives`
**What curators see**: Only representatives to curate

```sql
-- Show only proteins I need to curate
SELECT * FROM ecod_curation.cluster_representatives
WHERE cluster_name = 'weekly_20250905_70pct'
  AND curation_status = 'pending'
ORDER BY cluster_size DESC;  -- Curate largest clusters first
```

#### `cluster_members_detail`
**For verification**: What gets auto-curated when I approve a representative

```sql
-- When I curate 8s72_A, what else gets auto-curated?
SELECT member_source_id, sequence_identity_to_rep
FROM ecod_curation.cluster_members_detail
WHERE representative_source_id = '8s72_A';
```

#### `clustering_efficiency`
**Statistics**: How much work did clustering save?

```sql
SELECT * FROM ecod_curation.clustering_efficiency;
```

Example output:
```
Cluster: weekly_20250905_70pct
  Total proteins: 100
  Representatives to curate: 18
  Reduction: 82% (curate 18 instead of 100!)
```

## Workflow

### In pyecod_prod (Batch Processing)

#### 1. Run CD-HIT clustering

```bash
# After loading proteins to ecod_curation
cd /data/ecod/test_batches/ecod_weekly_20250905

# Extract sequences
python scripts/extract_sequences.py --output sequences.fasta

# Run CD-HIT at 70% identity
cd-hit -i sequences.fasta -o clusters_70 -c 0.70 -n 5 -M 16000 -T 8

# Load clustering results
python scripts/load_clustering.py \
  --cluster-file clusters_70.clstr \
  --threshold 0.70 \
  --name "weekly_20250905_70pct"
```

Output:
```
Clustering loaded successfully!
  Total clusters: 18
  Representatives loaded: 18
  Members loaded: 82
  Reduction: 82% (curate 18 instead of 100!)
```

#### 2. Check efficiency

```bash
python scripts/load_clustering.py --stats
```

### In pyecod_vis (Curation UI)

#### 1. Curate representatives only

**Queue view shows**: Only 18 proteins (representatives), not all 100

```sql
-- What pyecod_vis queries
SELECT * FROM ecod_curation.cluster_representatives
WHERE curation_status = 'pending'
ORDER BY priority DESC, cluster_size DESC;
```

UI shows:
```
8s72_A  [Representative of cluster with 6 members - curate this one to auto-curate 6 proteins]
8yl2_A  [Representative of cluster with 8 members - curate this one to auto-curate 8 proteins]
...
```

#### 2. Curator reviews representative

For **8s72_A**:
- View domain boundaries: 1-64
- Check evidence: BLAST hit e6wjcC1, evalue 0.0018
- Decision: Accept boundaries, assign F-group 382.1.1.7

#### 3. Propagation happens

**Option A: Automatic (recommended)**
When curator marks 8s72_A as "curated", backend:
1. Looks up cluster members (6 proteins)
2. Copies domain boundaries from 8s72_A
3. Copies F-group assignments
4. Marks members as `curation_status='curated'`, `curation_source='propagated'`
5. Records in `curation_propagation` table

**Option B: Manual verification**
Curator reviews propagation before confirming:
```
Curating 8s72_A will auto-apply to:
  - 8s72_N (95% identity) ✓
  - 8s72_H (88% identity) ✓
  - 8s72_L (87% identity) ✓
  - 8s72_X (89% identity) ✓
  - 8s72_Y (87% identity) ✓

[Approve and Propagate] [Cancel]
```

#### 4. Result

- **Manual effort**: Curated 1 protein (8s72_A)
- **Automatic gain**: 5 proteins auto-curated via propagation
- **Total curated**: 6 proteins
- **Time saved**: ~83% (5/6 proteins)

## Curation Propagation Logic

### What gets propagated?

1. **Domain boundaries** ✅
   - If sequences align well (>70% identity)
   - Boundaries should be highly conserved

2. **F-group assignments** ✅
   - Same fold → same F-group
   - Safe to propagate

3. **T/H/X groups** ✅ (already from BLAST)
   - Already assigned from evidence

4. **Non-domain regions** ⚠️ (maybe)
   - Disordered regions may differ
   - Linkers may vary in length
   - Safer to NOT propagate unless identical

### Validation checks before propagation

Before auto-curating cluster members, verify:

```python
def can_propagate(representative, member):
    """Check if curation can be safely propagated."""

    # 1. Sequence identity high enough?
    if member.sequence_identity_to_rep < 70:
        return False, "sequence identity too low"

    # 2. Similar sequence length?
    length_diff = abs(representative.sequence_length - member.sequence_length)
    if length_diff > 20:
        return False, "sequence length differs by >20 residues"

    # 3. Representative was manually curated (not auto-accepted)?
    if representative.curation_source != 'manual':
        return False, "representative not manually curated"

    return True, "ok"
```

## Views for pyecod_vis

### Queue View (with clustering)

```sql
-- Show representatives only, prioritized by impact
CREATE OR REPLACE VIEW ecod_curation.curation_queue_clustered AS
SELECT
  cr.protein_id,
  cr.source_id,
  cr.partition_coverage,
  cr.domain_count,
  cr.curation_status,
  cr.cluster_size,
  cr.cluster_size - 1 as will_autocurate,  -- How many members benefit
  q.priority,
  q.priority_reason,
  -- Boost priority if large cluster (more impact)
  CASE
    WHEN cr.cluster_size >= 10 THEN q.priority + 3
    WHEN cr.cluster_size >= 5 THEN q.priority + 2
    WHEN cr.cluster_size >= 3 THEN q.priority + 1
    ELSE q.priority
  END as adjusted_priority
FROM ecod_curation.cluster_representatives cr
LEFT JOIN ecod_curation.curation_queue q ON cr.protein_id = q.protein_id
WHERE cr.curation_status = 'pending'
ORDER BY adjusted_priority DESC, cr.cluster_size DESC;
```

This prioritizes:
1. High-priority issues (from original queue logic)
2. Large clusters (more bang for curator's buck)

### Example: Curation Impact

**Before clustering**:
- 100 proteins to curate
- Estimated time: 100 × 2 min = 200 minutes (3.3 hours)

**After clustering at 70%**:
- 18 representatives to curate
- 82 auto-curated via propagation
- Estimated time: 18 × 2 min = 36 minutes
- **Time saved: 164 minutes (82%)**

## Integration Points

### pyecod_prod responsibilities

1. **Run CD-HIT** on each batch
2. **Load clustering** to ecod_curation schema
3. **Provide script** for propagation (after curation)

### pyecod_vis responsibilities

1. **Show representatives** in queue (not all 100 proteins)
2. **Show cluster size** to curators ("this will auto-curate 6 proteins")
3. **Trigger propagation** when representative is curated
4. **Allow review** of what gets auto-curated before confirming

## Future Enhancements

### Phase 1 (Current)
- ✅ Schema for clustering
- ✅ Load CD-HIT results
- ✅ Views for representatives

### Phase 2
- Propagation script (pyecod_prod)
- UI for cluster preview (pyecod_vis)
- Validation before propagation

### Phase 3
- Multiple threshold support (70%, 90%, 95%)
- Manual cluster override ("don't propagate to this member")
- Cluster-based statistics and reports

## SQL Examples

### For pyecod_prod

```sql
-- Load 100 proteins to ecod_curation (already done)
-- Run CD-HIT (bash)
-- Load clustering results (load_clustering.py)

-- Check what was loaded
SELECT * FROM ecod_curation.clustering_efficiency;
```

### For pyecod_vis

```sql
-- Show curation queue (representatives only)
SELECT * FROM ecod_curation.cluster_representatives
WHERE curation_status = 'pending'
ORDER BY cluster_size DESC
LIMIT 20;

-- When curator selects 8s72_A, show impact
SELECT
  member_source_id,
  sequence_identity_to_rep,
  member_status
FROM ecod_curation.cluster_members_detail
WHERE representative_source_id = '8s72_A';

-- After curator approves, run propagation
-- (pyecod_prod script will do this)
```

## Summary

✅ **Schema ready** for sequence clustering workflow
✅ **Views ready** to show representatives in pyecod_vis
✅ **Loader script ready** to import CD-HIT results
⏳ **Propagation script** needed in pyecod_prod (Phase 2)

The schema now supports efficient curation via clustering, potentially reducing curator workload by 70-90%!
