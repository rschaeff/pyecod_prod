# Historical Backfill Status Report

**Date**: 2025-10-21
**Scope**: 2-year backfill (2023-10-21 to 2025-10-21)
**Status**: ⚡ **PHASE 4a IN PROGRESS** - Metadata backfill running
**Clustering Strategy**: **Global clustering at 70% identity (APPROVED)**

---

## Executive Summary

The 2-year historical backfill encompasses **103 PDB weekly releases** with an estimated **~170,000 chains**. Using **global clustering** will reduce computational workload by **60%**, saving approximately **100,000 BLAST jobs** and **8,500 compute hours**.

---

## Current Database State

### Loaded Data
- **Releases**: 1 (2025-09-05)
- **Total chains**: 1,660
- **Classifiable chains**: 1,632 (98.3%)
- **Peptides filtered**: 28 (1.7%)
- **ECOD status**:
  - In ECOD: 0
  - Not in ECOD: 1,660

### Backfill Needed
- **Additional releases**: 102
- **Period**: 2023-10-27 to 2025-10-10

---

## Backfill Scope Analysis

### Available PDB Releases

**Total releases**: 103 weekly releases
**Date range**: 2023-10-27 to 2025-10-10
**PDB entries**: 32,137 structures
**Average entries/week**: 312 structures

### Chain Estimates

Based on 2025-09-05 ratios (1,660 chains from 309 entries = 5.37× multiplier):

| Metric | Estimate |
|--------|----------|
| **Total chains** | ~172,575 |
| **Classifiable chains** | ~169,683 (98.3%) |
| **Peptides (filtered)** | ~2,892 (1.7%) |

### Sample Release Distribution

| Release Date | PDB Entries |
|--------------|-------------|
| 2023-10-27 | 275 |
| 2023-11-03 | 685 |
| 2023-11-10 | 242 |
| 2023-11-17 | 301 |
| 2023-11-24 | 325 |
| 2023-12-01 | 299 |
| 2023-12-08 | 274 |
| 2023-12-15 | 326 |
| 2023-12-22 | 303 |
| 2023-12-29 | 105 |
| ... | ... |
| **(103 releases total)** | **32,137** |

---

## Clustering Strategy: Global @ 70% Identity

### Decision Rationale

✅ **APPROVED**: Use global clustering for 2-year backfill

**Why global clustering?**
1. **Maximum efficiency**: 60% reduction vs 33% with per-week
2. **One-time operation**: Historical data doesn't need incremental updates
3. **Computational savings**: ~100K fewer BLAST jobs
4. **Downstream benefits**: Reduces curation burden by presenting clustered results

**Key insight**: *"Clustering isn't optional with this level of backfill. Looking at raw results is good for no one."*

### Impact Analysis

| Metric | Without Clustering | With Global Clustering (60%) | Savings |
|--------|-------------------|------------------------------|---------|
| **BLAST jobs** | 169,683 | 67,873 | **101,810 jobs** |
| **HHsearch jobs** (40% need it) | 67,873 | 27,149 | **40,724 jobs** |
| **Total SLURM jobs** | 237,556 | 95,022 | **142,534 jobs (60%)** |
| **BLAST compute time** | ~14,140 hours | ~5,656 hours | **~8,484 hours** |
| **Total compute time** | ~35,350 hours | ~14,140 hours | **~21,210 hours** |

**Time saved**: ~21,000 hours = ~884 days of single-core compute = **~2.4 years saved**

### Clustering Workflow

```bash
# Phase 4a: Backfill Metadata (all 103 releases)
python scripts/backfill_metadata.py \
    --start-date 2023-10-27 \
    --end-date 2025-10-10

# Phase 4b: Extract all sequences into single FASTA
python scripts/extract_all_sequences.py \
    --start-date 2023-10-27 \
    --end-date 2025-10-10 \
    --output /data/ecod/clustering/historical_2y.fa

# Phase 4c: Run global CD-HIT (on big memory node)
cd-hit \
    -i /data/ecod/clustering/historical_2y.fa \
    -o /data/ecod/clustering/historical_2y_70 \
    -c 0.70 \
    -n 5 \
    -M 64000 \
    -T 32 \
    -d 0

# Phase 4d: Load clustering to database
python scripts/load_clustering.py \
    --cluster-file /data/ecod/clustering/historical_2y_70.clstr \
    --release-date 2023-10-27 \
    --threshold 0.70 \
    --method cd-hit-global

# Phase 4e: Populate ECOD status (clustering-aware!)
python scripts/populate_ecod_status.py --all
```

