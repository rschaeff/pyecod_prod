# pyECOD Production Framework

Production-ready pipeline for processing weekly PDB updates with ECOD domain classification.

## Overview

This framework automates the classification of new PDB structures using a two-pass approach:
1. **BLAST search** against ECOD domain and chain databases (all chains)
2. **HHsearch** for chains with low BLAST coverage (<90%)

This ensures comprehensive coverage while optimizing computational resources.

## Architecture

```
pyecod_prod/
├── src/pyecod_prod/
│   ├── batch/              # Batch orchestration
│   │   ├── weekly_batch.py # Main workflow coordinator
│   │   └── manifest.py     # Batch state tracking (YAML-based)
│   ├── parsers/            # Data parsers
│   │   └── pdb_status.py   # PDB weekly update parser (peptide filtering)
│   ├── slurm/              # HPC job submission
│   │   ├── blast_runner.py # BLAST job arrays
│   │   └── hhsearch_runner.py # HHsearch job arrays
│   ├── core/               # Core processing
│   │   ├── summary_generator.py # Domain summary XML generation
│   │   └── partition_runner.py  # pyecod-mini partitioning
│   └── utils/              # Utilities
│       └── directories.py  # Batch directory structure management
├── scripts/
│   └── run_small_test.py   # Small-scale production test (15 chains)
└── tests/                  # Unit tests
```

## Workflow

### Complete Weekly Batch Processing

```bash
# Process PDB weekly update from 2025-10-19
python -m pyecod_prod.batch.weekly_batch 2025-10-19 \
    --status-dir /usr2/pdb/data/status/20251019 \
    --base-path /data/ecod/pdb_updates/batches
```

**Processing Steps:**

1. **Create Batch** (`create_batch()`)
   - Initialize directory structure: fastas/, blast/, hhsearch/, summaries/, partitions/, slurm_logs/
   - Create batch_manifest.yaml to track all chains

2. **Parse PDB Updates** (`process_pdb_updates()`)
   - Parse added.pdb from /usr2/pdb/data/status/{YYYYMMDD}/
   - Extract chains from PDB files
   - Filter peptides (<20 residues) - marked as non-classifiable
   - Validate sequences with Biopython
   - Add chains to manifest with metadata

3. **Generate FASTAs** (`generate_fastas()`)
   - Create .fa files for all classifiable chains
   - Store in {batch}/fastas/ directory

4. **Submit BLAST Jobs** (`run_blast()`)
   - Parallel SLURM job array (max 500 concurrent)
   - Chain BLAST: vs chainwise100.develop291
   - Domain BLAST: vs ecod100.develop291
   - E-value: 0.002, Max alignments: 5,000
   - Output: XML format (outfmt 5)

5. **Process BLAST Results** (`process_blast_results()`)
   - Parse XML output files
   - Calculate query coverage (union of all HSP regions)
   - Mark chains with coverage <90% as needing HHsearch
   - Update manifest with coverage stats

6. **Submit HHsearch Jobs** (`run_hhsearch()`)
   - Only for chains with BLAST coverage <90%
   - Profile-to-profile search vs ecod_v291_hhm
   - E-value: 0.001, Min prob: 50, Max alignments: 5,000
   - Parallel SLURM job array (max 500 concurrent)

7. **Process HHsearch Results** (`process_hhsearch_results()`)
   - Parse .hhr output files
   - Calculate query coverage from alignments
   - Update manifest with HHsearch stats

8. **Generate Summaries** (`generate_summaries()`)
   - Combine BLAST + HHsearch evidence
   - Create domain_summary.xml files
   - Format compatible with pyecod-mini

9. **Run Partitioning** (`run_partitioning()`)
   - Execute pyecod-mini on each summary
   - Generate domain partition assignments
   - Update manifest with partition results

### Batch Manifest Format

Each batch maintains a YAML manifest tracking state:

