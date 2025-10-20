# Production Workflows

This document describes the three main production workflows for the pyECOD framework:

1. **Update Weeks**: Process all PDB releases since last ECOD update (catch-up processing)
2. **Repair Batches**: Reprocess specific chains or weeks
3. **Database Integration**: Sync batch results to PostgreSQL for ECOD integration

---

## 1. Update Weeks Workflow (Catch-up Processing)

### Purpose
Process all PDB weekly updates from a start date to present. This is used when ECOD needs to catch up on multiple weeks of PDB releases.

### Script
`scripts/process_update_weeks.py`

### Usage

#### Dry run to see what would be processed:
```bash
python scripts/process_update_weeks.py \
    --start-date 2025-09-05 \
    --dry-run
```

#### Process all weeks from a start date (no SLURM submission):
```bash
python scripts/process_update_weeks.py \
    --start-date 2025-09-05 \
    --base-path /data/ecod/pdb_updates/batches
```

#### Process with SLURM job submission:
```bash
python scripts/process_update_weeks.py \
    --start-date 2025-09-05 \
    --submit
```

#### Limit number of batches (for testing):
```bash
python scripts/process_update_weeks.py \
    --start-date 2025-09-05 \
    --max-batches 3 \
    --submit
```

### How It Works

1. **Discover releases**: Scans `/usr2/pdb/data/status/` for directories between start_date and latest
2. **Validate releases**: Checks for non-empty `added.pdb` files
3. **Sequential processing**: Processes each week in order (oldest to newest)
4. **Resume capability**: Skips completed batches, resumes incomplete ones
5. **Error handling**: Continues to next week if one fails

### Features

- **Automatic discovery**: Finds all PDB weekly releases in date range
- **Skip empty weeks**: Ignores weeks with no new structures
- **Resume support**: Can restart from failures without reprocessing
- **Progress tracking**: Prints summary after each batch
- **Final report**: Shows success/failure counts and failed weeks

### Example Output

```
Finding PDB weekly releases...

Found 8 weekly releases to process:
  - 2025-09-05 (/usr2/pdb/data/status/20250905)
  - 2025-09-12 (/usr2/pdb/data/status/20250912)
  ...

Process 8 weekly releases? [y/N]: y

######################################################################
Batch 1/8
######################################################################

======================================================================
Processing weekly release: 2025-09-05
======================================================================
...
```

---

## 2. Repair Batches Workflow

### Purpose
Reprocess specific chains or weeks that need correction, reclassification, or failed in previous runs.

### Common Use Cases

1. **PDB modifications/obsoletes**: Reprocess chains affected by PDB updates
2. **Algorithm updates**: Reclassify chains with new pyecod-mini version
3. **Failed processing**: Retry chains that failed BLAST, HHsearch, or partitioning
4. **Hierarchy changes**: Reclassify after ECOD hierarchy updates
5. **Low quality results**: Reprocess chains with low partition coverage

### Script
`scripts/process_repair_batch.py`

### Usage

#### Reprocess specific weeks:
```bash
python scripts/process_repair_batch.py \
    --weeks 2025-09-05,2025-09-12 \
    --reason pdb_modifications \
    --batch-name ecod_repair_20251019_pdb_mods
```

#### Reprocess chains from file:
```bash
# Create file with format: pdb_id chain_id source_week
cat > failed_chains.txt <<EOF
8s72 A 2025-09-05
8yl2 B 2025-09-05
EOF

python scripts/process_repair_batch.py \
    --chains-file failed_chains.txt \
    --reason error_fix
```

#### Find and reprocess all low-quality chains:
```bash
python scripts/process_repair_batch.py \
    --low-quality \
    --reason algorithm_update
```

#### Reprocess with different options:
```bash
# Rerun just partitioning (use existing BLAST/HHsearch)
python scripts/process_repair_batch.py \
    --weeks 2025-09-05 \
    --reason algorithm_update \
    --rerun-partition

# Rerun everything from scratch
python scripts/process_repair_batch.py \
    --weeks 2025-09-05 \
    --reason hierarchy_update \
    --rerun-blast \
    --rerun-hhsearch \
    --rerun-partition
```