---

## Implementation Phases

### Phase 1: ECOD Status Lookup ✅ COMPLETE
- Script updated with clustering awareness
- Tested on 2025-09-05 batch
- Ready for production use
- **File**: `scripts/populate_ecod_status.py`

### Phase 2: Unclassified Region Extraction ⏳ NEXT
- Extract regions not covered by ECOD
- Identify chains needing classification

### Phase 3: Curation Load Testing ⏳ PENDING
- Load sample data to ecod_curation
- Validate pyecod_vis integration

### Phase 4: Historical Backfill ⚡ IN PROGRESS
**Sub-phases**:
- **4a**: ⚡ **IN PROGRESS** - Backfill metadata (103 releases)
  - Script: `scripts/backfill_metadata.py`
  - Started: 2025-10-21 17:44 UTC
  - Progress: Release 8/103
  - ETA: ~4-5 hours (completes ~22:00 UTC)
  - Log: `/tmp/backfill_metadata.log`
- **4b**: ⏳ NEXT - Extract all sequences to single FASTA
- **4c**: ⏳ PENDING - Run global CD-HIT clustering
- **4d**: ⏳ PENDING - Load clustering to database
- **4e**: ⏳ PENDING - Run clustering-aware ECOD status lookup
- **4f**: ⏳ PENDING - Extract unclassified regions
- **4g**: ⏳ PENDING - Run BLAST/HHsearch on cluster representatives
- **4h**: ⏳ PENDING - Generate summaries and partitions
- **4i**: ⏳ PENDING - Load to curation database

---

## ECOD Coverage Expectations

### Hypothesis

Based on ECOD's comprehensive coverage:
- **ecod_commons**: 2.7M domains across 380K+ proteins
- **Expected ECOD match rate**: 40-70% of chains
- **Remaining chains**: New structures needing classification

### Validation Strategy

After Phase 4e (ECOD status lookup):
```sql
SELECT
    ecod_status,
    COUNT(*) as chains,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as percent
FROM pdb_update.chain_status
WHERE release_date BETWEEN '2023-10-27' AND '2025-10-10'
  AND can_classify = TRUE
GROUP BY ecod_status
ORDER BY chains DESC;
```

**Expected distribution**:
- `in_current_ecod`: 40-70% (already classified)
- `not_in_ecod`: 30-60% (need classification)

---

## Compute Resource Planning

### Memory Requirements

**CD-HIT global clustering**:
- Input: ~170K sequences
- Estimated memory: 32-64GB
- Recommended node: 96GB partition
- Runtime: 2-8 hours (depends on sequence lengths)

### SLURM Job Arrays

**After clustering (processing representatives only)**:
- BLAST array jobs: ~68K (array limit: 500 concurrent)
- HHsearch array jobs: ~27K (array limit: 500 concurrent)
- Total runtime: ~7-14 days (with 500 concurrent jobs)

**Without clustering** (for comparison):
- BLAST array jobs: ~170K
- Would require multiple batches due to SLURM 1000-job array limit
- Total runtime: ~21-30 days

---

## Database Storage Estimates

### pdb_update Schema

**chain_status table**:
- Rows: ~170K chains
- Storage: ~50MB (minimal columns)

**clustering_run table**:
- Rows: 1 (global clustering)
- Storage: negligible

**cluster_member table**:
- Rows: ~170K (all chains)
- Storage: ~30MB

**Total pdb_update growth**: ~100MB

### ecod_curation Schema (future)

**protein table**:
- Rows: ~68K representatives (after clustering)
- Storage: ~20MB

