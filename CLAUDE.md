# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

pyECOD Production Framework: Production pipeline for automated classification of new PDB protein structures into the ECOD (Evolutionary Classification of Protein Domains) hierarchy. Implements a two-pass search strategy (BLAST + HHsearch) with full SLURM integration, YAML-based state tracking, and end-to-end domain partitioning.

**Status**: Production-ready with all 9 workflow steps validated.

## Separation of Concerns

**This repository contains PRODUCTION INFRASTRUCTURE only.**

The domain partitioning algorithm lives in the separate **pyecod_mini** repository (as a library).

**See**: [PYECOD_MINI_API_SPEC.md](PYECOD_MINI_API_SPEC.md) for the formal API contract.

### Responsibilities

**pyecod_prod** (this repo):
- ✅ PDB data acquisition and parsing
- ✅ BLAST/HHsearch execution via SLURM
- ✅ Evidence generation (domain_summary.xml)
- ✅ Batch workflow orchestration (9-step pipeline)
- ✅ State tracking (manifest)
- ✅ Quality policy decisions (coverage thresholds)
- ✅ Database integration (future)
- ✅ Calls pyecod_mini for domain partitioning (step 8)

**pyecod_mini** (separate repo):
- ✅ Domain partitioning algorithm
- ✅ Evidence parsing (BLAST XML, HHR files)
- ✅ Coverage calculation from partitions
- ✅ Library API + simple CLI
- ❌ NO production infrastructure, NO SLURM, NO batch orchestration

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
- `SummaryGenerator`: Combine BLAST + HHsearch evidence into unified XML (domain_summary.xml format per API spec)
- `PartitionRunner`: Wrapper for pyecod-mini domain partitioning (calls library API or CLI, applies ECOD quality thresholds)

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

**Partitioning fails**: Check pyecod_mini is installed (`pip list | grep pyecod-mini`). Verify version compatibility with PYECOD_MINI_API_SPEC.md. Check partition_runner.py logs.

## File Paths Reference

### Key Source Files

- Main orchestrator: `src/pyecod_prod/batch/weekly_batch.py`
- Manifest manager: `src/pyecod_prod/batch/manifest.py`
- PDB parser: `src/pyecod_prod/parsers/pdb_status.py`
- BLAST runner: `src/pyecod_prod/slurm/blast_runner.py`
- HHsearch runner: `src/pyecod_prod/slurm/hhsearch_runner.py`
- Summary generator: `src/pyecod_prod/core/summary_generator.py`
- Partition runner: `src/pyecod_prod/core/partition_runner.py` (integration with pyecod_mini)
- API specification: `PYECOD_MINI_API_SPEC.md` (contract with pyecod_mini)

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

---

## Integration with pyecod_mini

### Overview

pyecod_prod generates domain evidence (BLAST + HHsearch), then calls pyecod_mini for domain partitioning.

**Integration Point**: Step 8 of the 9-step workflow via `PartitionRunner` class.

### Installation

```bash
# Install pyecod_mini as dependency
pip install pyecod-mini==1.0.0  # Pin specific version for reproducibility

# Or install from local path during development
pip install -e /path/to/pyecod_mini
```

### API Contract

**See**: [PYECOD_MINI_API_SPEC.md](PYECOD_MINI_API_SPEC.md) for complete specification.

**Input**: `domain_summary.xml` (generated by pyecod_prod in step 7)
**Output**: `partition.xml` (contains domains, coverage, algorithm version)

### Quality Assessment

**IMPORTANT**: Quality thresholds are ECOD production policy, NOT part of pyecod_mini algorithm.

Defined in `core/partition_runner.py`:

```python
def _assess_ecod_quality(domain_count, coverage, seq_length) -> str:
    """
    ECOD-specific quality thresholds (tunable based on production experience).
    """
    if domain_count == 0:
        return "no_domains"

    if coverage >= 0.80:
        return "good"           # Production-ready
    elif coverage >= 0.50:
        return "low_coverage"   # May need manual review
    else:
        return "fragmentary"    # Likely incomplete
```

**Coverage is calculated by pyecod_mini** and trusted by pyecod_prod. Quality labels are applied by pyecod_prod.

### Integration Patterns

**Preferred**: Use library API (when pyecod_mini installed as package)

```python
from pyecod_mini import partition_protein, PartitionError

try:
    result = partition_protein(
        summary_xml="summaries/8ovp_A.summary.xml",
        output_xml="partitions/8ovp_A.partition.xml",
        batch_id="ecod_weekly_20251019"
    )

    # Apply ECOD quality policy
    quality = _assess_ecod_quality(
        result.domain_count,
        result.coverage,
        result.sequence_length
    )

    manifest.mark_partition_complete(pdb_id, chain_id, result.coverage, quality)

except PartitionError as e:
    manifest.mark_partition_failed(pdb_id, chain_id, error=str(e))
    logger.error(f"Partitioning failed: {e}")
```

**Fallback**: Use CLI (if library not available)

