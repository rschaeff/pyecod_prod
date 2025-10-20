# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

pyECOD Production Framework: Production pipeline for automated classification of new PDB protein structures into the ECOD (Evolutionary Classification of Protein Domains) hierarchy. Implements a two-pass search strategy (BLAST + HHsearch) with full SLURM integration, YAML-based state tracking, and end-to-end domain partitioning.

**Status**: Production-ready with all 9 workflow steps validated.

## Development Commands

### Environment Setup

```bash
# Add to PYTHONPATH for development
export PYTHONPATH=/home/rschaeff/dev/pyecod_prod/src:$PYTHONPATH

# Install package in editable mode (requires pytest, black, ruff, mypy)
pip install -e ".[dev]"

# Verify installation
python -c "from pyecod_prod.batch.weekly_batch import WeeklyBatch; print('OK')"
```

### Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test suites
pytest tests/unit/test_batch_manifest.py -v
pytest tests/integration/test_blast_workflow.py -v
pytest tests/integration/test_hhsearch_workflow.py -v

# Small-scale production test (15 chains from real PDB release)
cd /home/rschaeff/dev/pyecod_prod
python scripts/run_small_test.py
```

### Code Quality

```bash
# Format code with black (100 char line length)
black src/ tests/

# Lint with ruff
ruff check src/ tests/

# Type check with mypy
mypy src/
```

## Architecture Overview

### File-First Design Pattern

The framework uses a **file-first architecture** where YAML manifests are the primary source of truth (not database):

- All workflow state tracked in `batch_manifest.yaml`
- Human-readable, git-friendly, easy to debug
- Database integration is optional (for indexing/coordination only)
- Enables resumable processing from any workflow step

### Two-Pass Search Strategy

**Why Two Passes?**
- BLAST is fast but less sensitive (sequence-to-sequence)
- HHsearch is slow but more sensitive (profile-to-profile)
- ~50-60% of chains have good BLAST coverage (≥90%)
- Only low-coverage chains need expensive HHsearch

**Decision Logic**:
```python
if blast_coverage >= 0.90:
    needs_hhsearch = False  # Use BLAST evidence only
else:
    needs_hhsearch = True   # Run HHsearch for additional evidence
