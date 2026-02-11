# Auto-Accession: Q4 2025 + Q1 2026 Batch

**Date**: 2026-01-20
**Batch ID**: `ecod_q4_2025_q1_2026`
**Domain Version**: `pyecod_prod_ecod_q4_2025_q1_2026`

## Overview

This document describes the auto-accession of high-confidence domain classifications from pyecod-mini directly into `ecod_commons`. This bypasses `ecod_curation` (which is reserved for manual review of ~10% of cases).

## Batch Statistics

| Metric | Value |
|--------|-------|
| Partition XMLs scanned | 3,677 |
| High-coverage (≥80%) | 2,679 chains |
| Low-coverage (<80%) | 998 chains (skipped) |
| Designed proteins excluded | 4 PDBs |
| **Domains inserted** | **4,497** |
| Failed | 0 |

### UID Range

- **Start**: 4,886,797
- **End**: 4,891,293

### Designed Proteins Excluded

The following 18 designed proteins were configured for exclusion (4 were present in batch):

```
9hnh, 9hn3, 9hn0, 9hml, 9hmk, 9hmj, 9hmi, 9hmh,
9h9h, 9h9g, 9h9f, 9h9e, 9h9d, 9h9c, 9h9a, 9h99,
9h98, 9r0t
```

Skipped in this batch: `9h99`, `9hn3`, `9hnh`, `9r0t`

## Database Tables Modified

| Table | Records Added | Notes |
|-------|---------------|-------|
| `ecod_commons.domains` | 4,497 | New domain records |
| `ecod_commons.f_group_assignments` | 4,497 | Family assignments (`assignment_method='blast'`) |
| `ecod_commons.domain_ranges` | 4,497 | PDB ranges (`range_type='pdb'`) |
| `ecod_commons.proteins` | ~1,388 | New protein records (as needed) |

## Version Tracking

All inserted domains have:
- `domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026'`
- `assigned_by = 'pyecod_prod'`

### Software Versions

| Component | Version |
|-----------|---------|
| pyecod-mini | 2.0.3 |
| pyecod-prod | 0.1.0 |
| ECOD reference | v293.1 |

## Overlap Detection Policy

Matches legacy Perl script (`process_domain_summary_to_ecod_release.pl`):

| Condition | Action |
|-----------|--------|
| Identical range | Skip (duplicate) |
| >80% bidirectional coverage | Skip ("loose correspondence") |
| >10 residues overlap | Skip (conflict) |
| ID collision with different range | Auto-renumber domain |

**Results**: No overlaps or conflicts detected in this batch (all 4,497 domains were new).

## Files Created

### Scripts

- `scripts/auto_accession_batch.py` - Main batch accession script
- `src/pyecod_prod/parsers/partition_parser.py` - Partition XML parser
- `src/pyecod_prod/database/auto_accession.py` - Auto-accession loader (updated)
- `src/pyecod_prod/database/domain_overlap.py` - Overlap detection (updated)
- `src/pyecod_prod/database/cluster_propagation.py` - Cluster member propagation

### Reports

- `/data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/accession_report_final.json`
- `/data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/accession_dry_run_full_v3.json`

## Rollback Instructions

To rollback this batch:

```sql
BEGIN;

-- Check what will be deleted
SELECT COUNT(*) FROM ecod_commons.domains
WHERE domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026';

-- Delete domain_ranges
DELETE FROM ecod_commons.domain_ranges
WHERE domain_id IN (
    SELECT id FROM ecod_commons.domains
    WHERE domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026'
);

-- Delete F-group assignments
DELETE FROM ecod_commons.f_group_assignments
WHERE domain_id IN (
    SELECT id FROM ecod_commons.domains
    WHERE domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026'
);

-- Delete T-group assignments (if any)
DELETE FROM ecod_commons.t_group_only_assignments
WHERE domain_id IN (
    SELECT id FROM ecod_commons.domains
    WHERE domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026'
);

-- Delete domains
DELETE FROM ecod_commons.domains
WHERE domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026';

COMMIT;
```

## Cluster Propagation

