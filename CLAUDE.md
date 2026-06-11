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
- ✅ Designed protein detection and filtering
- ✅ Sequence clustering (mmseqs2/CD-HIT) for redundancy reduction
- ✅ BLAST/HHsearch execution via SLURM
- ✅ Evidence generation (domain_summary.xml)
- ✅ Batch workflow orchestration (9-step pipeline)
- ✅ State tracking (manifest)
- ✅ Quality policy decisions (coverage thresholds)
- ✅ Database integration for tracking and coordination
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

### Reference Version Registry (single source of truth)

All reference paths (BLAST DBs, HHsearch DB, family/classification lookups, and the
reference CSVs handed to pyecod_mini) are resolved from one declarative registry —
`src/pyecod_prod/config/references.yaml` — keyed by canonical version (`v291`,
`v294.2`; `develop291` is an alias for `v291`). This replaced ad-hoc per-component
hardcoding, which had let the HHsearch DB drift to a different ECOD version than the
BLAST DBs / lookups (a correctness hazard on reclassification releases).

```python
from pyecod_prod.utils.reference_config import ReferenceConfig
ref = ReferenceConfig.load("v294.2")   # or "develop291"; default = registry `default:`
ref.verify()                            # assert every required artifact exists
ref.blast_chain_db, ref.hhsearch_db, ref.classification_lookup, ref.domain_definitions_csv
```

- `BlastRunner` / `HHsearchRunner` / `WeeklyBatch` / `PartitionRunner` resolve their
  paths from the registry per `reference_version`, so the whole pipeline stays on one
  ECOD version. The hardcoded DB constants are last-resort fallbacks only.