```

### Core Workflow (9 Steps)

1. **Parse PDB Updates**: Extract chains from weekly PDB release, filter peptides (<20 residues)
2. **Generate FASTAs**: Write `.fa` files for classifiable chains
3. **Submit BLAST Jobs**: Chain + domain BLAST via SLURM arrays (max 500 concurrent)
4. **Process BLAST Results**: Calculate coverage, identify low-coverage chains (<90%)
5. **Submit HHsearch Jobs**: Profile-to-profile search for low-coverage chains only
6. **Process HHsearch Results**: Parse HHR files, update manifest
7. **Generate Summaries**: Combine BLAST + HHsearch evidence into domain_summary.xml
8. **Run Partitioning**: Execute pyecod-mini for domain assignments
9. **Complete**: All chains processed and partitioned

### Key Components

**Orchestration** (`batch/weekly_batch.py`):
- `WeeklyBatch` class coordinates complete workflow
- Manages component initialization and SLURM job submission
- Implements resume capability via manifest
- Entry point: `run_complete_workflow()`

**State Management** (`batch/manifest.py`):
- `BatchManifest` class tracks all processing state in YAML
- Methods: `add_chain()`, `mark_blast_complete()`, `mark_hhsearch_complete()`, `mark_partition_complete()`
- Query methods: `chains_needing_hhsearch()`, `get_chain_data()`, `print_summary()`

**SLURM Integration** (`slurm/`):
- `BlastRunner`: BLAST job arrays (chain + domain databases)
- `HHsearchRunner`: HHsearch job arrays (low-coverage chains only)
- Features: Job submission, monitoring via `squeue`/`sacct`, coverage parsing

**Data Parsing** (`parsers/`):
- `PDBStatusParser`: Parse PDB weekly releases, filter peptides (≥20 residues), extract chains from mmCIF
- `HHsearchParser`: Parse HHR output files

**Core Processing** (`core/`):
- `SummaryGenerator`: Combine BLAST + HHsearch evidence into unified XML
- `PartitionRunner`: Wrapper for pyecod-mini domain partitioning

## Critical Configuration

### Database Locations

**BLAST Databases (ECOD v291)**:
```
/data/ecod/database_versions/v291/chainwise100.develop291.psq  # Chain-level
/data/ecod/database_versions/v291/ecod100.develop291.psq       # Domain-level
```

**HHsearch Database (ECOD v291)**:
```
/data/ecod/database_versions/v291/ecod_v291_hhm.ffdata   # 1.2GB HMM profiles
/data/ecod/database_versions/v291/ecod_v291_hhm.ffindex
```

**Important**: HHsearch database path should be `/data/ecod/database_versions/v291/ecod_v291` (without `_hhm` suffix). HHsearch automatically appends `_hhm.ffdata` and `_hhm.ffindex`.

### System Tools

```bash
BLAST+: /sw/apps/ncbi-blast-2.15.0+/bin/blastp
HH-suite: /sw/apps/hh-suite/bin/hhsearch
pyecod-mini: /home/rschaeff/.local/bin/pyecod-mini
```

### PDB Data Locations

```
mmCIF files: /usr2/pdb/data/structures/divided/mmCIF/{middle_2_letters}/{pdb_id}.cif.gz
Status files: /usr2/pdb/data/status/{YYYYMMDD}/added.pdb
```

### Batch Output Structure

```
/data/ecod/pdb_updates/batches/ecod_weekly_20251019/
├── batch_manifest.yaml      # Primary state tracking
├── pdb_entries.txt          # Reference copy of added.pdb
├── fastas/                  # Input FASTA files
├── blast/                   # BLAST XML results (chain + domain)
├── hhsearch/                # HHsearch HHR results (low-coverage only)
├── summaries/               # Domain summary XML (BLAST + HHsearch combined)
├── partitions/              # pyecod-mini partition XML
├── slurm_logs/              # Job output/error logs
└── scripts/                 # Generated SLURM submission scripts
```

## Important Design Decisions

### Peptide Filtering

Chains shorter than 20 residues are automatically filtered and marked as non-classifiable:
- Threshold: 20 residues (configurable: `parsers/pdb_status.py:PDBStatusParser.PEPTIDE_THRESHOLD`)
- Rationale: Too short for reliable domain classification
- Typical rate: ~1.6% of chains (28/1705 in 2025-09-05 release)

### SLURM Array Job Limits

Use `--array=1-N%LIMIT` to avoid overwhelming the cluster scheduler:
- BLAST: `--array=1-1677%500` (max 500 concurrent jobs)
- HHsearch: `--array=1-234%500` (max 500 concurrent jobs)

### Coverage Calculation

**BLAST Coverage**: Union of all HSP (high-scoring segment pair) regions
**HHsearch Coverage**: Union of all alignment regions from Q lines in HHR file

Both calculate: `coverage = len(covered_positions) / query_length`

### Resumable Workflow

Every workflow step checks manifest status before executing:
```python
manifest = BatchManifest(batch_dir)
if chain_data["blast_status"] == "complete":
    continue  # Skip already processed chains

# Do work...
manifest.mark_blast_complete(pdb_id, chain_id, coverage=0.95)
manifest.save()
```

## Common Development Tasks

### Create and Process a Batch

```python
from pyecod_prod.batch.weekly_batch import WeeklyBatch

batch = WeeklyBatch(
    release_date="2025-10-19",
    pdb_status_dir="/usr2/pdb/data/status/20251019",
    base_path="/data/ecod/pdb_updates/batches",
    reference_version="develop291"
)

# Run complete workflow (all 9 steps)
batch.run_complete_workflow(submit_blast=True, submit_hhsearch=True)
```

### Resume Existing Batch

```python
# Manifest automatically loaded
batch = WeeklyBatch(
    release_date="2025-10-19",
    pdb_status_dir="/usr2/pdb/data/status/20251019",
    base_path="/data/ecod/pdb_updates/batches"
)

# Check status
batch.manifest.print_summary()