### Repair Batch Reasons

- `pdb_modifications`: PDB modified/obsoleted structures
- `algorithm_update`: New pyecod-mini or improved algorithms
- `error_fix`: Fix failed processing from previous runs
- `hierarchy_update`: ECOD hierarchy changed (X-group splits, H-group merges)
- `user_request`: Manual reprocessing request

### Features

- **Flexible input**: Accept weeks, chain lists, or quality criteria
- **Selective reprocessing**: Choose which steps to rerun (BLAST/HHsearch/partition)
- **Automatic discovery**: Find low-quality chains across all batches
- **Source tracking**: Maintains link to original weekly batch
- **Dry run mode**: Preview what would be reprocessed

### Output

Repair batches create a manifest similar to weekly batches but with additional fields:

```yaml
batch_name: ecod_repair_20251019_pdb_mods
batch_type: repair
created: 2025-10-19T22:00:00
reference_version: develop291
source_weeks:
  - 2025-09-05
  - 2025-09-12
rerun_blast: false
rerun_hhsearch: false
rerun_partition: true
chains:
  8s72_A:
    pdb_id: "8s72"
    chain_id: A
    source_week: "2025-09-05"
    repair_status: pending
    ...
```

---

## 3. Database Integration Workflow

### Purpose
Sync completed batch results to PostgreSQL database for central tracking, indexing, and ECOD integration preparation.

### Database Schema
Location: `sql/01_create_pdb_update_schema.sql`

**Tables:**
- `pdb_update.weekly_release`: Batch metadata and status
- `pdb_update.chain_status`: Individual chain processing results
- `pdb_update.repair_batch`: Repair batch tracking
- `pdb_update.repair_chain`: Chains in repair batches

**Views:**
- `pdb_update.release_summary`: Summary of all releases
- `pdb_update.chains_needing_hhsearch`: Chains pending HHsearch
- `pdb_update.failed_chains`: All failed chains across batches

### Script
`scripts/sync_to_database.py`

### Database Setup

```bash
# Create database and schema
psql -U ecod -d update_protein -f sql/01_create_pdb_update_schema.sql

# Verify
psql -U ecod -d update_protein -c "SELECT * FROM pdb_update.release_summary;"
```

### Usage

#### Check database status:
```bash
python scripts/sync_to_database.py --status
```

#### Sync specific batch:
```bash
python scripts/sync_to_database.py \
    --batch /data/ecod/pdb_updates/batches/ecod_weekly_20250905
```

#### Sync all batches:
```bash
python scripts/sync_to_database.py \
    --all \
    --base-path /data/ecod/pdb_updates/batches
```

#### Update existing records:
```bash
python scripts/sync_to_database.py \
    --all \
    --overwrite
```

#### Custom database connection:
```bash
python scripts/sync_to_database.py \
    --host db.example.com \
    --port 5432 \
    --database update_protein \
    --user ecod \
    --all
```

### What Gets Synced

For each batch:
1. **Batch metadata**: Release date, paths, counts, status, timestamps
2. **Chain status**: BLAST/HHsearch/partition results, coverage, quality
3. **File paths**: Locations of FASTA, BLAST, HHsearch, summary, partition files
4. **Error tracking**: Failure reasons for failed chains

### Database Queries

#### Get batch summary:
```sql
SELECT * FROM pdb_update.release_summary
ORDER BY release_date DESC;
```

#### Find chains needing HHsearch:
```sql
SELECT pdb_id, chain_id, blast_coverage
FROM pdb_update.chains_needing_hhsearch
WHERE release_date = '2025-09-05';
```

#### Find failed chains:
```sql
SELECT * FROM pdb_update.failed_chains
WHERE release_date > '2025-09-01';
```

#### Get partition quality statistics:
```sql
SELECT
    partition_quality,
    COUNT(*) as chain_count,
    AVG(partition_coverage) as avg_coverage
FROM pdb_update.chain_status
WHERE release_date = '2025-09-05'
  AND can_classify = true
GROUP BY partition_quality;
```

