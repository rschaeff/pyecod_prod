# PDB Backfill 2023-2025 Workflow

## Overview

2-year PDB backfill (Oct 2023 - Oct 2025): 103 releases, 197,777 total chains, 193,119 classifiable chains.

**Status as of 2025-10-22:**
- ✅ All metadata loaded to `pdb_update.chain_status`
- ✅ All 193,119 sequences extracted to `pdb_update.sequence`
- ✅ ECOD status populated (52,063 chains already in ECOD)
- 🔄 mmseqs2 clustering at 70% identity (in progress)
- ⏳ Clustering load to database (pending)
- ⏳ BLAST on representatives (pending)

## Database Schema

### pdb_update.sequence Table

**Purpose**: Store SEQRES sequences extracted from PDB mmCIF files.

**Why database-first approach:**
- Avoids file management complexity (learned after FASTA extraction issues)
- Enables resumable extraction with ON CONFLICT
- Structured query for missing sequences
- Easy export to FASTA for clustering

```sql
CREATE TABLE pdb_update.sequence (
    pdb_id text NOT NULL,
    chain_id text NOT NULL,
    sequence text NOT NULL,
    length integer NOT NULL,
    release_date date,
    extracted_at timestamp DEFAULT now(),
    PRIMARY KEY (pdb_id, chain_id)
);
```

**Population workflow:**
1. Load existing FASTA files: `load_sequences_to_db.py`
2. Find missing sequences via LEFT JOIN
3. Extract missing via SLURM jobs: `extract_to_db.py`
4. Export to FASTA for clustering: `export_sequences.py`

### pdb_update.chain_status Table

**Relevant fields:**
- `ecod_status`: 'not_in_ecod', 'in_current_ecod', 'in_previous_ecod'
- `is_representative`: Boolean (from clustering)
- `representative_pdb_id`, `representative_chain_id`: Cluster rep assignment
- `cluster_size`: Number of members if this chain is a representative

## ECOD Status Considerations

### Critical Complexities

**1. Clustering vs ECOD Status**

The relationship between clustering representatives and ECOD status is **NOT straightforward**:

- ❌ **INCORRECT ASSUMPTION**: Representative in ECOD → all members in ECOD
- ✅ **REALITY**: Each chain needs independent ECOD status check
  - Representative might be from 2023 PDB entry (in ECOD)
  - Members might be from 2024-2025 PDB entries (not in ECOD)
  - Representatives are chosen by sequence identity, NOT by ECOD status

**2. Partial Classification / Coverage Issues**

Chains marked as `in_current_ecod` may still have substantial unclassified regions:

- A chain can be in ECOD with **poor coverage** (<50% of residues assigned to domains)
- Fragmentary classifications exist (e.g., only N-terminal domain classified)
- Multi-domain proteins may have only some domains classified

**3. ECOD Status Should NOT Prevent BLAST**

Current logic: Skip BLAST if `ecod_status = 'in_current_ecod'`

**Problem scenarios:**
- Chain in ECOD but only 40% coverage → remaining 60% might find new domains
- Chain in old ECOD version, new classification might be better
- Chain classified but with low confidence (manual review needed)

**Recommendation for future work:**
- Query ECOD coverage from `ecod_protein.domain` before skipping BLAST
- Only skip BLAST if coverage >= 80% AND in current ECOD version
- Consider re-running low-coverage chains even if already in ECOD

### ECOD Status Propagation Strategy

**Current implementation** (`populate_ecod_status.py`):
1. Query `ecod_commons.chain` for direct matches
2. Mark matching chains as `in_current_ecod`
3. Does NOT propagate from representatives to members

**Why we DON'T propagate ECOD status via clustering:**
- PDB entries are unique per chain (8abc_A ≠ 8xyz_A even if 70% identical)
- ECOD classification is per-chain, not per-sequence-cluster
- Cluster members from different PDB entries need independent classification

**BLAST evidence propagation is different:**
- BLAST results CAN be shared within cluster (same sequence → same hits)
- Representative's BLAST hits apply to all 70% identical members
- This is an optimization, not a classification decision

## Clustering Workflow

### mmseqs2 Parameters

```bash
mmseqs easy-cluster \
    all_chains.fasta \
    output_prefix \
    tmp_dir \
    --min-seq-id 0.7 \      # 70% sequence identity
    -c 0.8 \                # 80% coverage requirement
    --cov-mode 0 \          # Coverage of shorter sequence
    --threads 32
```

**Expected compression:** ~75-80% reduction (193K → ~40-45K representatives)

### Clustering Database Schema