```yaml
batch_name: ecod_weekly_20251019
batch_type: weekly
reference_version: develop291
created: 2025-10-19T10:00:00
pdb_status_path: /usr2/pdb/data/status/20251019

processing_status:
  total_structures: 1677
  blast_complete: 1677
  hhsearch_needed: 234
  hhsearch_complete: 234
  partition_complete: 1677

chains:
  8s72_A:
    pdb_id: "8s72"
    chain_id: A
    sequence: MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKRQTLGQHDFSAGEGLYTHMKALRPDE
    sequence_length: 105
    can_classify: true
    blast_status: complete
    blast_coverage: 0.95
    needs_hhsearch: false
    hhsearch_status: not_needed
    partition_status: complete
    partition_coverage: 0.95
    domain_count: 1
    partition_quality: high
    files:
      fasta: fastas/8s72_A.fa
      chain_blast: blast/8s72_A.chain_blast.xml
      domain_blast: blast/8s72_A.domain_blast.xml
      summary: summaries/8s72_A_summary.xml
      partition: partitions/8s72_A_partition.xml

  8yl2_A:
    pdb_id: "8yl2"
    chain_id: A
    sequence: GSHMENLYFQGFQVDNGFELLKISDIVNAGIEKVAKKIDQKLGG
    sequence_length: 45
    can_classify: true
    blast_status: complete
    blast_coverage: 0.65
    needs_hhsearch: true
    hhsearch_status: complete
    hhsearch_coverage: 0.89
    partition_status: complete
    files:
      fasta: fastas/8yl2_A.fa
      chain_blast: blast/8yl2_A.chain_blast.xml
      domain_blast: blast/8yl2_A.domain_blast.xml
      hhsearch: hhsearch/8yl2_A.hhr
      summary: summaries/8yl2_A_summary.xml
      partition: partitions/8yl2_A_partition.xml

slurm_jobs:
  - job_id: "264895"
    job_type: blast
    chains: [8s72_A, 8s72_N, 8yl2_A, ...]
    partition: 96GB
    submitted: 2025-10-19T10:05:00
    status: completed
  - job_id: "264910"
    job_type: hhsearch
    chains: [8yl2_A, 8yl2_B, ...]
    partition: 96GB
    submitted: 2025-10-19T10:15:00
    status: completed
```

## Peptide Filtering

Chains shorter than 20 residues are automatically filtered:

**Configuration** (/home/rschaeff/dev/pyecod_prod/src/pyecod_prod/parsers/pdb_status.py:74)
```python
PEPTIDE_THRESHOLD = 20  # Minimum residues for classification
```

**Manifest Representation:**
```yaml
chains:
  8abc_Z:
    pdb_id: "8abc"
    chain_id: Z
    sequence: MKTA
    sequence_length: 4
    can_classify: false
    cannot_classify_reason: peptide
```

**Test Results (2025-09-05 release):**
- Total chains: 1,705
- Peptides filtered: 28 (1.6%)
- Classifiable: 1,677

## Database Configuration

### BLAST Databases (v291)

Location: `/data/ecod/database_versions/v291/`

```
chainwise100.develop291.psq     # Chain-level database
ecod100.develop291.psq          # Domain-level database
```

**Parameters:**
- E-value threshold: 0.002
- Max alignments: 5,000
- Output format: XML (5)

### HHsearch Database (v291)

Location: `/data/ecod/database_versions/v291/`

```
ecod_v291_hhm.ffdata            # Main HMM profiles (1.2GB)
ecod_v291_hhm.ffindex           # Index file
ecod_v291_hhm_cs219.ffdata      # Context-specific profiles
ecod_v291_hhm_cs219.ffindex     # CS219 index
```

**Source:** `ecod_v291_hhdb_vjzhang.tar.gz` (7.7GB compressed)

**Parameters:**
- E-value threshold: 0.001
- Minimum probability: 50
- Max alignments: 5,000 (-Z/-B flags)

## SLURM Configuration

### BLAST Job Arrays

Script template: `/home/rschaeff/dev/pyecod_prod/src/pyecod_prod/slurm/blast_runner.py:115-177`

