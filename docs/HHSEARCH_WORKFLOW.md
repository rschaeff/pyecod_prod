# HHsearch Workflow for PDB Backfill

This document describes the staged HHsearch workflow for the 2023-2025 PDB backfill project.

## Overview

The HHsearch workflow implements a **two-pass search strategy**:
1. **BLAST** (fast, less sensitive) - COMPLETED
2. **HHsearch** (slow, more sensitive) - For chains with <90% BLAST coverage

## Coverage Analysis Results

From 9,656 cluster representatives (not in ECOD):
- **Excellent (≥90%)**: 5,359 chains (55.5%) - BLAST sufficient ✓
- **Good (70-89%)**:     473 chains (4.9%)  - Need HHsearch
- **Low (50-69%)**:      238 chains (2.5%)  - Need HHsearch
- **Poor (<50%)**:       356 chains (3.7%)  - Need HHsearch
- **No evidence**:     3,230 chains (33.5%) - Need HHsearch

**Total chains needing HHsearch: 4,297 (44.5%)**

Average BLAST coverage: 61.7%

## Architecture: Staged Workflow

HHsearch requires a large UniRef30 database (~261GB uncompressed) for profile building.
To avoid staging overhead per-job, we use a **decoupled 3-phase approach**:

### Phase 1: Database Staging
Copy UniRef30 to /tmp on select nodes with adequate disk space (≥300GB)

### Phase 2: Profile Building + Search
Run hhblits (profile) + hhsearch (search) ONLY on staged nodes

### Phase 3: Database Destaging
Clean up UniRef30 from /tmp after all jobs complete

## Files and Scripts

### Data Files
- `hhsearch_targets.txt` - 4,297 chains needing HHsearch (<90% BLAST coverage)
- `blast_targets.txt` - Original 9,656 chains for BLAST
- `summaries/*.summary.xml` - BLAST evidence (9,656 files)

### Scripts
1. `run_hhsearch_twostep.py` - Core HHsearch script (hhblits + hhsearch)
2. `stage_uniref_to_nodes.sh` - Stage UniRef30 to compute nodes
3. `submit_hhsearch_staged.sh` - Submit HHsearch jobs to staged nodes
4. `destage_uniref_from_nodes.sh` - Clean up UniRef30 from nodes

### Output Directories
- `profiles/` - HHblits multiple sequence alignments (.a3m files)
- `hhsearch/` - HHsearch results (.hhr files)
- `staging/` - Staging logs and markers

## Workflow Execution

### Step 1: Identify Nodes with Sufficient /tmp

Check nodes in 96GB partition for /tmp capacity:

```bash
# Submit test job to check /tmp on all nodes
sbatch --array=16-34 --partition=96GB check_node_tmp.sh

# Or manually check a single node
srun --partition=96GB --nodes=1 --pty bash -c "df -h /tmp"
```

**Requirement**: ≥300GB /tmp space (261GB database + 40GB working space)

**Recommended nodes** (update after verification):
- leda20, leda21, leda22, leda23 (or other nodes with large /tmp)

### Step 2: Stage UniRef30 Database

Stage the database to selected nodes (~2 hours):

```bash
# Using default nodes
./stage_uniref_to_nodes.sh

# Or specify nodes explicitly
./stage_uniref_to_nodes.sh leda20,leda21,leda22,leda23
```

**What it does**:
- Copies `~/search_libs/UniRef30_2023_02_hhsuite.tar.gz` (66GB) to /tmp
- Extracts to ~261GB uncompressed database
- Creates staging markers in `staging/` directory

**Monitor progress**:
```bash
squeue -u $USER --name=stage_uniref*
tail -f staging/stage_*.log
```

**Verify staging**:
```bash
ls staging/*_staged.txt  # Should show one file per node
```

### Step 3: Submit HHsearch Jobs

Submit jobs ONLY to nodes with staged database (~4-6 hours for 4,297 chains):

```bash
# Auto-detect staged nodes from markers
./submit_hhsearch_staged.sh

# Or specify nodes explicitly
./submit_hhsearch_staged.sh leda20,leda21,leda22,leda23
```

