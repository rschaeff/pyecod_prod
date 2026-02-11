# Historical Backfill Status Report

**Date**: 2025-10-28
**Scope**: 2-year backfill (2023-10-21 to 2025-10-21)
**Status**: 🔄 **PHASE 4j IN PROGRESS** - Structure preprocessing for curation interface (48% complete, 4,526/9,365 PDB files)
**Clustering Strategy**: **Global clustering at 70% identity (DEPLOYED)**

---

## Executive Summary

The 2-year historical backfill has been **successfully loaded, clustered, and BLASTed**. Using **global clustering at 70% identity** reduced the computational workload by **91.4%**, saving approximately **132,000 BLAST jobs** and **21,400 compute hours**.

**Current state**: BLAST workflow complete (9,656/9,656 representatives). Partitioning 97% complete (9,365/9,656), with 291 chains needing investigation/retry.

---

## Current Status

### ✅ Completed Phases

**Phase 4a: Metadata Backfill** ✅
- **103 releases loaded** (2023-10-27 to 2025-10-10)
- **197,777 total chains**, **193,119 classifiable**
- **Database**: All data in `pdb_update.chain_status`

**Phase 4b: Sequence Extraction** ✅
- **193,119 sequences** extracted to database
- **Table**: `pdb_update.sequence`
- **Export**: `all_chains.fasta` (52 MB)

**Phase 4c: Global Clustering** ✅
- **Method**: mmseqs2 at 70% identity
- **Date**: 2025-10-22
- **Result**: 193,119 → 16,574 representatives (**91.4% reduction**)
- **Avg cluster size**: 11.7 chains
- **Max cluster size**: 2,466 chains

**Phase 4d: Clustering Load to Database** ✅
- **Loaded**: `pdb_update.clustering_run`
- **Updated**: `chain_status` with clustering fields
- **Representatives**: 16,574 marked in database

**Phase 4e: ECOD Status Lookup** ✅
- **In ECOD**: 51,146 chains (26.5%)
- **Not in ECOD**: 141,973 chains (73.5%)
- **Clustering-aware**: Representatives processed first, then propagated

**Phase 4f: BLAST Target Selection** ✅
- **Initial**: 141,973 chains not in ECOD
- **After clustering**: 16,574 representatives
- **After ECOD filtering**: **9,656 BLAST targets**
- **Total reduction**: **95.0%** (from 193,119 to 9,656)

### ✅ Recently Completed

**Phase 4g: BLAST Workflow** ✅
- **Chain BLAST**: ✅ 100% complete (9,656/9,656)
  - Jobs: 267789-267798 (10 batches)
  - Runtime: ~4-6 hours
  - Database: chainwise100.develop291

- **Domain BLAST**: ✅ 100% complete (9,656/9,656)
  - Jobs: 271356, 272277, 273156, 274114, 275036, 275984, 276905
  - Runtime: ~4-6 hours
  - Database: ecod100.develop291

- **Summaries**: ✅ 100% complete (9,656/9,656)
  - Generated from chain + domain BLAST
  - Format: domain_summary.xml (per PYECOD_MINI_API_SPEC)

- **Partitions (BLAST-only)**: ✅ 97.0% complete (9,365/9,656)
  - Generated via pyecod_mini
  - Remaining: 291 chains (3.0%, under investigation)

### ✅ Recently Completed

**Phase 4h: HHsearch Workflow** ✅
- **Coverage Analysis**: ✅ Complete
  - 5,359 chains with ≥90% BLAST coverage (BLAST sufficient)
  - 4,297 chains with <90% coverage (needed HHsearch)
- **HHsearch Jobs**: ✅ Complete
  - Jobs: 318110, 318141-318144 (5 batches)
  - Completed: 4,038 chains (94.0%)
  - Failed: 259 chains (6.0% - timeouts)
  - Runtime: ~6-7 hours (2025-10-23 22:36 to ~05:00 CDT)