```bash
#SBATCH --job-name=blast_both
#SBATCH --partition=96GB
#SBATCH --array=1-N%500        # Max 500 concurrent jobs
#SBATCH --time=4:00:00
#SBATCH --mem=8G
#SBATCH --cpus-per-task=1
#SBATCH --output={batch}/slurm_logs/blast_%A_%a.out
#SBATCH --error={batch}/slurm_logs/blast_%A_%a.err

export PATH="/sw/apps/ncbi-blast-2.15.0+/bin:$PATH"

blastp -query $FASTA_FILE \
       -db {database} \
       -outfmt 5 \
       -num_alignments 5000 \
       -evalue 0.002 \
       -out $OUTPUT_FILE
```

### HHsearch Job Arrays

Script template: `/home/rschaeff/dev/pyecod_prod/src/pyecod_prod/slurm/hhsearch_runner.py:107-152`

```bash
#SBATCH --job-name=hhsearch
#SBATCH --partition=96GB
#SBATCH --array=1-N%500        # Max 500 concurrent jobs
#SBATCH --time=8:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=4
#SBATCH --output={batch}/slurm_logs/hhsearch_%A_%a.out
#SBATCH --error={batch}/slurm_logs/hhsearch_%A_%a.err

export PATH="/sw/apps/hh-suite/bin:$PATH"

hhsearch -i $FASTA_FILE \
         -d /data/ecod/database_versions/v291/ecod_v291 \
         -o $OUTPUT_FILE \
         -e 0.001 \
         -p 50 \
         -Z 5000 \
         -B 5000 \
         -cpu 4 \
         -v 2

# Note: HHsearch automatically appends _hhm.ffdata and _hhm.ffindex to the database path
```

## Small-Scale Testing

Test the complete workflow with 15 chains from a real PDB release:

```bash
cd /home/rschaeff/dev/pyecod_prod
source ~/.bashrc
python scripts/run_small_test.py
```

**Test Configuration:**
- PDB Release: 2025-09-05
- Total entries: 309
- Total chains: 1,705
- Classifiable: 1,677
- Peptides filtered: 28
- **Test subset: 15 chains** (limited for fast validation)

**Output Location:**
```
/data/ecod/test_batches/ecod_weekly_20250905/
├── batch_manifest.yaml
├── fastas/          # 15 FASTA files
├── blast/           # 30 XML files (chain + domain)
├── hhsearch/        # ~8 HHR files (low-coverage only)
├── summaries/       # 15 domain_summary.xml files
├── partitions/      # 15 partition.xml files
└── slurm_logs/      # Job output logs
```

**Expected Test Results:**
```
✓ Batch creation: Success
✓ PDB parsing: 1,677 classifiable, 28 peptides filtered
✓ FASTA generation: 15 files
✓ BLAST submission: 15/15 complete (100%)
✓ BLAST coverage: ~8 chains need HHsearch
✓ HHsearch submission: 8/8 complete (100%)
✓ Summary generation: 15/15 complete (100%)
✓ Partitioning: 15/15 complete (100%)
```

## Installation & Setup

### Prerequisites

**Python Dependencies:**
```bash
pip install biopython pyyaml
```

**System Tools (pre-installed on cluster):**
```
BLAST: /sw/apps/ncbi-blast-2.15.0+/bin/blastp
HH-suite: /sw/apps/hh-suite/bin/hhsearch
pyecod-mini: /home/rschaeff/.local/bin/pyecod-mini (or in PATH)
```

### Environment Setup

```bash
# Add to ~/.bashrc or session
export PYTHONPATH=/home/rschaeff/dev/pyecod_prod/src:$PYTHONPATH

# Verify installation
python -c "from pyecod_prod.batch.weekly_batch import WeeklyBatch; print('OK')"
```

### HHsearch Database Setup

Extract the complete HHsearch database (one-time setup):

```bash
cd /data/ecod/database_versions/v291

# Extract all database files (7.7GB, may take several minutes)
tar -xzf ecod_v291_hhdb_vjzhang.tar.gz

# Create symlinks for CS219 files (naming convention)
ln -sf ecod_v291_cs219.ffdata ecod_v291_hhm_cs219.ffdata
ln -sf ecod_v291_cs219.ffindex ecod_v291_hhm_cs219.ffindex

# Verify files
ls -lh ecod_v291_hhm* ecod_v291*cs219*
```