```sql
-- Clustering metadata (one row per clustering run)
CREATE TABLE pdb_update.clustering_run (
    release_date date PRIMARY KEY,
    threshold float NOT NULL,           -- 0.70
    method text NOT NULL,                -- 'mmseqs2'
    total_sequences integer,             -- 193,119
    total_clusters integer,              -- ~40-45K
    run_date timestamp DEFAULT now()
);

-- Updates to chain_status (clustering assignments)
ALTER TABLE pdb_update.chain_status
ADD COLUMN is_representative boolean DEFAULT TRUE,
ADD COLUMN representative_pdb_id text,
ADD COLUMN representative_chain_id text,
ADD COLUMN cluster_size integer;
```

### Loading Clustering Results

Script: `load_clustering.py` (from pyecod_prod)

```bash
python scripts/load_clustering.py \
    --cluster-file mmseqs_70pct_cluster.tsv \
    --release-date 2025-10-22 \
    --threshold 0.70 \
    --method mmseqs2
```

**TSV format** (mmseqs2 output):
```
representative_id    member_id
8abc_A              8abc_A
8abc_A              8abc_B
8abc_A              8xyz_A
8def_A              8def_A
```

## Next Steps

1. **Complete clustering** (mmseqs2 job in progress)
2. **Load clustering to database**
   - Insert to `clustering_run` table
   - Update `chain_status` with representative assignments
3. **Verify clustering statistics**
   - Compression ratio
   - Cluster size distribution
   - Representative selection
4. **BLAST workflow on representatives**
   - Query database for representatives with `ecod_status = 'not_in_ecod'`
   - Run chain + domain BLAST via existing pipeline
   - Share BLAST evidence with cluster members

## Lessons Learned

### Database-First Approach

**Problem**: FASTA file extraction had multiple issues:
- Jobs hanging silently (Python processes dying without errors)
- Zero-byte output files due to buffering
- Timeout issues with large PDB files
- Complex resumption logic with file validation

**Solution**: Database-first workflow
1. Store sequences in `pdb_update.sequence`
2. Query database for missing sequences
3. Extract directly to database (PDB-centric batching)
4. Export to FASTA only when needed for clustering

**Benefits:**
- Resumable (ON CONFLICT DO NOTHING)
- Easy progress monitoring (COUNT queries)
- Structured storage (no file management)
- Efficient exports (single query)

### PDB-Centric Batching

Opening each PDB file once and extracting all needed chains:
- Reduces I/O by 50-70% for multi-chain structures
- Groups chains by PDB ID before processing
- Much faster than chain-by-chain approach

### SLURM Chunking

For 154K sequences: 31 jobs × 5,000 chains each
- Small enough to complete reliably (<1 hour each)
- Enough parallelism to finish quickly (31 concurrent jobs)
- Easy to identify and rerun failures

## File Locations

**Database:** dione:45000/ecod_protein
- Schema: `pdb_update`
- Tables: `chain_status`, `sequence`, `clustering_run`

**FASTA files:**
- All sequences: `/data/ecod/pdb_updates/backfill_2023_2025/clustering/all_chains.fasta`
- 193,119 sequences, 51.3 MB

**Clustering output:**
- Results: `/data/ecod/pdb_updates/backfill_2023_2025/clustering/mmseqs_70pct_cluster.tsv`
- Representatives: `/data/ecod/pdb_updates/backfill_2023_2025/clustering/mmseqs_70pct_rep_seq.fasta`

**Scripts:**
- `load_sequences_to_db.py` - Load FASTA files to database
- `extract_to_db.py` - Extract sequences directly to database
- `export_sequences.py` - Export from database to FASTA
- `scripts/run_clustering.py` - Run mmseqs2 clustering (SLURM)
- `scripts/load_clustering.py` - Load clustering results to database
- `scripts/populate_ecod_status.py` - Populate ECOD status from ecod_commons

## Future Considerations

### Coverage-Aware BLAST

Before skipping BLAST for chains in ECOD:
1. Check coverage from `ecod_protein.domain`
2. Calculate: `SUM(domain_length) / chain_length`
3. Only skip if coverage >= 80%

### Re-classification Strategy

Chains with low coverage (<50%) should be re-BLASTed even if in ECOD:
- May find additional domains
- May improve classification quality
- ECOD evolves - new families/superfamilies added

### Clustering Validation

After loading clustering results:
- Check for singleton clusters (representatives with cluster_size = 1)
- Verify compression ratio matches expectations (~75-80%)
- Validate bidirectional representative assignments

### BLAST Evidence Sharing

Representatives with good BLAST hits should share with cluster members:
- Copy BLAST XML results
- Reuse domain_summary.xml evidence
- Only partition each member independently (structure may differ slightly)
