# ecod_curation Integration Status

**Date**: 2025-10-20
**Status**: Phase 1 Complete - Basic Integration Implemented

## What Was Implemented

### 1. Database Loader Module ✅

**File**: `src/pyecod_prod/database/curation_loader.py`

Core functions:
- `load_partition_to_curation()` - Load protein partition results to ecod_curation schema
- `classify_partition_quality()` - Classify partition as 'good', 'low_coverage', 'fragmentary', 'failed'
- `can_curate()` - Filter out peptides and nucleic acids
- `should_queue_for_curation()` - Heuristics for adding to manual curation queue
- `calculate_queue_priority()` - Priority scoring (1-10) for curation queue

**Features**:
- Inserts protein, domain_assignment, and domain_evidence records
- Automatically adds low-confidence cases to curation queue
- Handles NULL f-groups for incomplete classifications
- MD5 sequence hashing for duplicate detection

### 2. Integration Script ✅

**File**: `scripts/load_to_curation.py`

Capabilities:
- Load single partition XML file
- Load entire batch directory
- Dry-run mode for testing
- Error handling and progress reporting

Usage:
```bash
# Load entire batch
python scripts/load_to_curation.py --batch-path /data/ecod/test_batches/ecod_weekly_20250905

# Load single partition
python scripts/load_to_curation.py --pdb 8abc --chain A --partition-xml partitions/8abc_A.partition.xml

# Dry run (no database writes)
python scripts/load_to_curation.py --batch-path /data/ecod/test_batches/ecod_weekly_20250905 --dry-run
```

### 3. Test Suite ✅

**File**: `tests/test_curation_loader.py`

Tests:
- Unit tests for all helper functions
- Integration test with full database round-trip
- Quality classification logic
- Queue prioritization logic
- Peptide/nucleic acid filtering

Run tests:
```bash
# Unit tests (no database required)
pytest tests/test_curation_loader.py -k "not integration"

# Integration test (requires database)
pytest tests/test_curation_loader.py::test_load_partition_to_curation_integration

# Or run directly
python tests/test_curation_loader.py
```

### 4. Database Schema ✅

**Location**: dione:45000/ecod_protein
**Schema**: ecod_curation (deployed 2025-01-20)

Tables:
- `protein` - Proteins awaiting curation
- `domain_assignment` - Domain predictions and curator modifications
- `domain_evidence` - BLAST/HHsearch evidence
- `non_domain_region` - Regions marked as junk
- `curation_queue` - Proteins prioritized for review
- `curation_session` - Curator session tracking
- `curation_decision_log` - Decision audit log

Views:
- `queue_view` - Curation queue with protein details
- `ready_for_accession` - Proteins ready for ecod_commons
- `flagged_proteins` - Proteins needing expert review
- `curation_stats` - Overall statistics

## What's Working

### ✅ Basic Pipeline Integration

You can now:

1. Run test batch with partitioning:
   ```bash
   python scripts/run_small_test.py  # 15 chains
   # OR
   python scripts/run_medium_test.py  # 100 chains
   ```

2. Load partition results to ecod_curation:
   ```bash
   python scripts/load_to_curation.py --batch-path /data/ecod/test_batches/ecod_weekly_20250905
   ```

3. Query the curation queue:
   ```sql
   -- Connect to database
   PGPASSWORD='ecod#badmin' psql -h dione -p 45000 -U ecod -d ecod_protein

   -- View curation queue
   SELECT * FROM ecod_curation.queue_view ORDER BY priority DESC;

   -- Check proteins ready for accession
   SELECT * FROM ecod_curation.ready_for_accession;

   -- View statistics
   SELECT * FROM ecod_curation.curation_stats;
   ```

## What's NOT Yet Implemented

### ⚠️ Phase 2: Full Classification & Evidence

**Issue**: Current pyecod_mini partition result doesn't include:
- T/H/X/F group assignments (only ecod_domain_id)
- Detailed evidence with query/hit ranges
- Classification confidence levels

**Needed**:

1. **Enhance partition XML output** (pyecod_mini side):
   ```xml
   <domain id="8abc_A_001"
           range="10-150"
           ecod_domain="e8s9s7"
           t_group="1.1.13"
           h_group="1.1"
           x_group="1.1.13"
           f_group="1.1.13.29"
           best_match_uid="3066545"
           classification_level="f_group_specific"
           confidence="0.92">
     <evidence type="blast_domain"
               hit_uid="3066545"
               hit_pdb="8s9s"
               hit_chain="7"
               evalue="1.5e-45"
               score="189.2"
               identity="0.85"
               query_range="10-150"
               hit_range="5-145"
               ref_t_group="1.1.13"
               ref_f_group="1.1.13.29"/>
   </domain>
   ```

2. **Alternative: Database lookup** (pyecod_prod side):
   ```python
   # In load_to_curation.py, add lookup functions:
   def lookup_classification(ecod_domain_id: str) -> Dict:
       """Query ecod_rep to get t/h/x/f groups for a domain."""
       # SELECT t_group, h_group, x_group, f_group
       # FROM ecod_rep.cluster
       # WHERE representative_domain_id = ecod_domain_id
       pass

   def parse_evidence_from_summary(summary_xml: str) -> List[Dict]:
       """Parse summary.xml to extract evidence details."""
       pass
   ```