```python
subprocess.run([
    "pyecod-mini",
    f"{pdb_id}_{chain_id}",
    "--summary-xml", summary_xml,
    "--output", partition_xml,
    "--batch-id", batch_id
], timeout=300, check=True)
```

### Version Compatibility

Track pyecod_mini version in requirements:

```
# requirements.txt
pyecod-mini>=1.0.0,<2.0.0  # Compatible with API spec v1.x
```

Verify algorithm version from output XML:

```python
# Parse partition.xml to check version
tree = ET.parse(partition_xml)
algo_version = tree.getroot().get("algorithm_version")
print(f"Used pyecod_mini version: {algo_version}")
```

### Testing Integration

```bash
# Test with small batch (15 chains)
python scripts/run_small_test.py

# Verify partition step completed
grep "partition_status: complete" /data/ecod/test_batches/*/batch_manifest.yaml

# Check algorithm version in output
grep "algorithm_version" /data/ecod/test_batches/*/partitions/*.xml
```

---

## New Features (October 2025)

### Family Lookup System

**Purpose**: Populate `target_family` attribute in domain_summary.xml with ECOD family names.

**Implementation**:
- Lookup file: `/data/ecod/database_versions/v291/domain_family_lookup.tsv` (1,083,021 mappings)
- Generated from ECOD XML `f_group` elements via `scripts/build_family_lookup.py`
- Loaded automatically by `WeeklyBatch` on initialization
- Gracefully handles missing lookup (logs warning, uses empty dict)

**Usage**:
```python
from pyecod_prod.utils.family_lookup import load_family_lookup_for_version

# Load for specific ECOD version
lookup = load_family_lookup_for_version("develop291")

# Use in summary generator
generator = SummaryGenerator(
    reference_version="develop291",
    family_lookup=lookup
)
```

**Regenerate lookup**:
```bash
python scripts/build_family_lookup.py \
    /data/ecod/database_versions/v291/ecod.develop291.xml \
    /data/ecod/database_versions/v291/domain_family_lookup.tsv
```

**Validation**:
```bash
# Test lookup
python -c "
from pyecod_prod.utils.family_lookup import load_family_lookup_for_version
lookup = load_family_lookup_for_version('develop291')
print(f'Loaded {len(lookup):,} mappings')
print(f'e1suaA1 → {lookup.get(\"e1suaA1\", \"NOT FOUND\")}')"

# Verify in summary XMLs
grep 'target_family' /data/ecod/pdb_updates/batches/*/summaries/*.xml
```

### Library API Integration

**Status**: pyecod_mini now provides a stable library API (as of v2.0.0).

**Detection**:
```python
from pyecod_prod.core.partition_runner import LIBRARY_AVAILABLE

if LIBRARY_AVAILABLE:
    print("✅ Using library API (faster, cleaner)")
else:
    print("⚠️  Using CLI fallback")
```

**Benefits**:
- ⚡ **Performance**: No subprocess overhead
- 🛡️ **Reliability**: Direct exception handling
- 📊 **Simplicity**: Structured dataclasses, not XML parsing
- 🔍 **Debugging**: Direct stack traces
- 📝 **Versioning**: Algorithm version auto-tracked

**API Usage** (handled automatically by PartitionRunner):
```python
from pyecod_mini import partition_protein, PartitionResult, PartitionError

result = partition_protein(
    summary_xml="/path/to/summary.xml",
    output_xml="/path/to/partition.xml",
    pdb_id="8abc",
    chain_id="A",
    batch_id="ecod_weekly_20251019",
)

# Result structure
print(f"Success: {result.success}")
print(f"Domains: {len(result.domains)}")
print(f"Coverage: {result.coverage:.1%}")
print(f"Algorithm version: {result.algorithm_version}")
```

### Version Tracking

**Purpose**: Track pyecod_mini algorithm version for reproducibility and debugging.

**Implementation**:
- `PartitionResult.algorithm_version` field captures version
- Stored in batch manifest for each chain
- Written to partition XML metadata
- Logged in all outputs

**Validation**:
```bash
# Check version in partition XMLs
grep 'algorithm.*version' /data/ecod/pdb_updates/batches/*/partitions/*.xml

# Expected output:
# <version algorithm="2.0.0" git_commit="..." timestamp="..."/>
```

**Version Compatibility**:
```python
# pyecod_prod expects semantic versioning
# Requirements: pyecod-mini>=2.0.0,<3.0.0

# Version changes:
# - MAJOR (3.0.0): Breaking API/algorithm changes
# - MINOR (2.1.0): New features, backward-compatible
# - PATCH (2.0.1): Bug fixes only
```

---

## References

- [PYECOD_MINI_API_SPEC.md](PYECOD_MINI_API_SPEC.md) - Formal API contract with pyecod_mini
- [docs/VERSION_TRACKING.md](docs/VERSION_TRACKING.md) - Implementation roadmap for versioning
- [docs/sessions/SESSION_SUMMARY_20251019.md](docs/sessions/SESSION_SUMMARY_20251019.md) - Recent feature implementation
- pyecod_mini repository: `/home/rschaeff/dev/pyecod_mini/`
- ECOD database: https://prodata.swmed.edu/ecod/