- **Failure Analysis**:
  - All failures: hhblits timeouts (30-min limit exceeded)
  - Failed chains: mean 1,244 residues (vs 241 for successful)
  - Range: 83-4,629 residues (very large multi-domain proteins)

**Phase 4i: HHsearch Validation Analysis** ✅
- **Bug Fix Validation**: v2.0.1 tested on 3,799 chains
- **Results**:
  - Chains improved: 31/3,799 (0.8%)
  - Average improvement: +0.3% coverage
  - No degradations observed
  - Top improvements: Up to +89% coverage for low-BLAST-coverage chains
- **Interpretation**:
  - Bug fix working correctly (HHsearch evidence now integrated)
  - Impact modest but significant for affected chains
  - High-quality evidence (no false positives)
  - Confirms two-pass strategy is effective for low-coverage chains
- **Data Location**: `/data/ecod/pdb_updates/backfill_2023_2025/blast/partitions_v2_0_1/`

### ⚡ In Progress

**Phase 4j: Structure Preprocessing** 🔄
- **Purpose**: Extract 9,365 chain PDB files for pyecod_vis 3D visualization
- **Job**: 327562 (SLURM array, 94 batches)
- **Started**: 2025-10-28
- **Progress**: 4,526/9,365 complete (48%)
- **Status**: Running smoothly, no errors
- **Output**: `/data/ecod/pdb_updates/backfill_2023_2025/blast/chain_pdbs/`
- **ETA**: 1-2 hours to completion
- **Script**: `scripts/preprocess_chain_structures.py`

### ⏳ Pending Phases

**Phase 4k: Curation Database Load** ⏳
- Load chain PDB files and metadata to ecod_curation schema
- Enable 3D visualization in pyecod_vis curation interface
- Estimated runtime: 1-2 hours

**Phase 4l: Evidence Propagation** ⏳
- Copy BLAST+HHsearch evidence from representatives to cluster members (176,545 chains)
- Run partition independently for each member (structures may differ slightly)
- Estimated runtime: ~50-100 hours (parallelized)

**Phase 4m: Production Database Load** ⏳
- Sync partition results to `pdb_update`
- Populate domain assignments
- Calculate coverage metrics
- Final validation and reporting

---

## Backfill Scope

### Releases Processed

**Total releases**: 103 weekly releases
**Date range**: 2023-10-27 to 2025-10-10
**PDB entries**: 32,137 structures
**Average entries/week**: 312 structures

### Chain Statistics

| Metric | Count |
|--------|-------|
| **Total chains** | 197,777 |
| **Classifiable chains** | 193,119 (97.6%) |
| **Peptides (filtered <20 residues)** | 4,658 (2.4%) |
| **In ECOD (already classified)** | 51,146 (26.5%) |
| **Not in ECOD (need classification)** | 141,973 (73.5%) |
| **Cluster representatives** | 16,574 (8.6%) |
| **Representatives not in ECOD** | 9,656 (5.0%) |

---

## Clustering Impact Analysis

### Global Clustering Results

**Method**: mmseqs2 (--min-seq-id 0.7, -c 0.8, --cov-mode 0)
**Date**: 2025-10-22
**Runtime**: ~2 hours (32 threads)

**Results**:
- **Input**: 193,119 sequences
- **Output**: 16,574 representatives (8.6%)
- **Reduction**: 91.4% (176,545 chains eliminated)
- **Singleton clusters**: 3,993 (24.1% of clusters)
- **Avg cluster size**: 11.7 chains
- **Max cluster size**: 2,466 chains

### Workload Reduction

| Metric | Without Clustering | With Clustering | Savings |
|--------|-------------------|-----------------|---------|
| **Initial chains** | 193,119 | 193,119 | — |
| **After ECOD filter** | 141,973 | 141,973 | — |
| **After clustering** | 141,973 | 9,656 | **93.2%** |
| **BLAST jobs** | 141,973 | 9,656 | **132,317 jobs** |
| **HHsearch jobs** (40%) | ~56,800 | ~3,860 | ~52,940 jobs |
| **Total SLURM jobs** | ~198,800 | ~13,500 | **185,300 jobs (93.2%)** |
| **Compute hours** | ~16,600 | ~1,100 | **~15,500 hours** |