3. **Update load_to_curation.py**:
   - Add classification lookup from ecod_rep
   - Parse summary.xml for evidence
   - Associate evidence with partitioned domains

### ⚠️ Phase 3: Automated Batch Integration

**File to modify**: `src/pyecod_prod/batch/weekly_batch.py`

Add curation loading to `run_partitioning()` method:

```python
def run_partitioning(self):
    """Run pyecod-mini partitioning on all summaries"""
    # ... existing partitioning code ...

    for chain_key, chain_data in self.manifest.data["chains"].items():
        # ... existing partition call ...

        if result.error_message:
            continue

        # NEW: Load to ecod_curation
        try:
            from pyecod_prod.database.curation_loader import load_partition_to_curation

            protein_id = load_partition_to_curation(
                pdb_id=pdb_id,
                chain_id=chain_id,
                release_date=self.release_date,
                sequence=chain_data["sequence"],  # Need to add sequence to chain_data
                partition_result=result,  # Need to convert to dict format
                processing_version=f'pyecod_prod_{self.batch_name}'
            )

            logger.info(f"Loaded {pdb_id}_{chain_id} to ecod_curation (protein_id={protein_id})")

        except Exception as e:
            logger.error(f"Failed to load {pdb_id}_{chain_id} to ecod_curation: {e}")
            # Continue processing - don't fail batch due to curation load error
```

**Challenge**: Need protein sequence in manifest. Currently not stored.

### ⚠️ Phase 4: Accession Script

**File to create**: `scripts/accession.py`

See `docs/ecod_curation_integration.md` for specification.

Functionality:
- Query `ecod_curation.ready_for_accession` view
- Validate all domains have f-groups
- Assign ECOD UIDs and domain IDs
- Create records in ecod_commons
- Mark as accessioned in ecod_curation

## Testing Plan

### Phase 1 Testing (Current)

✅ Unit tests pass
✅ Integration test with database works
✅ Can load single partition manually
✅ Can load batch directory manually

### Phase 2 Testing (Next)

- [ ] Verify t/h/x/f group lookup works
- [ ] Verify evidence parsing from summary.xml works
- [ ] Load test batch with full classification
- [ ] Verify evidence shows correctly in ecod_curation

### Phase 3 Testing (After Phase 2)

- [ ] Run full small test (15 chains) end-to-end
- [ ] Verify all chains load to ecod_curation automatically
- [ ] Check queue logic - appropriate proteins queued
- [ ] Check statistics view

### Phase 4 Testing (Final)

- [ ] Test accession script with small batch
- [ ] Verify ECOD UID assignment
- [ ] Verify ecod_commons records created correctly
- [ ] Verify ecod_curation marked as accessioned
- [ ] End-to-end test: partition → curate → accession

## Current Limitations

1. **No t/h/x/f groups**: Domains loaded without ECOD classification hierarchy
   - Consequence: Curators must assign f-groups manually for ALL domains
   - Workaround: OK for now - this is the curation workflow anyway
   - Future: Pre-populate when available from pipeline

2. **No detailed evidence**: Evidence table empty
   - Consequence: Curators don't see BLAST/HHsearch details
   - Workaround: Can view original summary.xml files
   - Future: Parse summary.xml and populate evidence table

3. **Manual batch loading**: Not integrated into weekly_batch.py
   - Consequence: Must run `load_to_curation.py` separately
   - Workaround: Run script after partitioning completes
   - Future: Auto-load during batch processing

4. **No sequence in partition result**: Must be provided separately
   - Consequence: load_to_curation.py parses from XML
   - Workaround: Works, but adds parsing overhead
   - Future: Include sequence in PartitionResult

## Next Steps

### Immediate (This Week)

1. Test with real data:
   ```bash
   # Run small test batch
   python scripts/run_small_test.py

   # Load to curation (once partitioning completes)
   python scripts/load_to_curation.py --batch-path /data/ecod/test_batches/ecod_weekly_20250905
   ```

2. Verify database records:
   ```sql
   SELECT COUNT(*) FROM ecod_curation.protein;
   SELECT * FROM ecod_curation.queue_view ORDER BY priority DESC LIMIT 10;
   SELECT * FROM ecod_curation.curation_stats;
   ```

3. Document any issues or edge cases

### Short Term (Next Sprint)

1. Implement classification lookup from ecod_rep
2. Implement evidence parsing from summary.xml
3. Update load_to_curation.py with full data

### Medium Term (Next Month)

1. Integrate into weekly_batch.py
2. Implement accession.py script
3. End-to-end testing with pyecod_vis

## Files Created

```
pyecod_prod/
├── src/pyecod_prod/database/
│   ├── curation_loader.py          # Core loading functions
│   └── __init__.py                 # Updated exports
├── scripts/
│   └── load_to_curation.py         # Batch loading script
├── tests/
│   └── test_curation_loader.py     # Test suite
└── docs/
    ├── ecod_curation_integration.md        # Original specification
    └── CURATION_INTEGRATION_STATUS.md      # This file
```

## Database Connection

All tools use this connection by default:
```python
{
    "host": "dione",
    "port": 45000,
    "database": "ecod_protein",
    "user": "ecod",
    "password": "ecod#badmin"
}
```

Can be overridden via `connection_params` argument if needed.

---

**Status**: Ready for initial testing with real partition data. Full classification and evidence integration coming in Phase 2.