### Features

- **Idempotent syncing**: Safe to run multiple times (upsert logic)
- **Batch or individual**: Sync one batch or all at once
- **Progress tracking**: Database tracks processing status across batches
- **Historical analysis**: Query trends across multiple releases
- **Integration preparation**: Database ready for ECOD domain integration

---

## Complete Production Workflow

### 1. Initial Setup (One-time)

```bash
# Create database schema
psql -U ecod -d update_protein -f sql/01_create_pdb_update_schema.sql

# Determine last ECOD update date
LAST_UPDATE="2025-09-05"
```

### 2. Catch-up Processing

```bash
# Process all weeks since last update
python scripts/process_update_weeks.py \
    --start-date $LAST_UPDATE \
    --submit \
    --base-path /data/ecod/pdb_updates/batches
```

### 3. Sync to Database

```bash
# Sync all completed batches
python scripts/sync_to_database.py \
    --all \
    --base-path /data/ecod/pdb_updates/batches
```

### 4. Check for Issues

```bash
# Check database status
python scripts/sync_to_database.py --status

# Query failed chains
psql -U ecod -d update_protein -c "
SELECT pdb_id, chain_id, failure_reason
FROM pdb_update.failed_chains
LIMIT 20;
"
```

### 5. Repair Failed Chains

```bash
# Export failed chains
psql -U ecod -d update_protein -t -A -F' ' -c "
SELECT pdb_id, chain_id, release_date
FROM pdb_update.failed_chains;
" > failed_chains.txt

# Create repair batch
python scripts/process_repair_batch.py \
    --chains-file failed_chains.txt \
    --reason error_fix \
    --rerun-partition
```

### 6. Weekly Ongoing Processing

```bash
# Process latest week (run weekly via cron)
LATEST_WEEK=$(date -d "last thursday" +%Y-%m-%d)

python scripts/process_update_weeks.py \
    --start-date $LATEST_WEEK \
    --max-batches 1 \
    --submit

# Sync to database
python scripts/sync_to_database.py \
    --batch /data/ecod/pdb_updates/batches/ecod_weekly_${LATEST_WEEK//-/}
```

---

## File Locations

### Scripts
- **Update weeks**: `scripts/process_update_weeks.py`
- **Repair batches**: `scripts/process_repair_batch.py`
- **Database sync**: `scripts/sync_to_database.py`

### Source Code
- **Database module**: `src/pyecod_prod/database/sync.py`
- **Batch management**: `src/pyecod_prod/batch/weekly_batch.py`
- **Manifest tracking**: `src/pyecod_prod/batch/manifest.py`

### Data Locations
- **Batch output**: `/data/ecod/pdb_updates/batches/`
- **PDB status**: `/usr2/pdb/data/status/{YYYYMMDD}/`
- **Database schema**: `sql/01_create_pdb_update_schema.sql`

---

## Best Practices

### Update Weeks
- Run dry-run first to verify release list
- Process in chronological order (oldest to newest)
- Monitor first few batches before processing all
- Use `--max-batches` for testing

### Repair Batches
- Always specify clear `--reason` for tracking
- Use `--dry-run` to preview changes
- Default to partition-only reprocessing (faster)
- Only rerun BLAST/HHsearch if absolutely necessary

### Database Integration
- Sync batches after completion, not during processing
- Use `--overwrite` to update corrected results
- Run `--status` regularly to monitor overall progress
- Query failed chains weekly for repair batch creation

---

## Troubleshooting

### Update weeks stuck on a failed batch
The script continues to next week automatically. Check logs and create repair batch for failed week.

### Repair batch missing chain data
Chains without source manifest entries get minimal metadata. Ensure source weeks were processed and synced.

### Database connection failed
Check `.pgpass` file, database user permissions, and network connectivity. Database is optional - framework works from YAML alone.

### How to resume interrupted processing
All scripts support resume. Just rerun the same command - completed batches are skipped automatically.