**Time saved**: ~15,500 hours = ~646 days of single-core compute

---

## ECOD Coverage Analysis

### Distribution by Status

| ECOD Status | Chains | Percent |
|-------------|--------|---------|
| **not_in_ecod** | 141,973 | 73.5% |
| **in_current_ecod** | 51,146 | 26.5% |
| **in_previous_ecod** | 0 | 0.0% |

### Analysis

**Findings**:
- 26.5% of backfill chains already exist in ECOD
- This is lower than expected (predicted 40-70%)
- Possible reasons:
  - Backfill includes many recent structures (2024-2025)
  - ECOD database may not include latest PDB entries
  - Some chains may be in ECOD but under different identifiers

**Implications**:
- 73.5% of chains genuinely need classification
- High value for production pipeline (not duplicating existing work)
- Large classification effort ahead (~142K chains)

---

## BLAST Workflow Details

### File Structure

```
/data/ecod/pdb_updates/backfill_2023_2025/blast/
├── blast_targets.txt              # 9,656 targets
├── fastas/*.fa                    # 9,656 FASTA files
├── chain_blast/*.chain_blast.xml  # ✅ 9,656 complete
├── domain_blast/*.domain_blast.xml # 🔄 ~717/9,656 (7.4%)
├── summaries/*.summary.xml        # ✅ 9,657 complete
├── partitions/*.partition.xml     # ✅ 9,366/9,656 (96.9%)
├── slurm_logs/                    # Job logs
├── submit_*.sh                    # SLURM submission scripts
└── README.md                      # Workflow documentation
```

### Progress Monitoring

**Check progress**:
```bash
cd /data/ecod/pdb_updates/backfill_2023_2025/blast
./check_blast_progress.sh
```

**Check SLURM jobs**:
```bash
squeue -u $USER | grep -E "(chain_blast|domain_blast|summary|partition)"
```

---

## Database State

### pdb_update Schema

**Tables populated**:
- `weekly_release`: 103 releases
- `chain_status`: 197,777 chains with metadata
- `sequence`: 193,119 sequences
- `clustering_run`: 1 global clustering run
- `cluster_member`: (optional) 193,119 membership records

**Clustering fields in chain_status**:
- `cluster_id`: Cluster identifier (16,574 unique)
- `is_representative`: TRUE for 16,574 chains
- `representative_pdb_id/chain_id`: Link to rep for members

**ECOD status fields**:
- `ecod_status`: 'in_current_ecod' (51,146), 'not_in_ecod' (141,973)
- `ecod_version`: ECOD version identifier

### Validation Queries

**Check clustering efficiency**:
```sql
SELECT * FROM pdb_update.clustering_efficiency
WHERE release_date = '2025-10-22';
```

**Check ECOD status distribution**:
```sql
SELECT ecod_status, COUNT(*),
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as percent
FROM pdb_update.chain_status
WHERE can_classify = TRUE
GROUP BY ecod_status;
```

**Check BLAST targets**:
```sql
SELECT COUNT(*)
FROM pdb_update.chain_status
WHERE is_representative = TRUE
  AND ecod_status = 'not_in_ecod';
-- Expected: 9,656
```

---

## Timeline

### Completed

