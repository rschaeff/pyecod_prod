# HHsearch Workflow for PDB Backfill

This document describes the HHsearch workflow for the 2023-2025 PDB backfill project.

## Current Status (2025-10-25)

**✅ HHSEARCH COMPLETE - 94% SUCCESS RATE**

- **Completed**: 4,038 chains (94.0%)
- **Failed (timeouts)**: 259 chains (6.0%)
- **Jobs**: 318110, 318141-318144 (5 batches)
- **Runtime**: ~6-7 hours (2025-10-23 22:36 to 2025-10-24 ~05:00 CDT)

**Failure Analysis**:
- All 259 failures were hhblits timeouts (30-minute limit)
- Failed chains significantly longer than successful:
  - Failed: mean 1,244 residues, range 83-4,629
  - Successful: mean 241 residues, range 20-2,032
- Top 10 failures: 4,000-4,629 residues (very large multi-domain proteins)

**Post-Processing** (2025-10-25):
- Regenerating 4,038 summaries with BLAST + HHsearch evidence (Job 322407)
- Re-running partitioning with enhanced evidence
- Results saved to separate directories for comparison:
  - `summaries_with_hhsearch/`
  - `partitions_with_hhsearch/`

## Overview

The HHsearch workflow implements a **two-pass search strategy**:
1. **BLAST** (fast, less sensitive) - ✅ COMPLETED
2. **HHsearch** (slow, more sensitive) - 🔄 IN PROGRESS (for chains with <90% BLAST coverage)

## Coverage Analysis Results

From 9,656 cluster representatives (not in ECOD):
- **Excellent (≥90%)**: 5,359 chains (55.5%) - BLAST sufficient ✓
- **Good (70-89%)**:     473 chains (4.9%)  - Need HHsearch
- **Low (50-69%)**:      238 chains (2.5%)  - Need HHsearch
- **Poor (<50%)**:       356 chains (3.7%)  - Need HHsearch
- **No evidence**:     3,230 chains (33.5%) - Need HHsearch

**Total chains needing HHsearch: 4,297 (44.5%)**

Average BLAST coverage: 61.7%

## Architecture: Direct Database Access

HHsearch requires a large UniRef30 database (~261GB uncompressed) for profile building.

**Database location**: `/home/rschaeff/search_libs/UniRef30_2023_02`

The database is already extracted and stored on network-shared storage accessible from
all compute nodes. **No staging required** - jobs use the database directly from this
location, which is mounted on all nodes via NFS.

## Files and Scripts

### Data Files
- `hhsearch_targets.txt` - 4,297 chains needing HHsearch (<90% BLAST coverage)
- `blast_targets.txt` - Original 9,656 chains for BLAST
- `summaries/*.summary.xml` - BLAST evidence (9,656 files)

### Scripts
1. `run_hhsearch_twostep.py` - Core HHsearch script (hhblits + hhsearch)
2. `submit_hhsearch_batch[2-5].sh` - Individual batch submission scripts
3. `submit_hhsearch_fixed.sh` - Multi-batch submission wrapper (for future runs)

### Output Directories
- `profiles/` - HHblits multiple sequence alignments (.a3m files)
- `hhsearch/` - HHsearch results (.hhr files)

## Workflow Execution (Simplified Direct Access)

**Note**: UniRef30 is already extracted in `/home/rschaeff/search_libs/UniRef30_2023_02` and accessible from all nodes via NFS. **No staging required.**

### Submit HHsearch Jobs

The workflow submits 5 batches to process 4,297 chains:

```bash
cd /data/ecod/pdb_updates/backfill_2023_2025/blast

# Submit individual batches (already done for current run)
sbatch submit_hhsearch_batch2.sh  # Chains 1001-2000
sbatch submit_hhsearch_batch3.sh  # Chains 2001-3000
sbatch submit_hhsearch_batch4.sh  # Chains 3001-4000
sbatch submit_hhsearch_batch5.sh  # Chains 4001-4297

# Or use wrapper for future runs
./submit_hhsearch_fixed.sh
```

**What each job does**:
1. hhblits: Build profile against UniRef30 (~/search_libs/UniRef30_2023_02)
2. hhsearch: Search profile against ECOD HMMs (/data/ecod/database_versions/v291/ecod_v291)

**SLURM array limit workaround**: Each batch uses array indices 1-N with offset calculation to avoid MaxArraySize=1000 limit.

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
- Max concurrent: 500 jobs per batch

## Timeline Estimate

**Direct access (simplified workflow)**:
- HHsearch jobs: ~4-8 hours (depending on hhblits profile building time)
  - hhblits: 10-30 min/chain (profile building against UniRef30)
  - hhsearch: 5-10 min/chain (search against ECOD HMMs)
- Max 500 concurrent jobs per batch (5 batches = 2,500 max concurrent total)

**Actual runtime** (current run started 2025-10-23 22:36):
- Will be updated after completion

## Node Requirements

Each node running HHsearch requires:
- RAM: 16GB per job
- CPUs: 4 per job
- Network access: ~/search_libs/UniRef30_2023_02 (261GB, NFS-mounted)
- No local /tmp storage required (uses network database directly)

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

### Issue: "UniRef30 database not found"
**Symptoms**: Jobs fail with "ERROR: UniRef30 database not found!"
**Solution**: Verify database exists: `ls -lh /home/rschaeff/search_libs/UniRef30_2023_02_*.ffdata`

### Issue: SLURM array limit exceeded
**Symptoms**: "sbatch: error: Batch job submission failed: Invalid job array specification"
**Cause**: SLURM MaxArraySize typically 1000, can't use indices >1000
**Solution**: Use individual batch scripts with offset calculation (already implemented in submit_hhsearch_batch[2-5].sh)

### Issue: hhblits timeout
**Default timeout**: 30 minutes per chain
**Solution**: Check if chain has exceptionally long sequence, may need manual processing
**Check**: `tail slurm_logs/hhsearch_*.err` for timeout messages

### Issue: Slow progress
**Typical rate**: Variable depending on sequence length and homology
- hhblits: 10-30 min/chain (profile building)
- hhsearch: 5-10 min/chain (search)
**Solutions**:
- Check for failed jobs: `sacct -u $USER --name=hhsearch* --state=FAILED`
- Monitor active jobs: `squeue -u $USER --name=hhsearch*`
- Check SLURM logs for errors: `ls slurm_logs/hhsearch_*.err`

### Issue: NFS performance bottleneck
**Symptoms**: Many jobs accessing UniRef30 simultaneously causing slow I/O
**Mitigation**: SLURM %500 limit reduces concurrent access
**Check**: Monitor with `squeue -u $USER --name=hhsearch* | grep " R " | wc -l`

## References

- HH-suite documentation: https://github.com/soedinglab/hh-suite
- UniRef30 database: https://uniclust.mmseqs.com/
- ECOD database: https://prodata.swmed.edu/ecod/
- pyecod_prod repository: `/home/rschaeff/dev/pyecod_prod/`
