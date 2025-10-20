# Phase 1 Complete: Core Components

## Overview

Phase 1 of the pyECOD Production Framework has been successfully implemented. This phase established the foundational components for processing weekly PDB updates and generating domain summary files.

## Completed Components

### 1. Project Structure ✅

```
pyecod_prod/
├── src/pyecod_prod/
│   ├── __init__.py
│   ├── parsers/
│   │   ├── __init__.py
│   │   └── pdb_status.py        # PDB weekly update parser
│   ├── batch/
│   │   ├── __init__.py
│   │   └── manifest.py           # YAML manifest management
│   ├── slurm/
│   │   ├── __init__.py
│   │   └── blast_runner.py       # SLURM BLAST job submission
│   ├── utils/
│   │   ├── __init__.py
│   │   └── directories.py        # Directory structure helpers
│   └── core/
│       └── __init__.py
├── tests/
│   ├── unit/
│   │   └── test_batch_manifest.py
│   └── integration/
├── sql/
│   └── 01_create_pdb_update_schema.sql
├── docs/
├── scripts/
├── pyproject.toml
└── README.md
```

### 2. Database Schema ✅

**File**: `sql/01_create_pdb_update_schema.sql`

Created minimal `pdb_update` schema with 4 tables:

- `weekly_release`: Track PDB weekly releases
- `chain_status`: Track each chain through pipeline
- `repair_batch`: Track repair/reprocessing batches
- `repair_chain`: Track chains in repair batches

**Key Features**:
- Optional database (manifest files are primary truth)
- Helper views for common queries
- Automatic timestamp triggers
- Comprehensive indexes for performance

**To Deploy**:
```bash
psql -U ecod -d update_protein -f sql/01_create_pdb_update_schema.sql
```

### 3. PDBStatusParser ✅

**File**: `src/pyecod_prod/parsers/pdb_status.py`

**Purpose**: Parse weekly PDB status files and extract protein chains.

**Features**:
- Read `added.pdb` and `modified.pdb` from `/usr2/pdb/data/status/`
- Parse mmCIF files using Biopython
- Extract amino acid sequences from chains
- Filter peptides (<20 residues)
- Identify non-classifiable chains

**Usage**:
```python
from pyecod_prod import PDBStatusParser

parser = PDBStatusParser()
result = parser.process_weekly_release("/usr2/pdb/data/status/20251010")

print(f"Classifiable chains: {len(result['classifiable'])}")
print(f"Peptides: {len(result['peptides'])}")
```

### 4. BatchManifest ✅

**File**: `src/pyecod_prod/batch/manifest.py`

**Purpose**: Manage batch state via YAML files (file-first architecture).

**Features**:
- Initialize batch with metadata
- Add chains with status tracking
- Update chain status through pipeline
- Track SLURM jobs
- Get chains needing HHsearch (coverage < 90%)
- Query chains by status
- Generate batch summaries

**Usage**:
```python
from pyecod_prod import BatchManifest

manifest = BatchManifest("/data/ecod/pdb_updates/batches/ecod_weekly_20251010")

manifest.initialize_batch(
    batch_name="ecod_weekly_20251010",
    batch_type="weekly",
    release_date="2025-10-10",
    pdb_status_path="/usr2/pdb/data/status/20251010",
    reference_version="develop291",
)

# Add chain
manifest.add_chain("8abc", "A", sequence="MKTAY...", sequence_length=250)

# Mark BLAST complete
manifest.mark_blast_complete("8abc", "A", coverage=0.95)

# Save manifest
manifest.save()

# Print summary
manifest.print_summary()
```

### 5. BlastRunner ✅

**File**: `src/pyecod_prod/slurm/blast_runner.py`

**Purpose**: Submit and monitor BLAST jobs via SLURM.

**Features**:
- Generate SLURM job array scripts
- Submit jobs with array limits (max concurrent)
- Monitor job status
- Parse query coverage from BLAST XML
- Support both chain and domain BLAST
- Automatic retry/recovery

**Database Paths** (v291):
- Chain: `/data/ecod/database_versions/v291/chainwise100.develop291`
- Domain: `/data/ecod/database_versions/v291/ecod100.develop291`