- **2025-10-21 17:44 UTC**: Started metadata backfill (Phase 4a)
- **2025-10-21 22:00 UTC**: Metadata backfill complete (103 releases)
- **2025-10-22 14:00 UTC**: Sequence extraction complete (193,119 sequences)
- **2025-10-22 16:00 UTC**: Global clustering started (mmseqs2)
- **2025-10-22 18:00 UTC**: Clustering complete, loaded to database
- **2025-10-22 18:30 UTC**: ECOD status populated (51,146 in ECOD)
- **2025-10-22 19:00 UTC**: BLAST targets exported (9,656 representatives)
- **2025-10-22 19:30 UTC**: Chain BLAST started (10 batches)
- **2025-10-22 23:30 UTC**: Chain BLAST complete (9,656/9,656)
- **2025-10-22 20:00 UTC**: Domain BLAST started
- **2025-10-23 00:00 UTC**: Summaries generated (9,656/9,656)
- **2025-10-23 02:00 UTC**: Domain BLAST complete (9,656/9,656)
- **2025-10-23 19:47 UTC**: Partitions status check (9,365/9,656 complete, 97.0%)
- **2025-10-23 20:35 CDT**: Database load to ecod_curation started (9,365 partitions)
- **2025-10-23 22:36 CDT**: HHsearch jobs submitted (5 batches, 4,297 chains)
  - Fixed SLURM array limit issue (MaxArraySize=1000)
  - Using direct UniRef30 access (no staging required)

### Current Status (2025-10-23 22:50 CDT)

- **Phase 4g: BLAST Workflow** - ✅ COMPLETE (100%)
  - All BLAST, summaries, and partitions complete
  - 291 chains (3.0%) partition failures under investigation

- **Phase 4h: HHsearch Workflow** - 🔄 IN PROGRESS
  - Jobs 318110-318144 running (5 batches, 4,297 chains)
  - Started: 22:36 CDT
  - ETA: 4-8 hours (02:36-06:36 CDT on 2025-10-24)

- **Phase 4i: ecod_curation Load** - 🔄 95% COMPLETE
  - Database load: 8,931/9,365 proteins (PID 1653403)
  - Started: 20:35 CDT
  - ETA: ~10-15 minutes

### Upcoming

- **Phase 4j**: Structure preprocessing (9,365 PDB files, ~3-8 hours)
- **Phase 4k**: HHsearch results processing (regenerate summaries, re-partition)
- **Phase 4l**: Evidence propagation (copy from reps to 176,545 members)
- **Phase 4m**: Production database load (sync to pdb_update)

---

## Next Steps

### Immediate (Overnight - 2025-10-23/24)

1. 🔄 **Monitor HHsearch jobs** - IN PROGRESS
   - 4,297 chains processing (ETA: 4-8 hours)
   - Check for failures: `sacct -u $USER --name=hhsearch* --state=FAILED`
   - Monitor progress: `squeue -u $USER --name=hhsearch*`

2. 🔄 **Complete ecod_curation load** - 95% DONE
   - 434 proteins remaining (~10-15 minutes)
   - Verify completion: `SELECT COUNT(*) FROM ecod_curation.protein`

3. ⏳ **Structure preprocessing** - WAITING FOR DB LOAD
   - Process 9,365 chain PDB files for curation interface
   - Estimated runtime: 3-8 hours
   - Can run in parallel with HHsearch

### Short-Term (2025-10-24)

4. **Process HHsearch results** - After jobs complete
   - Parse 4,297 HHR files
   - Regenerate summaries with BLAST + HHsearch evidence
   - Re-run partitioning for chains with updated evidence

5. **Examine partitions in ecod_curation**
   - Review domain assignments via curation interface
   - Identify chains needing manual review
   - Spot-check quality across coverage ranges

6. **Analyze 291 partition failures**
   - Identify which chains failed
   - Check for patterns (size, complexity, etc.)
   - Determine if they need manual intervention

### Medium-Term (This Week)

7. **Implement evidence propagation**
   - Script to copy BLAST+HHsearch evidence from reps to members (176,545 chains)
   - Run pyecod_mini partition independently for each member
   - Handle cluster members with different structures

8. **Load partition results to pdb_update**
   - Parse partition XMLs
   - Populate domain assignments
   - Calculate coverage metrics

9. **Generate completion report**
   - Statistics on domain counts, coverage, quality
   - Comparison to ECOD existing data
   - Identify chains needing manual curation

---