The 2,676 classified representatives need their domain assignments propagated to cluster members at 70% sequence identity.

### Propagation Methodology

**Why tiered propagation?** At 70% sequence identity, proteins may have:
- Different domain boundaries due to insertions/deletions
- Variable loop regions
- Potentially different domain compositions

We use sequence length difference as a proxy for structural similarity:

| Tier | Length Diff | Members | % | Action |
|------|-------------|---------|---|--------|
| 1 | ≤10% | 20,255 | 94% | Auto-propagate |
| 2 | 10-20% | 1,087 | 5% | Auto-propagate (verified) |
| 3 | >20% | 165 | 0.8% | Needs full re-classification |

### Dry Run Results (2026-01-20)

```
Representatives processed: 2,676
Total cluster members: 21,507
Processing time: 1,265.6 seconds (~21 min)
Rate: 17.0 members/sec

Propagation Breakdown:
  Tier 1 (auto):      20,255 members
  Tier 2 (verified):   1,087 members
  Tier 3 (reclassify):   165 members

Total domains to propagate: 33,742
```

### Production Run Results (2026-01-20)

```
Representatives processed: 2,676
Total cluster members: 21,507
Processing time: 5,482.1 seconds (~91 min)
Rate: 3.9 members/sec

Propagation Breakdown:
  Tier 1 (auto):      20,255 members
  Tier 2 (verified):   1,087 members
  Tier 3 (reclassify):   165 members

Total domains propagated: 33,748
```

**Final Domain Counts**:
| Domain Version | Domains | With Sequences |
|----------------|---------|----------------|
| Direct (`pyecod_prod_ecod_q4_2025_q1_2026`) | 4,497 | 4,497 |
| Propagated (`pyecod_prod_ecod_q4_2025_q1_2026_propagated`) | 33,748 | 33,736 |
| **Total** | **38,245** | **38,233** |

*12 domains have range definitions extending beyond chain sequence lengths (edge cases from propagation).*

### Propagation Details

**Domain Version**: Propagated domains get `domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026_propagated'`

**Assignment Method**: `assignment_method='inheritance'` distinguishes propagated from directly classified domains

**Representative Link**: Each propagated domain has `representative_domain_id` pointing to the source domain

**Tables Modified**:
| Table | Records | Notes |
|-------|---------|-------|
| `ecod_commons.proteins` | ~21,507 | New protein records for members |
| `ecod_commons.domains` | ~33,742 | Propagated domain records |
| `ecod_commons.f_group_assignments` | ~33,742 | Family assignments (`assignment_method='inheritance'`) |
| `ecod_commons.domain_ranges` | ~33,742 | PDB ranges for propagated domains |

### Propagation Module

**Module**: `src/pyecod_prod/database/cluster_propagation.py`

**Key Classes**:
- `ClusterPropagator` - Main propagation engine
- `PropagationTier` - Enum for tier classification
- `PropagationResult` - Result for single member
- `PropagationSummary` - Batch summary statistics

**Key Methods**:
```python
# Classify a member into a propagation tier
tier = propagator.classify_member_tier(member_length, rep_length)

# Get representative's domains
domains = propagator.get_representative_domains(pdb_id, chain_id, domain_version)

# Get cluster members
members = propagator.get_cluster_members(rep_pdb_id, rep_chain_id, release_dates)

# Propagate to a single member
result = propagator.propagate_to_member(member_pdb_id, member_chain_id, ...)

# Propagate from a single representative to all members
results = propagator.propagate_from_representative(rep_pdb_id, rep_chain_id, ...)

# Full batch propagation
summary = propagator.propagate_batch(domain_version, release_dates, limit)
```

### Usage

```bash
# Dry run first
python scripts/run_propagation_batch.py --dry-run

# Real run
python scripts/run_propagation_batch.py

# With limit for testing
python scripts/run_propagation_batch.py --limit 10
```