**Usage**:
```python
from pyecod_prod import BlastRunner

runner = BlastRunner()

# Submit BLAST jobs
job_id = runner.submit_blast_jobs(
    batch_dir="/data/ecod/pdb_updates/batches/ecod_weekly_20251010",
    fasta_dir="fastas",
    output_dir="blast",
    blast_type="both",  # chain + domain
    partition="96GB",
    array_limit=500,  # Max 500 concurrent jobs
)

# Wait for completion
success = runner.wait_for_completion(job_id)

# Parse coverage
coverage = runner.parse_blast_coverage("blast/8abc_A.domain_blast.xml")
print(f"Coverage: {coverage:.1%}")
```

### 6. Directory Structure Utilities ✅

**File**: `src/pyecod_prod/utils/directories.py`

**Purpose**: Manage standardized batch directory structure.

**Features**:
- Create batch directory structure
- Get file paths for chains
- Generate relative paths for manifest
- Write FASTA files with proper formatting

**Standard Structure**:
```
batch_dir/
├── batch_manifest.yaml
├── pdb_entries.txt
├── fastas/           # Input sequences
├── blast/            # BLAST results
├── hhsearch/         # HHsearch results (subset)
├── summaries/        # Combined evidence
├── partitions/       # Final domain partitions
├── slurm_logs/       # Job logs
└── scripts/          # Generated SLURM scripts
```

**Usage**:
```python
from pyecod_prod.utils.directories import BatchDirectories, write_fasta

dirs = BatchDirectories("/data/ecod/pdb_updates/batches/ecod_weekly_20251010")
dirs.create_structure()

# Write FASTA
fasta_path = dirs.get_fasta_path("8abc", "A")
write_fasta(str(fasta_path), "8abc_A", "MKTAYIAKQRQ...")

# Get all file paths
file_paths = dirs.get_file_paths_dict("8abc", "A", relative=True)
```

### 7. Unit Tests ✅

**File**: `tests/unit/test_batch_manifest.py`

**Coverage**:
- Manifest creation and initialization
- Adding chains (classifiable and peptides)
- Status updates (BLAST, HHsearch, partition)
- Save/load functionality
- Summary generation
- Query methods

**Run Tests**:
```bash
cd pyecod_prod
pytest tests/unit/test_batch_manifest.py -v
```

## Installation

```bash
cd /home/rschaeff/dev/pyecod_prod
pip install -e ".[dev]"
```

## Configuration

### Reference Databases (v291)

All components are pre-configured to use v291 databases:

```python
# BLAST databases
CHAIN_DB = "/data/ecod/database_versions/v291/chainwise100.develop291"
DOMAIN_DB = "/data/ecod/database_versions/v291/ecod100.develop291"

# PDB mirror
PDB_MIRROR = "/usr2/pdb/data/structures/all/mmCIF"

# PDB status
PDB_STATUS = "/usr2/pdb/data/status/{YYYYMMDD}"
```

## Next Steps: Phase 2

Phase 2 will implement the complete BLAST-only workflow:

1. **SummaryGenerator**: Combine BLAST results into domain_summary.xml
2. **PartitionRunner**: Wrapper for pyecod-mini partitioning
3. **WeeklyBatch**: Orchestrator for full workflow
4. **End-to-end testing**: Process a real PDB weekly update

**Estimated Time**: 1 week

## Dependencies

**Required**:
- Python 3.9+
- PyYAML >= 6.0
- BioPython >= 1.81
- psycopg2-binary >= 2.9 (if using database)

**SLURM Environment**:
- BLAST+ module
- SLURM job scheduler

## Documentation

- **Production Plan**: `/tmp/production_framework_plan.md`
- **Database Analysis**: `/tmp/database_version_analysis.md`
- **Original Framework Analysis**: `/tmp/original_framework_analysis.md`
- **HHM Library Generation**: `/tmp/hhm_library_generation_plan.md`

## Testing Checklist

- [x] PDBStatusParser parses weekly status files
- [x] PDBStatusParser extracts chains from mmCIF
- [x] PDBStatusParser filters peptides
- [x] BatchManifest creates and loads YAML
- [x] BatchManifest tracks chain status
- [x] BatchManifest identifies chains needing HHsearch
- [x] BlastRunner generates SLURM scripts
- [x] BlastRunner parses BLAST coverage
- [x] Directory utilities create structure
- [x] All unit tests pass

## Known Limitations

1. **No Integration Tests Yet**: Need end-to-end tests with real data
2. **Database Sync Not Implemented**: Manifest → database sync pending
3. **Error Recovery**: Basic error handling, needs enhancement
4. **Monitoring**: No dashboard or progress visualization yet

## Contributors

- ECOD Team
- Built with Claude Code

## License

Internal ECOD project