**What it does**:
- Submits 5 batches (4,297 chains ÷ 1000 per batch)
- Each job runs:
  1. hhblits: Build profile against UniRef30 (/tmp)
  2. hhsearch: Search profile against ECOD HMMs
- Max 500 concurrent jobs per batch
- Outputs: `profiles/*.a3m` and `hhsearch/*.hhr`

**Monitor progress**:
```bash
squeue -u $USER --name=hhsearch*
ls profiles/*.a3m | wc -l   # Profiles built
ls hhsearch/*.hhr | wc -l   # HHsearch completed
```

**Resource allocation** (per job):
- Time: 4 hours
- Memory: 16GB
- CPUs: 4
- Partition: 96GB

### Step 4: Destage Database

After ALL HHsearch jobs complete, free up /tmp space (~30 minutes):

```bash
# Verify all jobs completed
squeue -u $USER --name=hhsearch*  # Should be empty

# Run destaging
./destage_uniref_from_nodes.sh
```

**What it does**:
- Removes ~261GB UniRef30 database from /tmp
- Cleans up temporary hhblits files
- Removes staging markers

## Timeline Estimate

**With 4 staged nodes (parallel with partitioning)**:
- Phase 1 (Staging): ~2 hours
- Phase 2 (HHsearch): ~4-6 hours (4,297 chains ÷ 4 nodes ÷ ~8-10 chains/hour/node)
- Phase 3 (Destaging): ~30 minutes

**Total: ~6-8 hours**

## Node Requirements

Each staged node requires:
- /tmp space: ≥300GB
- RAM: 16GB per concurrent job
- CPUs: 4 per job
- With %500 limit: Max 500 × 16GB = 8TB total RAM (well within 96GB node capacity with time-sharing)

## Database Details

### UniRef30_2023_02
**Source**: `~/search_libs/UniRef30_2023_02_hhsuite.tar.gz` (66GB compressed)

**Contents** (uncompressed):
- `UniRef30_2023_02_hhm.ffdata`: 48GB (HMM database)
- `UniRef30_2023_02_a3m.ffdata`: 204GB (MSA database)
- `UniRef30_2023_02_cs219.ffdata`: 8.5GB (Context-specific profiles)
- **Total**: ~261GB

### ECOD v291 HMM Database
**Location**: `/data/ecod/database_versions/v291/ecod_v291`

**Contents** (shared storage, no staging needed):
- `ecod_v291_hhm.ffdata`: 1.2GB
- `ecod_v291_hhm.ffindex`: 28MB

## Next Steps After HHsearch Completes

1. **Regenerate summaries** with HHsearch evidence
2. **Re-partition** chains with updated evidence
3. **Propagate results** from representatives to cluster members (176,545 chains)

See `README.md` for complete workflow documentation.

## Troubleshooting

### Issue: "UniRef30 not staged in /tmp"
**Solution**: Run `stage_uniref_to_nodes.sh` first, verify with `ls staging/*_staged.txt`

### Issue: Jobs failing on wrong nodes
**Solution**: Ensure `submit_hhsearch_staged.sh` uses correct `--nodelist`

### Issue: Out of /tmp space
**Solution**: Check df -h /tmp on nodes, ensure ≥300GB available

### Issue: hhblits timeout
**Default timeout**: 30 minutes per chain
**Solution**: Check if chain has exceptionally long sequence, may need manual processing

### Issue: Slow progress
**Typical rate**: 8-10 chains/hour/node
**Solutions**:
- Verify all staged nodes are being used
- Check for failed jobs: `sacct -u $USER --name=hhsearch* --state=FAILED`
- Increase number of staged nodes if available

## References

- HH-suite documentation: https://github.com/soedinglab/hh-suite
- UniRef30 database: https://uniclust.mmseqs.com/
- ECOD database: https://prodata.swmed.edu/ecod/
- pyecod_prod repository: `/home/rschaeff/dev/pyecod_prod/`