**Python API**:
```python
from pyecod_prod.database.cluster_propagation import ClusterPropagator

# Dry run
propagator = ClusterPropagator(dry_run=True)
summary = propagator.propagate_batch(
    domain_version="pyecod_prod_ecod_q4_2025_q1_2026",
    release_dates=('2025-10-01', '2026-01-31')
)
summary.print_summary()

# Real propagation
propagator = ClusterPropagator(dry_run=False)
summary = propagator.propagate_batch(...)
```

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/run_propagation_batch.py` | Full batch propagation |
| `scripts/test_propagation.py` | Dry-run testing |
| `scripts/test_propagation_real.py` | Small-scale real test |

### Tier 3 Members (Needs Re-classification)

165 members have >20% length difference from their representative and need full pyecod-mini classification:

```sql
-- Find Tier 3 members
SELECT m.pdb_id, m.chain_id, m.sequence_length,
       r.pdb_id as rep_pdb, r.chain_id as rep_chain, r.sequence_length as rep_length,
       ABS(m.sequence_length - r.sequence_length)::float / r.sequence_length * 100 as length_diff_pct
FROM pdb_update.chain_status m
JOIN pdb_update.chain_status r ON m.representative_pdb_id = r.pdb_id
                               AND m.representative_chain_id = r.chain_id
WHERE m.release_date BETWEEN '2025-10-01' AND '2026-01-31'
AND m.is_representative = false
AND ABS(m.sequence_length - r.sequence_length)::float / r.sequence_length > 0.20
ORDER BY length_diff_pct DESC;
```

### Rollback Propagated Domains

```sql
BEGIN;

-- Check what will be deleted
SELECT COUNT(*) FROM ecod_commons.domains
WHERE domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026_propagated';

-- Delete domain_ranges
DELETE FROM ecod_commons.domain_ranges
WHERE domain_id IN (
    SELECT id FROM ecod_commons.domains
    WHERE domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026_propagated'
);

-- Delete F-group assignments
DELETE FROM ecod_commons.f_group_assignments
WHERE domain_id IN (
    SELECT id FROM ecod_commons.domains
    WHERE domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026_propagated'
);

-- Delete T-group assignments
DELETE FROM ecod_commons.t_group_only_assignments
WHERE domain_id IN (
    SELECT id FROM ecod_commons.domains
    WHERE domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026_propagated'
);

-- Delete domains
DELETE FROM ecod_commons.domains
WHERE domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026_propagated';

COMMIT;
```

## Performance Notes

### Optimizations Applied

1. **Batch prefetch for overlap checks**: Load all existing domains for batch PDBs in one query
2. **Domain ID prefetch**: Check domain ID existence via prefetch instead of N queries
3. **Tracked prefetch status**: Avoid re-querying for PDBs with no existing domains

### Processing Time

| Phase | Duration |
|-------|----------|
| Dry run (4,497 domains) | ~28 minutes |
| Real run (4,497 domains) | ~39 minutes |
| Rate | ~2 domains/sec |

## Verification Queries

```sql
-- Count domains by version
SELECT domain_version, COUNT(*)
FROM ecod_commons.domains
WHERE domain_version LIKE 'pyecod_prod%'
GROUP BY domain_version;

-- Check UID range
SELECT MIN(ecod_uid), MAX(ecod_uid), COUNT(*)
FROM ecod_commons.domains
WHERE domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026';

-- Sample domains with family assignments
SELECT d.domain_id, d.ecod_uid, p.pdb_id, p.chain_id,
       d.range_definition, fa.f_group_id
FROM ecod_commons.domains d
JOIN ecod_commons.proteins p ON d.protein_id = p.id
JOIN ecod_commons.f_group_assignments fa ON d.id = fa.domain_id
WHERE d.domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026'
LIMIT 10;

-- Verify domain_ranges populated
SELECT COUNT(*)
FROM ecod_commons.domain_ranges dr
JOIN ecod_commons.domains d ON dr.domain_id = d.id
WHERE d.domain_version = 'pyecod_prod_ecod_q4_2025_q1_2026';
```

## Future Batches

For future batches, use:

```bash
# Dry run first
python scripts/auto_accession_batch.py \
    /path/to/partitions \
    --dry-run \
    --min-coverage 0.80

# Real run with batch ID
python scripts/auto_accession_batch.py \
    /path/to/partitions \
    --batch-id my_batch_id \
    --ecod-reference v293.1