- **Default version is `v294.2`** (registry `default:` and component defaults).
- `pyecod_mini` (>=2.2.0) accepts reference-CSV overrides; prod passes the version's
  CSVs so the partitioner uses the same ECOD version (not mini's bundled test_data).
- **Adding a release**: add a `versions:` entry to `references.yaml` (build its BLAST
  DBs, classification lookup, and mini CSVs first) — no code change. `mini_bundled:
  true` marks a version whose CSVs pyecod_mini already ships (so they may be null).
- Build the classification lookup with `scripts/build_classification_lookup.py`
  (prefers `bulk_files/<...>.domains.txt`).

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
HH-suite: /sw/apps/hh-suite/bin/hhsearch, /sw/apps/hh-suite/bin/hhblits
pyecod-mini: /home/rschaeff/.local/bin/pyecod-mini
mmseqs2: /sw/apps/mmseqs/bin/mmseqs
CD-HIT: /sw/apps/cdhit/cd-hit
```

### HHsearch Database (UniRef30)

```bash
UniRef30 Database: /home/rschaeff/search_libs/UniRef30_2023_02
  - Already extracted (261GB), accessible from all compute nodes via NFS
  - No staging required - direct access from all SLURM jobs
  - Contains: _hhm.ffdata (48GB), _a3m.ffdata (204GB), _cs219.ffdata (8.5GB)
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
│   └── all_chains.fasta     # Combined FASTA for clustering
├── clustering/              # Sequence clustering results (optional)
│   ├── mmseqs_70pct_cluster.tsv
│   └── mmseqs_70pct_rep_seq.fasta
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

### Resuming Large Batches

When resuming a batch with interrupted BLAST/HHsearch jobs, use the `scripts/resume_batch.py` helper script or manually filter chains:

```python
from pyecod_prod.batch.weekly_batch import WeeklyBatch

batch = WeeklyBatch(
    release_date="2025-09-05",
    pdb_status_dir="/usr2/pdb/data/status/20250905",
    base_path="/data/ecod/pdb_updates/batches",
    reference_version="develop291"
)

# Step 1: Process existing results
batch.process_blast_results()
batch.process_hhsearch_results()

# Step 2: Generate summaries for completed chains
batch.generate_summaries()

# Step 3: Identify chains still needing processing
blast_needed = [
    f"{chain_data['pdb_id']}_{chain_data['chain_id']}"
    for chain_data in batch.manifest.data['chains'].values()
    if chain_data['blast_status'] != 'complete' and chain_data['can_classify']
]

hhsearch_needed = [
    f"{chain_data['pdb_id']}_{chain_data['chain_id']}"
    for chain_data in batch.manifest.chains_needing_hhsearch()
    if chain_data['hhsearch_status'] != 'complete'
]

# Step 4: Submit jobs ONLY for chains that need them
if blast_needed:
    job_id = batch.blast_runner.submit_blast_jobs(
        batch_dir=str(batch.batch_path),
        fasta_dir=str(batch.dirs.fastas_dir),
        output_dir=str(batch.dirs.blast_dir),
        blast_type="both",
        partition="96GB",
        array_limit=500,
        chain_filter=blast_needed  # CRITICAL: Only submit needed chains
    )
    print(f"Submitted BLAST for {len(blast_needed)} chains: job {job_id}")

if hhsearch_needed:
    job_id = batch.hhsearch_runner.submit_hhsearch_jobs(
        batch_dir=str(batch.batch_path),
        fasta_dir=str(batch.dirs.fastas_dir),
        output_dir=str(batch.dirs.hhsearch_dir),
        partition="96GB",
        array_limit=500,
        chain_filter=hhsearch_needed  # CRITICAL: Only submit needed chains
    )
    print(f"Submitted HHsearch for {len(hhsearch_needed)} chains: job {job_id}")

# Step 5: After jobs complete, process results and run partitioning
# batch.process_blast_results()
# batch.process_hhsearch_results()
# batch.generate_summaries()
# batch.run_partitioning()
```

**Why chain filtering is critical**: Without filtering, SLURM jobs are created for ALL FASTA files in the directory, which may exceed the 1000-job array limit. Chain filtering ensures jobs are only submitted for chains that actually need processing.

**See also**: `scripts/resume_batch.py` for automated resume with interactive prompts.

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

**SLURM array limit exceeded (>1000 jobs)**: This occurs when resuming batches with many FASTA files but fewer chains needing processing. The `BlastRunner` and `HHsearchRunner` now support chain filtering via the `chain_filter` parameter. See "Resuming Large Batches" section below.

## File Paths Reference

### Key Source Files

- Main orchestrator: `src/pyecod_prod/batch/weekly_batch.py`
- Manifest manager: `src/pyecod_prod/batch/manifest.py`
- PDB parser: `src/pyecod_prod/parsers/pdb_status.py`
- Designed protein detector: `src/pyecod_prod/utils/designed_proteins.py`
- BLAST runner: `src/pyecod_prod/slurm/blast_runner.py`
- HHsearch runner: `src/pyecod_prod/slurm/hhsearch_runner.py`
- Summary generator: `src/pyecod_prod/core/summary_generator.py`
- Partition runner: `src/pyecod_prod/core/partition_runner.py` (integration with pyecod_mini)
- Clustering runner: `scripts/run_clustering.py` (standalone mmseqs2/CD-HIT clustering)
- Clustering loader: `scripts/load_clustering.py` (load clustering to database)
- ECOD status populator: `scripts/populate_ecod_status.py` (clustering-aware status propagation)
- API specification: `PYECOD_MINI_API_SPEC.md` (contract with pyecod_mini)

### Test Files

- Unit tests: `tests/unit/test_batch_manifest.py`
- Integration tests: `tests/integration/test_blast_workflow.py`, `test_hhsearch_workflow.py`
- Designed protein tests: `tests/test_designed_proteins.py`
- Production test: `scripts/run_small_test.py`
- Resume helper: `scripts/resume_batch.py` (interactive batch resumption)

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

### Small-Scale Test
Test results (15 chains from 2025-09-05 release):
```
✓ Peptide filtering: 28 filtered (1.6% of 1,705 chains)
✓ BLAST pipeline: 15/15 complete (100%)
✓ Coverage analysis: 8 chains low coverage (<90%)
✓ HHsearch pipeline: 8/8 complete (100%)
✓ Summary generation: 15/15 complete (100%)
✓ Partitioning: 15/15 complete (100%)
```

### Full-Week Test
Production run (1,677 chains from 2025-09-05 release):
```
✓ BLAST processing: 1,632/1,632 classifiable chains (100%)
✓ HHsearch processing: 354/410 chains needed (86%, 56 failures)
✓ Summary generation: 1,632 domain summary XMLs
✓ Partitioning: 1,485+/1,632 chains (91%+)
✓ Runtime: ~4.5 hours for full workflow
```

**Key learnings**:
- Chain filtering essential for large batches (prevents SLURM array limit errors)
- Partitioning is CPU-intensive (~1-2 chains/sec on average, slower for complex proteins)
- Some chains fail partitioning due to parsing errors (logged and marked in manifest)
- Workflow is fully resumable from any step via manifest

All 9 workflow steps validated and production-ready.

---

## Integration with pyecod_mini

### Overview

pyecod_prod generates domain evidence (BLAST + HHsearch), then calls pyecod_mini for domain partitioning.

**Integration Point**: Step 8 of the 9-step workflow via `PartitionRunner` class.

### Installation

```bash
# Install pyecod_mini as dependency
pip install pyecod-mini>=2.0.0,<3.0.0  # Use latest v2.x (includes bug fixes)

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
# pyproject.toml dependencies
pyecod-mini>=2.0.0,<3.0.0  # Compatible with API spec v2.x
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
# <version algorithm="2.0.2" git_commit="..." timestamp="..."/>
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

### Designed Protein Filter (January 2026)

**Purpose**: Detect and filter computationally designed/synthetic proteins from classification pipeline, as ECOD focuses on naturally evolved proteins.

**Rationale**: Designed proteins (de novo designs, miniproteins, Rosetta/RFdiffusion outputs) have artificial folds that don't fit the evolutionary classification model. They should be identified early and excluded from classification.

**Detection Markers** (scoring system):

| Marker | Score | Example |
|--------|-------|---------|
| Source organism: "synthetic construct" | +3 | Entity source in mmCIF |
| Keyword: "DE NOVO PROTEIN" | +3 | PDB keywords field |
| Title: "de novo" | +2 | "De novo designed protein..." |
| Title: design method (Rosetta, RFdiffusion, etc.) | +2 | "Rosetta designed scaffold" |
| Title: "miniprotein", "minibinder" | +2 | Baker lab designs |
| Title: "designed" (alone) | +1 | May need manual review |

**Confidence Levels**:
- **HIGH** (score ≥3): Almost certainly designed → auto-exclude
- **MEDIUM** (score 1-2): Likely designed → may need review
- **NONE** (score 0): Not detected as designed → classify normally

**Implementation**:
- Module: `src/pyecod_prod/utils/designed_proteins.py`
- Integration: `PDBStatusParser` checks during chain extraction
- Configurable: Can disable or adjust confidence threshold

**Usage**:

```python
from pyecod_prod.utils.designed_proteins import (
    DesignedProteinDetector,
    is_designed_protein,
    get_designed_protein_info,
)

# Quick check
if is_designed_protein("9hnh"):
    print("This is a designed protein")

# Detailed info
result = get_designed_protein_info("9r0t")
print(f"Score: {result.score}, Confidence: {result.confidence}")
print(f"Reasons: {result.reasons}")
# Output: Score: 9, Confidence: HIGH
# Reasons: ['synthetic_construct_organism', 'de_novo_keyword', 'de_novo_title']

# Batch filtering
detector = DesignedProteinDetector()
natural, designed = detector.filter_designed(pdb_ids)
```

**Integration with PDBStatusParser**:

```python
from pyecod_prod.parsers.pdb_status import PDBStatusParser

# Default: filter high-confidence designed proteins
parser = PDBStatusParser(
    filter_designed_proteins=True,
    designed_protein_confidence="high",  # "high", "medium", or "none"
)

result = parser.process_weekly_release("/usr2/pdb/data/status/20260102")
print(f"Designed proteins filtered: {len(result['designed'])} chains")
```

**CLI Options**:

```bash
# Disable filtering
python -m pyecod_prod.parsers.pdb_status /path/to/status --no-filter-designed

# Also filter medium-confidence
python -m pyecod_prod.parsers.pdb_status /path/to/status --designed-confidence medium
```

**Validation**:

```bash
# Run tests
pytest tests/test_designed_proteins.py -v

# Test on known designed protein
python -c "
from pyecod_prod.utils.designed_proteins import get_designed_protein_info
result = get_designed_protein_info('9hnh')
print(f'{result.pdb_id}: {result.confidence.value}, score={result.score}')
print(f'Reasons: {result.reasons}')"
```

**Note**: The `_entity.src_method='syn'` field in mmCIF is NOT reliable for designed protein detection. It indicates "contains synthetic component" (which includes synthetic ligands, peptides, etc.) rather than "designed protein". The Q4 2025 batch showed only 109 overlap between 1,171 PDBs with `syn` tag and 127 PDBs with "synthetic construct" organism.

### Sequence Clustering

**Purpose**: Reduce redundancy in BLAST searches by clustering sequences at 70% identity and running BLAST only on cluster representatives.

**Why clustering matters**:
- Large PDB backfills can contain thousands of chains
- Many chains are nearly identical (same structure, multiple copies)
- Clustering reduces BLAST workload by 70-80% (1,632 → ~367 representatives)
- Representatives inherit ECOD status to cluster members via database propagation

**Architecture**: Clustering is **decoupled from BLAST workflow**
- Clustering runs independently on FASTA files (O(n²) complexity)
- Results loaded to database before BLAST submission
- BLAST workflow queries database to select only representatives
- Avoids bottlenecks for large-scale backfills

#### Clustering Methods

**mmseqs2** (Recommended for large datasets):
- Path: `/sw/apps/mmseqs/bin/mmseqs`
- Fast cascaded clustering algorithm
- Handles millions of sequences efficiently
- Output: TSV format (representative_id → member_id)
- Test results: 1,632 sequences → 367 clusters in ~3 seconds

**CD-HIT** (Traditional method):
- Path: `/sw/apps/cdhit/cd-hit`
- Well-established in bioinformatics
- Better for small-medium datasets (<10K sequences)
- Output: .clstr format
- More memory intensive for large datasets

#### Usage

**Step 1: Run clustering** (standalone, before BLAST):

```bash
# With mmseqs2 (recommended)
python scripts/run_clustering.py \
    /data/ecod/pdb_updates/batches/ecod_weekly_20250905/fastas/all_chains.fasta \
    /data/ecod/pdb_updates/batches/ecod_weekly_20250905/clustering/mmseqs_70pct \
    --method mmseqs2 \
    --threshold 0.70 \
    --threads 16

# With CD-HIT (traditional)
python scripts/run_clustering.py \
    all_chains.fasta \
    clustering/cdhit_70pct \
    --method cd-hit \
    --threshold 0.70 \
    --threads 8

# Submit to SLURM (for very large datasets)
python scripts/run_clustering.py \
    all_chains.fasta \
    clustering/mmseqs_70pct \
    --method mmseqs2 \
    --submit \
    --partition 96GB \
    --threads 32
```

**Step 2: Load clustering to database**:

```bash
# Load mmseqs2 results
python scripts/load_clustering.py \
    --cluster-file clustering/mmseqs_70pct_cluster.tsv \
    --release-date 2025-09-05 \
    --threshold 0.70 \
    --method mmseqs2

# Load CD-HIT results
python scripts/load_clustering.py \
    --cluster-file clustering/cdhit_70pct.fasta.clstr \
    --release-date 2025-09-05 \
    --threshold 0.70 \
    --method cd-hit
```

**Step 3: BLAST workflow automatically uses representatives**:

The BLAST workflow queries `pdb_update.chain_status` for chains where:
- `is_representative = TRUE` (cluster representatives)
- `ecod_status = 'not_in_ecod'` (needs classification)

After BLAST completes, ECOD status propagates from representatives to cluster members via `scripts/populate_ecod_status.py`.

#### Database Schema

Clustering data stored in `pdb_update` schema:

```sql
-- Clustering metadata
CREATE TABLE pdb_update.clustering_run (
    release_date date PRIMARY KEY,
    threshold float NOT NULL,
    method text NOT NULL,  -- 'mmseqs2' or 'cd-hit'
    total_sequences integer,
    total_clusters integer,
    run_date timestamp DEFAULT now()
);

-- Chain-level clustering assignments
ALTER TABLE pdb_update.chain_status
ADD COLUMN is_representative boolean DEFAULT TRUE,
ADD COLUMN representative_pdb_id text,
ADD COLUMN representative_chain_id text,
ADD COLUMN cluster_size integer;
```

**Propagation logic** (in `populate_ecod_status.py`):
1. Query ecod_commons for representatives → mark as `in_current_ecod`
2. Propagate ECOD status to cluster members via `representative_pdb_id/chain_id`

#### Performance Comparison

Test dataset: 1,632 chains from 2025-09-05 release

| Method   | Runtime | Representatives | Compression | Memory |
|----------|---------|-----------------|-------------|--------|
| mmseqs2  | ~3s     | 367 (22%)      | 77.5%       | Low    |
| CD-HIT   | ~8s     | 357 (22%)      | 78.1%       | Medium |

**Key differences**:
- mmseqs2 slightly more conservative (10 extra clusters)
- Both achieve ~77-78% compression
- mmseqs2 scales better for 10K+ sequences

#### Output Files

```
clustering/
├── mmseqs_70pct_cluster.tsv      # TSV: rep_id → member_id
├── mmseqs_70pct_rep_seq.fasta    # Representative sequences only
├── mmseqs_70pct_all_seqs.fasta   # All sequences (sorted by cluster)
└── mmseqs_70pct_tmp/             # Temporary files (auto-cleaned)
```

**TSV format** (mmseqs2):
```
9ay5_A	9ay5_A
9ay5_A	9ay5_B
9ay5_A	9ay5_C
9ay5_G	9ay5_G
9ay5_G	9ay5_H
```

#### Scripts

- **Clustering**: `scripts/run_clustering.py` - Standalone clustering with mmseqs2/CD-HIT
- **Database loading**: `scripts/load_clustering.py` - Parse and load clustering to `pdb_update`
- **Status propagation**: `scripts/populate_ecod_status.py` - Propagate ECOD status from reps to members

#### Validation

```bash
# Check clustering efficiency
psql -d ecod_protein -c "
SELECT
    release_date,
    method,
    total_sequences,
    total_clusters,
    ROUND(100.0 * total_clusters / total_sequences, 1) as pct_representatives
FROM pdb_update.clustering_run
ORDER BY release_date DESC;
"

# Verify representative assignments
psql -d ecod_protein -c "
SELECT
    COUNT(*) FILTER (WHERE is_representative) as representatives,
    COUNT(*) FILTER (WHERE NOT is_representative) as members
FROM pdb_update.chain_status
WHERE release_date = '2025-09-05';
"

# Check ECOD status propagation
psql -d ecod_protein -c "
SELECT
    ecod_status,
    COUNT(*) FILTER (WHERE is_representative) as reps,
    COUNT(*) FILTER (WHERE NOT is_representative) as members
FROM pdb_update.chain_status
WHERE release_date = '2025-09-05'
GROUP BY ecod_status;
"
```

---

### Self-Exclusion / Non-Circular Rep Validation (June 2026)

**Purpose**: Validate **existing** ECOD representative domains with the current
algorithm without the query trivially self-matching its own reference entry
(circularity). Used for the v294 F-group reconciliation (the 456 "movers") and,
eventually, a full self-consistency audit.

**Requires** `pyecod_mini >= 2.1.0` (adds the exclusion API).

**How it works**: evidence is masked before partitioning so a rep is classified
from *independent* evidence only. Masking is opt-in; default behavior is unchanged.

**Exclusion options** (forwarded by `PartitionRunner.partition()`):
- `exclude_self=True` — drop hits to the query's own structure (same PDB id)
- `exclude_domain_ids=[...]` — drop specific reference ECOD domain ids
- `exclude_fgroups=[...]` / `exclude_tgroups=[...]` — drop by classification

```python
from pyecod_prod.core.partition_runner import PartitionRunner

runner = PartitionRunner()
result = runner.partition(
    summary_xml="summaries/1gcy_A.summary.xml",
    output_dir="partitions/",
    exclude_self=True,                       # removes the e1gcyA2 self-hit
    exclude_domain_ids=["e1gcyA1", "e1gcyA2"],  # optional explicit F-group list
)
```

**Classification on summaries** (enables F-group/T-group exclusion):
`SummaryGenerator` emits `t_group/h_group/x_group/f_group` on each `<hit>` when a
classification lookup is loaded. Build the lookup once per ECOD version:

```bash
python scripts/build_classification_lookup.py \
    /data/ecod/database_versions/v291/ecod.develop291.xml \
    /data/ecod/database_versions/v291/domain_classification_lookup.tsv
```

```python
from pyecod_prod.utils.classification_lookup import load_classification_lookup_for_version
clf = load_classification_lookup_for_version("develop291")
generator = SummaryGenerator(reference_version="develop291", classification_lookup=clf)
```

**IMPORTANT — legacy ECOD XML naming**: in the old XML the element named
`f_group` is actually the **T-group** and `pf_group` (Pfam group) is the real
**F-group**. `build_classification_lookup.py` maps these to their true levels
(x_id→x_group, h_id→h_group, f_group/f_id→t_group, pf_group/pf_id→f_group).

**Optional pre-masked summaries**: `SummaryGenerator.generate_summary(...,
exclude_self=True, exclude_domain_ids={...})` writes a summary with self/listed
hits already removed, plus a `<masked_evidence count=.../>` metadata element.

**Regression driver** (the 456 movers): `scripts/validate_reps_self_exclusion.py`
takes a TSV of reps (`domain_id, pdb_id, chain_id, old_f, commons_f, summary_xml
[, exclude_domains]`), runs each with `exclude_self`, maps each output domain's
`reference_ecod_domain_id` to an F-group via the classification lookup, and reports
`supported` / `different` / `unclassified` per rep.

```bash
python scripts/validate_reps_self_exclusion.py movers.tsv \
    --output movers_validation.tsv --reference develop291
```

**Output evidence of non-circularity**: partition.xml `<metadata>` carries
`exclusion_policy` and `evidence_items_masked`; a `<domain>` with
`top_evidence_masked="true"` had masked (e.g. self) evidence over its range.

## Historical Backfill (2023-2025)

### Overview

A 2-year backfill project to process 103 weekly PDB releases (2023-10-27 to 2025-10-10), covering 197,777 chains.

**Location**: `/data/ecod/pdb_updates/backfill_2023_2025/blast/`

**Status** (2025-10-23):
- ✅ BLAST complete (9,656 representatives)
- 🔄 HHsearch in progress (4,297 chains, ETA: 4-8 hours)
- 🔄 ecod_curation load 95% complete (8,931/9,365 proteins)

**See**: [docs/BACKFILL_STATUS_REPORT.md](docs/BACKFILL_STATUS_REPORT.md) for complete status.

### Key Statistics

- **Total chains**: 197,777
- **Classifiable**: 193,119 (97.6%)
- **In ECOD already**: 51,146 (26.5%)
- **Need classification**: 141,973 (73.5%)
- **After 70% clustering**: 16,574 representatives (91.4% reduction)
- **After ECOD filtering**: 9,656 BLAST targets (95.0% total reduction)

### Workflow

1. **Metadata backfill** (Phase 4a): Load 103 releases to `pdb_update.chain_status`
2. **Sequence extraction** (Phase 4b): Extract 193,119 sequences to database
3. **Global clustering** (Phase 4c): mmseqs2 at 70% identity → 16,574 representatives
4. **Clustering load** (Phase 4d): Load to `pdb_update.clustering_run`
5. **ECOD status lookup** (Phase 4e): Mark 51,146 chains already in ECOD
6. **BLAST targets** (Phase 4f): 9,656 representatives not in ECOD
7. **BLAST workflow** (Phase 4g): ✅ Complete (9,656/9,656 chain + domain)
8. **HHsearch workflow** (Phase 4h): 🔄 In progress (4,297 chains <90% BLAST coverage)
9. **ecod_curation load** (Phase 4i): 🔄 95% complete (for examination)
10. **Structure preprocessing** (Phase 4j): Pending (9,365 chain PDB files)
11. **Evidence propagation** (Phase 4k): Pending (copy to 176,545 members)

### HHsearch Workflow

**Why HHsearch?**: ~44.5% of representatives (4,297/9,656) have <90% BLAST coverage and need more sensitive profile-to-profile search.

**Two-step process**:
1. **hhblits**: Build query profile against UniRef30 (10-30 min/chain)
2. **hhsearch**: Search profile against ECOD HMMs (5-10 min/chain)

**Current run** (2025-10-23):
- Jobs: 318110-318144 (5 batches)
- Status: 30 running, 4,267 pending
- UniRef30: Direct access to `/home/rschaeff/search_libs/UniRef30_2023_02` (no staging)
- SLURM fix: Array indices 1-N per batch with offset (avoids MaxArraySize=1000 limit)

**Scripts**:
- `/data/ecod/pdb_updates/backfill_2023_2025/blast/run_hhsearch_twostep.py`
- `/data/ecod/pdb_updates/backfill_2023_2025/blast/submit_hhsearch_batch[2-5].sh`
- `/data/ecod/pdb_updates/backfill_2023_2025/blast/submit_hhsearch_fixed.sh` (wrapper)

**See**: [docs/HHSEARCH_WORKFLOW.md](docs/HHSEARCH_WORKFLOW.md) for complete documentation.

### Monitor Progress

```bash
# Check HHsearch jobs
squeue -u $USER --name=hhsearch*

# Count outputs
cd /data/ecod/pdb_updates/backfill_2023_2025/blast
ls profiles/*.a3m | wc -l   # hhblits profiles
ls hhsearch/*.hhr | wc -l   # HHsearch results

# Check database load
export ECOD_DB_PASSWORD='ecod#badmin'
psql -h dione -p 45000 -U ecod -d ecod_protein -c \
  "SELECT COUNT(*) FROM ecod_curation.protein;"

# Check for failures
sacct -u $USER --name=hhsearch* --state=FAILED
```

### Next Steps

After HHsearch completes:
1. Process HHR files and regenerate summaries (BLAST + HHsearch combined)
2. Re-run partitioning for chains with updated evidence
3. Examine results in ecod_curation schema
4. Propagate evidence to cluster members (176,545 chains)
5. Load final results to `pdb_update` schema

---

## References

- [PYECOD_MINI_API_SPEC.md](PYECOD_MINI_API_SPEC.md) - Formal API contract with pyecod_mini
- [docs/VERSION_TRACKING.md](docs/VERSION_TRACKING.md) - Implementation roadmap for versioning
- [docs/BACKFILL_STATUS_REPORT.md](docs/BACKFILL_STATUS_REPORT.md) - 2-year backfill status
- [docs/HHSEARCH_WORKFLOW.md](docs/HHSEARCH_WORKFLOW.md) - HHsearch workflow documentation
- [docs/CLUSTERING_INTEGRATION_STATUS.md](docs/CLUSTERING_INTEGRATION_STATUS.md) - Clustering workflow
- [docs/sessions/SESSION_SUMMARY_20251019.md](docs/sessions/SESSION_SUMMARY_20251019.md) - Recent feature implementation
- pyecod_mini repository: `/home/rschaeff/dev/pyecod_mini/`
- ECOD database: https://prodata.swmed.edu/ecod/