## Current Status (2025-10-19)

### Production-Ready Components ✅
- ✅ Weekly batch orchestration (WeeklyBatch class)
- ✅ PDB status file parsing with peptide filtering (<20 residues)
- ✅ BLAST job submission and monitoring via SLURM
- ✅ HHsearch submission for low-coverage chains (<90% BLAST coverage)
- ✅ YAML-based manifest tracking (file-first architecture)
- ✅ Domain summary generation (BLAST + HHsearch evidence)
- ✅ SLURM array job management with concurrent limits
- ✅ Coverage calculation from XML/HHR output
- ✅ Batch resume capability via manifest
- ✅ pyecod-mini integration for domain partitioning
- ✅ End-to-end workflow validation (all 9 steps)

### Known Issues & Solutions

1. **HHsearch Database Path** (RESOLVED ✓)
   - Issue: Database path included `_hhm` suffix, but HHsearch auto-appends it
   - Solution: Changed database path from `ecod_v291_hhm` to `ecod_v291`
   - Code: `/home/rschaeff/dev/pyecod_prod/src/pyecod_prod/slurm/hhsearch_runner.py:26`
   - Status: Fixed - HHsearch now finds `ecod_v291_hhm.ffdata` correctly

2. **HHsearch Results Processing** (RESOLVED ✓)
   - Issue: API mismatch - `mark_hhsearch_complete()` called with non-existent `coverage` parameter
   - Solution: Removed `coverage=coverage` argument from function call
   - Code: `/home/rschaeff/dev/pyecod_prod/src/pyecod_prod/batch/weekly_batch.py:409`
   - Status: Fixed - Results processing now works correctly

3. **pyecod-mini Integration** (RESOLVED ✓)
   - Issue: pyecod-mini didn't support `--summary-xml` and `--output` arguments
   - Solution: Enhanced pyecod-mini CLI to accept custom paths for integration
   - Code: `/home/rschaeff/dev/pyecod_mini/src/pyecod_mini/cli/main.py`
   - Status: Fixed - Full end-to-end partitioning working

4. **pyecod-mini Path Configuration** (RESOLVED ✓)
   - Issue: pyecod-mini executable path hardcoded
   - Solution: Configured absolute path in weekly_batch.py initialization
   - Code: `/home/rschaeff/dev/pyecod_prod/src/pyecod_prod/batch/weekly_batch.py:75`
   - Status: Fixed - Using `/home/rschaeff/.local/bin/pyecod-mini`

### Production Validation Results

**Small-scale test (15 chains from 2025-09-05 release):**
```
Peptide filtering:    ✓ 28 filtered (1.6% of 1,705 chains)
BLAST pipeline:       ✓ 15/15 complete (100% success)
Coverage analysis:    ✓ 8 chains identified as low coverage (<90%)
HHsearch pipeline:    ✓ 8/8 complete (100% success)
HHsearch processing:  ✓ 8/8 results processed
Summary generation:   ✓ 15/15 summaries created (100%)
Partitioning:         ✓ 15/15 partitions complete (100%)
```

**Workflow Status:**
- **BLAST-only mode**: ✅ Production-ready (chains with >90% coverage)
- **Two-pass mode**: ✅ Production-ready (BLAST + HHsearch for full coverage)
- **Partitioning**: ✅ Production-ready (full pyecod-mini integration complete)
- **End-to-end**: ✅ All 9 workflow steps validated and working

## Usage Examples

### Process Weekly PDB Release

```python
from pyecod_prod.batch.weekly_batch import WeeklyBatch

batch = WeeklyBatch(
    release_date="2025-10-19",
    pdb_status_dir="/usr2/pdb/data/status/20251019",
    base_path="/data/ecod/pdb_updates/batches",
    reference_version="develop291"
)

# Run complete workflow (BLAST + HHsearch + partitioning)
batch.run_complete_workflow(submit_blast=True, submit_hhsearch=True)
```

### Resume Existing Batch