```

The script now automatically:
- Inserts into `ecod_commons.domains`
- Inserts into `ecod_commons.f_group_assignments` (or `t_group_only_assignments`)
- Inserts into `ecod_commons.domain_ranges`

## Pfam v38.1 F-group Assignment

After auto-accession and propagation, domains are scanned against Pfam v38.1 for F-group assignment refinement.

### Domain Sequence Extraction

**Script**: `scripts/extract_domain_sequences.py`

```bash
# Extract sequences for direct domains
python scripts/extract_domain_sequences.py \
    --domain-version "pyecod_prod_ecod_q4_2025_q1_2026" \
    --input-fasta /data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/fastas/all_chains.fasta

# Extract sequences for propagated domains
python scripts/extract_domain_sequences.py \
    --domain-version "pyecod_prod_ecod_q4_2025_q1_2026_propagated" \
    --input-fasta /data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/fastas/all_chains.fasta
```

**Results** (2026-01-20):
| Domain Version | Total Domains | Sequences Extracted | Missing |
|----------------|---------------|---------------------|---------|
| Direct | 4,497 | 4,497 | 0 |
| Propagated | 33,748 | 33,736 | 12 |
| **Total** | **38,245** | **38,233** | **12** |

### Pfam hmmscan Workflow

**Script**: `scripts/submit_pfam_batch.py`

```bash
# Dry run (preview without submitting)
python scripts/submit_pfam_batch.py --dry-run

# Submit SLURM job
python scripts/submit_pfam_batch.py
```

**Configuration**:
- Pfam database: `~/data/pfam/v38.1/Pfam-A.hmm`
- HMMER: `/data/ecod/hmmer-3.1b2/binaries/hmmscan`
- Cutoff: `--cut_ga` (gathering threshold)
- Sequences per chunk: 1,000
- CPUs per task: 16
- Time limit: 2 hours

**Job Submission** (2026-01-20):
- Job ID: 399864
- Array tasks: 39 (1000 sequences each)
- Total sequences: 38,233
- Partition: All (default)

**Output files**:
```
/data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/pfam/
├── hmmscan_0000.tblout      # Sequence-level hits
├── hmmscan_0000.domtblout   # Domain-level hits
├── hmmscan_0000.out.gz      # Full output (compressed)
├── ...
└── hmmscan_0038.domtblout
```

### Pfam Results Parsing

**Script**: `scripts/parse_pfam_results.py`

```bash
python scripts/parse_pfam_results.py \
    --batch-dir /data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026
```

**Track Classification**:

| Track | Description | Expected % |
|-------|-------------|------------|
| Track 1 | Pfam maps to existing F-group | ~70% |
| Track 2a | Pfam needs new F-group | ~20% |
| Track 2b | Multiple Pfam (composite) | ~5% |
| Track 3 | No Pfam hit | ~5% |

**Output**:
- `pfam/domain_pfam_assignments.tsv` - Per-domain assignments
- `pfam/pfam_classification_report.json` - Summary statistics

### Scripts Created

| Script | Purpose |
|--------|---------|
| `scripts/extract_domain_sequences.py` | Extract domain sequences from chain sequences |
| `scripts/submit_pfam_batch.py` | Generate FASTA, split chunks, submit SLURM |
| `scripts/run_pfam_hmmscan.slurm` | SLURM array job for Pfam scanning |
| `scripts/parse_pfam_results.py` | Parse domtblout and classify domains |

### Monitoring

```bash
# Check job status
squeue -j 399864

