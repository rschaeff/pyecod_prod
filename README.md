# pyECOD Production Framework

Production pipeline for generating domain summary files that feed the pyECOD classification algorithm.

## Overview

This framework processes weekly PDB updates and generates domain summary XML files by:

1. **BLAST Search**: Running chain and domain BLAST against ECOD v291 databases
2. **HHsearch** (conditional): For proteins with low BLAST coverage (<90%)
3. **Summary Generation**: Combining evidence into domain_summary.xml
4. **Partitioning**: Running pyecod-mini to generate domain partitions

## Architecture

- **File-First**: YAML manifests are primary truth, database is optional index
- **Two-Pass**: BLAST-only first (fast), HHsearch for low coverage (slow)
- **SLURM-Integrated**: Designed for HPC cluster execution
- **Minimal Database**: 4 tables vs 80+ in legacy system

## Components

### Core

- `PDBStatusParser`: Parse weekly PDB updates from `/usr2/pdb/data/status/`
- `BatchManifest`: Manage batch state via YAML files
- `BlastRunner`: Submit and monitor BLAST jobs via SLURM
- `HHsearchRunner`: Submit and monitor HHsearch jobs via SLURM
- `SummaryGenerator`: Combine BLAST/HHsearch results into domain_summary.xml
- `PartitionRunner`: Wrapper for pyecod-mini partitioning

### Database Schema

Optional `pdb_update` schema in PostgreSQL for tracking and coordination:

- `weekly_release`: Track PDB weekly releases
- `chain_status`: Track each protein chain through pipeline
- `repair_batch`: Track repair/reprocessing batches
- `repair_chain`: Track chains in repair batches

## Reference Databases (v291)

```yaml
blast_databases:
  chain: /data/ecod/database_versions/v291/chainwise100.develop291
  domain: /data/ecod/database_versions/v291/ecod100.develop291

hhsearch:
  hhm_database: /data/ecod/database_versions/v291/ecod_v291_hhm
  uniref_database: ~/search_libs/UniRef30_2023_02

reference_files:
  xml: /data/ecod/database_versions/v291/ecod.develop291.xml
  range_cache: /data/ecod/database_versions/v291/ecod.develop291.range_cache.txt
```

## Installation

```bash
cd pyecod_prod
pip install -e ".[dev]"
```

## Quick Start

### Process Weekly Update

```bash
# Process PDB weekly update from 2025-10-10
pyecod-weekly 20251010

# Check status
pyecod-status --batch ecod_weekly_20251010

# Resume if interrupted
pyecod-weekly 20251010 --resume
```

### Repair Existing Proteins

```bash
# Reprocess specific proteins (e.g., after algorithm update)
pyecod-repair --chains 8abc_A 8xyz_B --reason "algorithm_update"
```

## Directory Structure

```
/data/ecod/pdb_updates/batches/
└── ecod_weekly_20251010/
    ├── batch_manifest.yaml    # Primary state file
    ├── pdb_entries.txt        # Copy of added.pdb
    ├── fastas/                # Input sequences
    ├── blast/                 # BLAST results
    ├── hhsearch/              # HHsearch results (subset)
    ├── summaries/             # Combined evidence
    ├── partitions/            # Final domain partitions
    └── slurm_logs/            # Job logs
```

## Implementation Status

### Phase 1: Core Components ✅
- [x] Database schema
- [x] PDBStatusParser
- [x] BatchManifest class
- [x] BlastRunner (SLURM submission)
- [x] Basic tests

### Phase 2: BLAST Pipeline (In Progress)
- [ ] Complete BlastRunner
- [ ] SummaryGenerator (BLAST-only mode)
- [ ] PartitionRunner
- [ ] WeeklyBatch orchestrator
- [ ] End-to-end BLAST-only workflow

### Phase 3: HHsearch Enhancement (Planned)
- [ ] HHsearchRunner
- [ ] Enhanced SummaryGenerator
- [ ] Two-pass workflow

### Phase 4: Repair & Polish (Planned)
- [ ] RepairBatch implementation
- [ ] Database sync utilities
- [ ] Monitoring/logging

## Development

```bash
# Run tests
pytest tests/

# Format code
black src/ tests/

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

## Related Projects

- **pyecod_mini**: Domain partitioning algorithm (consumes domain summaries)
- **pyecod**: Legacy ECOD pipeline (being replaced)

## License

Internal ECOD project