**sequence_cluster table**:
- Rows: ~102K cluster relationships
- Storage: ~15MB

**Total ecod_curation growth**: ~50MB

---

## Risk Assessment

### Known Risks

1. **PDB status file availability**
   - Risk: Some weekly releases may be missing
   - Mitigation: Validate all 103 releases before starting
   - Impact: LOW (sample check showed good coverage)

2. **mmCIF file corruption**
   - Risk: Some structures may fail parsing
   - Mitigation: Error handling in parser, log failures
   - Impact: LOW (< 0.1% expected failure rate)

3. **CD-HIT memory overflow**
   - Risk: 170K sequences may exceed 64GB
   - Mitigation: Test on subset first, use 128GB node if needed
   - Impact: MEDIUM (can mitigate with larger node)

4. **SLURM quota limits**
   - Risk: 68K jobs may hit cluster quotas
   - Mitigation: Coordinate with cluster admin, stagger submissions
   - Impact: LOW (well within normal usage)

5. **Database connection limits**
   - Risk: Bulk updates may hit connection limits
   - Mitigation: Batch commits, connection pooling
   - Impact: LOW (scripts use single connection)

### Mitigation Strategy

**Incremental validation**:
1. Test backfill on 1 week first
2. Test clustering on 10K chains subset
3. Test ECOD status lookup on clustered data
4. Run full backfill after validation

---

## Success Criteria

### Phase 4 Completion Criteria

✅ **Metadata loaded**: All 103 releases in weekly_release table
✅ **Chains extracted**: ~170K chains in chain_status table
✅ **Clustering complete**: 1 global clustering_run record, ~68K representatives
✅ **ECOD status populated**: All chains have ecod_status values
✅ **Coverage validated**: 40-70% in_current_ecod
✅ **Unclassified regions extracted**: Ready for BLAST/HHsearch
✅ **Quality checks pass**: < 1% parsing failures, no data corruption

---

## Next Steps

### Completed ✅

1. ✅ **Clustering strategy decision** - APPROVED (global clustering)
2. ✅ **Created backfill_metadata.py** - Script to populate weekly_release and chain_status
3. ✅ **Tested backfill script** - Single week + 3-week validation successful
4. ✅ **Started Phase 4a** - Full metadata backfill running in background

### In Progress ⚡

5. ⚡ **Phase 4a: Metadata backfill** - Processing 103 releases (~4-5 hours)
   - Monitor: `tail -f /tmp/backfill_metadata.log`
   - ETA: 2025-10-21 22:00 UTC

### Next (After Phase 4a Completes)

6. ⏳ **Verify backfill completion** - Check all 103 releases loaded
7. ⏳ **Create extract_all_sequences.py** - Script to generate global FASTA for clustering
8. ⏳ **Test CD-HIT on 10K subset** - Validate memory/performance requirements
9. ⏳ **Run Phase 4b-4c** - Extract sequences + global clustering
10. ⏳ **Run Phase 4d-4e** - Load clustering + ECOD status lookup
11. ⏳ **Analyze ECOD coverage** - Determine what percentage already classified

### Medium-Term (Next Week)

12. Complete BLAST/HHsearch workflow on cluster representatives
13. Generate summaries and partitions
14. Load to curation database
15. Validate with pyecod_vis integration

---

## References

- **Clustering schema**: `sql/04_add_clustering_support.sql`
- **Clustering strategy analysis**: `docs/CLUSTERING_STRATEGY.md`
- **Phase 1 test results**: `docs/PHASE_1_TEST_RESULTS.md`
- **Clustering integration status**: `docs/CLUSTERING_INTEGRATION_STATUS.md`
- **PDB data location**: `/usr2/pdb/data/status/{YYYYMMDD}/added.pdb`
- **mmCIF files**: `/usr2/pdb/data/structures/divided/mmCIF/{mid}/{pdb_id}.cif.gz`

---

**Last Updated**: 2025-10-21 17:50 UTC
**Next Review**: After Phase 4a completion (~22:00 UTC)
**Status**: ⚡ Phase 4a metadata backfill in progress (Release 8/103)