# Check completed tasks
ls /data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/pfam/*.domtblout | wc -l

# Check for errors
ls /data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/slurm_logs/pfam_*.err | xargs grep -l ERROR
```

---

## Replicable Workflow for Future Batches

This section provides a complete step-by-step guide for processing future PDB batches.

### Prerequisites

1. **Environment**:
   ```bash
   source ~/.bashrc
   export ECOD_DB_PASSWORD='ecod#badmin'
   export PYTHONPATH=/home/rschaeff/dev/pyecod_prod/src:$PYTHONPATH
   ```

2. **Required inputs**:
   - Partition XMLs from pyecod-mini classification
   - Chain FASTA file (e.g., `all_chains.fasta`)
   - Batch directory with clustering results

3. **Database access**: PostgreSQL on dione:45000

### Step 1: Auto-Accession (Direct Domains)

Insert high-confidence domains (≥80% coverage) into `ecod_commons`.

```bash
# Dry run first
python scripts/auto_accession_batch.py \
    /path/to/partitions \
    --batch-id my_batch_id \
    --min-coverage 0.80 \
    --dry-run

# Review dry run output, then real run
python scripts/auto_accession_batch.py \
    /path/to/partitions \
    --batch-id my_batch_id \
    --min-coverage 0.80
```

**Expected output**: `domain_version = 'pyecod_prod_<batch_id>'`

### Step 2: Cluster Propagation

Propagate domain assignments to 70% sequence identity cluster members.

```bash
# Dry run first
python scripts/run_propagation_batch.py \
    --domain-version "pyecod_prod_<batch_id>" \
    --start-date 2025-10-01 \
    --end-date 2026-01-31 \
    --dry-run

# Review tier breakdown, then real run
python scripts/run_propagation_batch.py \
    --domain-version "pyecod_prod_<batch_id>" \
    --start-date 2025-10-01 \
    --end-date 2026-01-31
```

**Expected output**: `domain_version = 'pyecod_prod_<batch_id>_propagated'`

**Propagation tiers**:
- Tier 1 (≤10% length diff): Auto-propagate (~94%)
- Tier 2 (10-20% length diff): Auto-propagate with verification (~5%)
- Tier 3 (>20% length diff): Skip, needs re-classification (~1%)

### Step 3: Domain Sequence Extraction

Extract domain sequences from chain sequences using range definitions.

```bash
# Extract for direct domains
python scripts/extract_domain_sequences.py \
    --domain-version "pyecod_prod_<batch_id>" \
    --input-fasta /path/to/all_chains.fasta \
    --output /path/to/domains/direct_domains.fasta

# Extract for propagated domains
python scripts/extract_domain_sequences.py \
    --domain-version "pyecod_prod_<batch_id>_propagated" \
    --input-fasta /path/to/all_chains.fasta \
    --output /path/to/domains/propagated_domains.fasta
```

**Verification**:
```sql
SELECT d.domain_version, COUNT(d.id) as domains, COUNT(ds.domain_id) as with_sequences
FROM ecod_commons.domains d
LEFT JOIN ecod_commons.domain_sequences ds ON d.id = ds.domain_id
WHERE d.domain_version LIKE 'pyecod_prod_<batch_id>%'
GROUP BY d.domain_version;
```

### Step 4: Pfam v38.1 Scanning

Run Pfam hmmscan for F-group assignment.

```bash
# Dry run (creates FASTA, splits chunks, shows command)
python scripts/submit_pfam_batch.py \
    --batch-dir /path/to/batch \
    --domain-version-pattern "pyecod_prod_<batch_id>%" \
    --dry-run

# Submit SLURM job
python scripts/submit_pfam_batch.py \
    --batch-dir /path/to/batch \
    --domain-version-pattern "pyecod_prod_<batch_id>%"
```

**Monitor**:
```bash
squeue -j <job_id>
ls /path/to/batch/pfam/*.domtblout | wc -l
```

### Step 5: Parse Pfam Results

Classify domains into F-group assignment tracks.

```bash
python scripts/parse_pfam_results.py \
    --batch-dir /path/to/batch \
    --domain-version-pattern "pyecod_prod_<batch_id>%"
```

**Output**:
- `pfam/domain_pfam_assignments.tsv` - Per-domain assignments
- `pfam/pfam_classification_report.json` - Summary with track counts

### Step 6: F-group Assignment

*TODO: Implement based on Pfam results*

**Track routing**:
- **Track 1**: Pfam matches existing F-group → assign directly
- **Track 2a**: Pfam needs new F-group → create F-group, assign ascending domain as provisional rep
- **Track 2b**: Multiple Pfam (composite) → manual curation queue
- **Track 3**: No Pfam hit → check for existing T-group match or manual curation

### Complete Workflow Script

For convenience, here's a template script for running the entire workflow:

```bash
#!/bin/bash
# Full auto-accession workflow
# Usage: ./run_batch_workflow.sh <batch_id> <partition_dir> <fasta_file> <start_date> <end_date>

set -euo pipefail

BATCH_ID=$1
PARTITION_DIR=$2
FASTA_FILE=$3
START_DATE=$4
END_DATE=$5

BATCH_DIR="/data/ecod/pdb_updates/batches/${BATCH_ID}"

source ~/.bashrc
export ECOD_DB_PASSWORD='ecod#badmin'
export PYTHONPATH=/home/rschaeff/dev/pyecod_prod/src:$PYTHONPATH

echo "=== Step 1: Auto-Accession ==="
python scripts/auto_accession_batch.py \
    "$PARTITION_DIR" \
    --batch-id "$BATCH_ID" \
    --min-coverage 0.80

echo "=== Step 2: Cluster Propagation ==="
python scripts/run_propagation_batch.py \
    --domain-version "pyecod_prod_${BATCH_ID}" \
    --start-date "$START_DATE" \
    --end-date "$END_DATE"

echo "=== Step 3: Sequence Extraction ==="
mkdir -p "${BATCH_DIR}/domains"

python scripts/extract_domain_sequences.py \
    --domain-version "pyecod_prod_${BATCH_ID}" \
    --input-fasta "$FASTA_FILE"

python scripts/extract_domain_sequences.py \
    --domain-version "pyecod_prod_${BATCH_ID}_propagated" \
    --input-fasta "$FASTA_FILE"

echo "=== Step 4: Pfam Scanning ==="
python scripts/submit_pfam_batch.py \
    --batch-dir "$BATCH_DIR" \
    --domain-version-pattern "pyecod_prod_${BATCH_ID}%"

echo "=== Workflow initiated ==="
echo "Monitor Pfam job and run parse_pfam_results.py when complete"
```

### Directory Structure

After running the workflow, batch directory should contain:

```
/data/ecod/pdb_updates/batches/<batch_id>/
├── partitions/              # Input partition XMLs
├── fastas/
│   └── all_chains.fasta     # Input chain sequences
├── domains/
│   ├── all_domains.fasta    # Combined domain sequences
│   └── chunks/              # Split for SLURM processing
│       ├── chunk_0001.fasta
│       └── ...
├── pfam/
│   ├── hmmscan_0001.domtblout
│   ├── hmmscan_0001.tblout
│   ├── domain_pfam_assignments.tsv
│   └── pfam_classification_report.json
├── slurm_logs/
│   ├── pfam_1.out
│   └── pfam_1.err
├── accession_report_final.json
└── propagation_summary.json
```

### Timing Estimates

Based on Q4 2025 + Q1 2026 batch (38,245 domains):

| Step | Duration | Notes |
|------|----------|-------|
| Auto-accession (4,497 domains) | ~40 min | 2 domains/sec |
| Propagation (33,748 domains) | ~90 min | 3.9 members/sec |
| Sequence extraction | ~5 min | 1000+ domains/sec |
| Pfam scanning (39 chunks) | ~60 min | Parallel SLURM jobs |
| Pfam parsing | ~5 min | - |
| **Total** | **~3-4 hours** | Mostly propagation + Pfam |

### Troubleshooting

**Propagation slower than expected**:
- Large clusters take longer due to database commits per member
- Run in background: `nohup python scripts/run_propagation_batch.py ... &`

**Sequence extraction missing sequences**:
- Check that chain sequences exist in FASTA file
- Domains with ranges exceeding chain length will fail (expected edge cases)

**Pfam job pending**:
- Check cluster availability: `sinfo`
- Default partition (96GB) should work for most jobs
- If nodes are DOWN/DRAINED, wait for cluster maintenance to complete

**No Pfam hits for domain**:
- Short domains (<30 residues) often have no Pfam match
- Disordered regions may not match HMMs
- Classified as Track 3 (no Pfam)