## Compute Resource Usage

### SLURM Jobs Submitted

| Job Type | Count | Status | Runtime |
|----------|-------|--------|---------|
| Chain BLAST | 10 batches | ✅ Complete | ~4 hours |
| Domain BLAST | 10 batches | 🔄 7.4% | ~4-6 hours (ongoing) |
| Summaries | 10 batches | ✅ Complete | ~30 minutes |
| Partitions | 10 batches | ✅ 96.9% | ~1-2 hours |

### Resource Estimates

**Per job**:
- BLAST: 8GB RAM, 1 CPU, 4 hours
- Summary: 4GB RAM, 1 CPU, 30 minutes
- Partition: 4GB RAM, 1 CPU, 1 hour

**Total resources**:
- Compute hours: ~1,100 hours (vs ~16,600 without clustering)
- Storage: ~50GB (BLAST XMLs, summaries, partitions)

---

## Success Criteria

✅ **Metadata loaded**: All 103 releases in database
✅ **Sequences extracted**: 193,119 sequences in database
✅ **Clustering complete**: 16,574 representatives (91.4% reduction)
✅ **ECOD status populated**: 51,146 chains in ECOD (26.5%)
✅ **BLAST targets identified**: 9,656 representatives
✅ **Chain BLAST complete**: 100% (9,656/9,656)
✅ **Domain BLAST complete**: 100% (9,656/9,656)
✅ **Summaries generated**: 100% (9,656/9,656)
🔄 **Partitions mostly complete**: 97.0% (9,365/9,656) - 291 need retry
⏳ **Evidence propagation**: Not started
⏳ **Database load**: Not started

---

## Lessons Learned

### Database-First Approach

**Success**: Storing sequences in `pdb_update.sequence` table avoided complex file management:
- Resumable extraction (ON CONFLICT DO NOTHING)
- Easy progress monitoring (COUNT queries)
- Efficient export to FASTA (single query)

**Key insight**: Database storage is more reliable than managing thousands of FASTA files.

### Global Clustering Strategy

**Success**: 91.4% reduction far exceeded initial predictions (60-80%):
- Very effective for large-scale backfills
- One-time operation (no incremental complexity)
- Massive compute savings (15,500 hours)

**Key insight**: "Clustering isn't optional with this level of backfill. Looking at raw results is good for no one."

### ECOD Status Integration

**Success**: Identifying 51,146 chains already in ECOD avoided duplicate work:
- Combined with clustering: 95% total reduction (193K → 9.7K)
- Clustering-aware propagation logic working well

**Key insight**: Always check ECOD status before starting BLAST to avoid wasted effort.

### PDB-Centric Batching

**Success**: Extracting all chains from a PDB file at once:
- Reduced I/O by 50-70% for multi-chain structures
- Faster than chain-by-chain approach

**Key insight**: Group by PDB ID, not by chain, when reading mmCIF files.

---

## References

- **Backfill workflow**: `/data/ecod/pdb_updates/backfill_2023_2025/BACKFILL_WORKFLOW.md`
- **BLAST workflow**: `/data/ecod/pdb_updates/backfill_2023_2025/blast/README.md`
- **Clustering integration**: `docs/CLUSTERING_INTEGRATION_STATUS.md`
- **Implementation plan**: `docs/IMPLEMENTATION_PLAN.md`
- **Production pipeline**: `docs/PRODUCTION_PIPELINE.md`
- **Scripts**:
  - `scripts/backfill_metadata.py` - Load historical releases
  - `scripts/run_clustering.py` - Run mmseqs2/CD-HIT
  - `scripts/load_clustering.py` - Load clustering to database
  - `scripts/populate_ecod_status.py` - Populate ECOD status

---

**Last Updated**: 2025-10-28
**Next Review**: After structure preprocessing completes (ETA: 1-2 hours)
**Status**: 🔄 **PHASE 4j IN PROGRESS** - Structure preprocessing 48% complete (4,526/9,365 PDB files)