# Continue from where it left off
batch.generate_summaries()
batch.run_partitioning()
```

### Check Batch Status

```python
from pyecod_prod.batch.manifest import BatchManifest

manifest = BatchManifest("/data/ecod/pdb_updates/batches/ecod_weekly_20251019")
manifest.print_summary()

# Get chains needing HHsearch
low_coverage = manifest.chains_needing_hhsearch()
print(f"Chains needing HHsearch: {len(low_coverage)}")
```

### Manual SLURM Job Submission

```python
# Submit BLAST without waiting
job_id, _ = batch.run_blast(partition="96GB", array_limit=500, wait=False)

# Check status later
status = batch.blast_runner.check_job_status(job_id)
# Returns: {'running': 100, 'pending': 50, 'completed': 0, 'failed': 0}

# Process results after completion
batch.process_blast_results()
```

## Troubleshooting

### Check SLURM Logs

```bash
# BLAST errors
ls /path/to/batch/slurm_logs/blast_*.err
cat /path/to/batch/slurm_logs/blast_264895_1.err

# HHsearch errors
ls /path/to/batch/slurm_logs/hhsearch_*.err
cat /path/to/batch/slurm_logs/hhsearch_264910_1.err
```

### Verify Database Files

```bash
# BLAST databases
ls -lh /data/ecod/database_versions/v291/*.psq

# HHsearch databases (should see _hhm.ffdata and _hhm.ffindex)
ls -lh /data/ecod/database_versions/v291/ecod_v291_hhm*
```

### Common Issues

**HHsearch database not found**: Ensure path is `/data/ecod/database_versions/v291/ecod_v291` (without `_hhm`). HHsearch auto-appends the suffix.

**SLURM jobs stuck in pending**: Check array limits (`%500`) and cluster load with `squeue -u $USER`.

**Peptides not filtered**: Verify `PDBStatusParser.PEPTIDE_THRESHOLD = 20` in `parsers/pdb_status.py:74`.

## File Paths Reference

### Key Source Files

- Main orchestrator: `src/pyecod_prod/batch/weekly_batch.py`
- Manifest manager: `src/pyecod_prod/batch/manifest.py`
- PDB parser: `src/pyecod_prod/parsers/pdb_status.py`
- BLAST runner: `src/pyecod_prod/slurm/blast_runner.py`
- HHsearch runner: `src/pyecod_prod/slurm/hhsearch_runner.py`
- Summary generator: `src/pyecod_prod/core/summary_generator.py`
- Partition runner: `src/pyecod_prod/core/partition_runner.py`

### Test Files

- Unit tests: `tests/unit/test_batch_manifest.py`
- Integration tests: `tests/integration/test_blast_workflow.py`, `test_hhsearch_workflow.py`
- Production test: `scripts/run_small_test.py`

### Data Locations

- Batch output: `/data/ecod/pdb_updates/batches/`
- Test batches: `/data/ecod/test_batches/`
- BLAST/HHsearch DBs: `/data/ecod/database_versions/v291/`
- PDB mirror: `/usr2/pdb/data/structures/divided/mmCIF/`
- PDB status: `/usr2/pdb/data/status/{YYYYMMDD}/`

## SLURM Job Configuration

### BLAST Jobs

```bash
Partition: 96GB
Time: 4:00:00
Memory: 8GB
CPUs: 1
Array limit: 500
E-value: 0.002
Max alignments: 5,000
```

### HHsearch Jobs

```bash
Partition: 96GB
Time: 8:00:00
Memory: 16GB
CPUs: 4
Array limit: 500
E-value: 0.001
Min probability: 50
Max alignments: 5,000
```

## Production Validation

Small-scale test results (15 chains from 2025-09-05 release):
```
✓ Peptide filtering: 28 filtered (1.6% of 1,705 chains)
✓ BLAST pipeline: 15/15 complete (100%)
✓ Coverage analysis: 8 chains low coverage (<90%)
✓ HHsearch pipeline: 8/8 complete (100%)
✓ Summary generation: 15/15 complete (100%)
✓ Partitioning: 15/15 complete (100%)
```

All 9 workflow steps validated and production-ready.