```python
# Manifest automatically loaded from existing batch
batch = WeeklyBatch(
    release_date="2025-10-19",
    pdb_status_dir="/usr2/pdb/data/status/20251019",
    base_path="/data/ecod/pdb_updates/batches"
)

# Check current status
batch.manifest.print_summary()

# Continue from where it left off
batch.generate_summaries()
batch.run_partitioning()
```

### Check Coverage Statistics

```python
from pyecod_prod.batch.manifest import BatchManifest

manifest = BatchManifest("/data/ecod/pdb_updates/batches/ecod_weekly_20251019")

# Get chains needing HHsearch
low_coverage = manifest.chains_needing_hhsearch()
print(f"Chains needing HHsearch: {len(low_coverage)}")

# Print detailed summary
manifest.print_summary()
```

### Manual BLAST/HHsearch Submission

```python
# Submit just BLAST jobs (don't wait)
job_id, _ = batch.run_blast(partition="96GB", array_limit=500, wait=False)
print(f"BLAST job: {job_id}")

# Check status later
status = batch.blast_runner.check_job_status(job_id)
print(status)  # {'running': 100, 'pending': 50, 'completed': 0, 'failed': 0}

# Submit HHsearch after BLAST completes
batch.process_blast_results()
hhsearch_job_id, success = batch.run_hhsearch(wait=True)
```

## Troubleshooting

### Check Batch Status

```python
from pyecod_prod.batch.manifest import BatchManifest

manifest = BatchManifest("/path/to/batch/")
manifest.print_summary()
```

### Review SLURM Logs

```bash
# Check BLAST errors
ls /path/to/batch/slurm_logs/blast_*.err

# Check HHsearch errors
ls /path/to/batch/slurm_logs/hhsearch_*.err

# View specific error
cat /path/to/batch/slurm_logs/blast_264895_1.err
```

### Verify Database Files

```bash
# BLAST databases
ls -lh /data/ecod/database_versions/v291/*.psq

# HHsearch databases
ls -lh /data/ecod/database_versions/v291/ecod_v291_hhm*
ls -lh /data/ecod/database_versions/v291/ecod_v291*cs219*
```

## Future Enhancements

### Phase 2: Validation Pipeline (Next Priority)
- Detect PDB obsoletes and modifications
- Monthly ECOD vs PDB reconciliation
- Automated repair batch generation
- Track superseded structures

### Phase 3: Hierarchy Propagation
- Monitor ECOD hierarchy changes (X-group splits, H-group merges)
- Automated domain reclassification
- Change manifest format
- Impact analysis tools

### Phase 4: Monitoring & Automation
- Central tracking database (PostgreSQL)
- Web dashboard for batch monitoring
- Automated weekly cron jobs
- Email/Slack alerts for failures

### Phase 5: Performance Optimization
- Database caching for repeat queries
- Parallel summary generation
- Incremental processing for large batches

## Key Design Principles

1. **File-First Architecture**: YAML manifests are primary source of truth
2. **Resumable**: All state tracked in manifest, can resume from any step
3. **Transparent**: Human-readable YAML, clear directory structure
4. **SLURM-Native**: Designed for HPC cluster execution
5. **Two-Pass Efficiency**: BLAST first (fast), HHsearch only when needed
6. **Peptide-Aware**: Automatic filtering of short peptides (<20 residues)

## Related Projects

- **pyecod-mini**: Domain partitioning algorithm (consumes domain_summary.xml)
- **ECOD Database**: Evolutionary Classification of Protein Domains
- **PDB**: RCSB Protein Data Bank

## Support & Documentation

- Manifest tracking: Check `batch_manifest.yaml` for current state
- SLURM logs: Review logs in `{batch}/slurm_logs/` for job details
- Code reference: Docstrings in all modules
- Test suite: `pytest tests/` for validation

## References

- BLAST: NCBI BLAST+ 2.15.0 (https://blast.ncbi.nlm.nih.gov/)
- HH-suite: Profile HMM-HMM comparison (https://github.com/soedinglab/hh-suite)
- ECOD: http://prodata.swmed.edu/ecod/
- PDB: https://www.rcsb.org/

## License

Internal ECOD project
