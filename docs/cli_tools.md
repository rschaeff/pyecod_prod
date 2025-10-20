# CLI Tools Reference

Quick reference for command-line tools to monitor and assess pyECOD batches.

---

## 1. Check Batch Status (`check_batch_status.py`)

**Purpose**: Assess the state of a batch directory from its YAML manifest.

### Basic Usage

```bash
# Check batch status
python scripts/check_batch_status.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905

# Validate all file paths exist
python scripts/check_batch_status.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --validate-files

# JSON output for scripting
python scripts/check_batch_status.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --json
```

### What It Shows

- Batch metadata (name, type, created date, reference version)
- Chain counts (total, classifiable, non-classifiable)
- Processing progress (BLAST, HHsearch, partition completion rates)
- Coverage statistics (average, min, max)
- Quality distribution
- File validation (optional)

### Example Output

```
======================================================================
Batch Status: ecod_weekly_20250905
======================================================================
Type: weekly
Path: /data/ecod/pdb_updates/batches/ecod_weekly_20250905
Created: 2025-10-19T21:13:00
Reference: develop291
Overall Status: COMPLETE

======================================================================
Chain Summary
======================================================================
Total chains: 100
  Classifiable: 100
  Non-classifiable: 0

======================================================================
Processing Progress
======================================================================
BLAST Status:
  complete        100 (100.0%)

HHsearch Status:
  Chains needing HHsearch: 47
  complete         47
  not_needed       53

Partition Status:
  complete        100 (100.0%)

======================================================================
Coverage Statistics
======================================================================
BLAST Coverage:
  Chains: 100
  Average: 92.5%
  Range: 45.2% - 100.0%

Partition Coverage:
  Chains: 100
  Average: 88.3%
  Range: 52.1% - 100.0%
```

### Exit Codes

- `0`: Batch complete
- `1`: Batch incomplete/in progress
- `2`: File not found
- `3`: Other error

---

## 2. Check Database Status (`check_database_status.py`)

**Purpose**: Query PostgreSQL database to see what's been synced/checked in.

### Basic Usage

```bash
# Overall database status
python scripts/check_database_status.py

# Specific week
python scripts/check_database_status.py --week 2025-09-05

# Show failed chains
python scripts/check_database_status.py --failed

# Show chains needing HHsearch
python scripts/check_database_status.py --hhsearch

# Batch summary table
python scripts/check_database_status.py --summary

# JSON output
python scripts/check_database_status.py --json
```

### Custom Database Connection

```bash
python scripts/check_database_status.py \
    --host db.example.com \
    --port 5432 \
    --database update_protein \
    --user ecod
```

### What It Shows

**Overall Status**:
- Total batches synced
- Status breakdown (pending, processing, complete, failed)
- Date range
- Chain statistics (total, classifiable, completed)
- Coverage averages
- Quality distribution

**Week-Specific**:
- Batch metadata and status
- Processing breakdown
- Coverage statistics
- Quality distribution

**Failed Chains**:
- PDB ID, Chain ID, Week
- Failure reason

**HHsearch Pending**:
- Chains with low BLAST coverage (<90%)
- Current HHsearch status

### Example Output

```
======================================================================
Database Status - Overall Summary
======================================================================

Batches:
  Total batches: 8
  Date range: 2025-09-05 to 2025-10-10
  Status breakdown:
    complete            5 ( 62.5%)
    processing          2 ( 25.0%)
    pending             1 ( 12.5%)

Chains:
  Total chains: 13,416
  Classifiable: 13,248
  BLAST complete: 13,248 (100.0%)
  Partition complete: 10,436 (78.8%)
  Failed: 24
  HHsearch pending: 312

Coverage Statistics:
  Average BLAST coverage: 91.2%
  Average partition coverage: 87.5%
  Average domains/chain: 3.45

Partition Quality Distribution:
  good                 9,234 ( 88.5%)
  low_coverage           892 (  8.5%)
  fragmentary            310 (  3.0%)
```

---

## 3. Batch Quality Statistics (`batch_quality_stats.py`)

**Purpose**: Generate detailed quality statistics for domain classification results.

### Basic Usage

```bash
# Basic statistics
python scripts/batch_quality_stats.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905

# Detailed statistics
python scripts/batch_quality_stats.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --detailed

# Show outliers
python scripts/batch_quality_stats.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --outliers

# Export to CSV
python scripts/batch_quality_stats.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --csv results.csv

# JSON output
python scripts/batch_quality_stats.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --json
```

### What It Shows

**Coverage Statistics**:
- BLAST, HHsearch, partition coverage
- Mean, median, range, standard deviation
- Coverage distribution histograms

**Domain Statistics**:
- Domains per chain (mean, median, range)
- Domain count distribution
- Zero-domain chains

**Quality Distribution**:
- Quality category breakdown (good, low_coverage, fragmentary)
- Visual bar charts

**Outlier Detection**:
- Low coverage chains (<50%)
- High domain count (>10 domains)
- Zero domains
- Fragmentary quality

**Sequence Length**:
- Length statistics
- Correlation with domain count

### Example Output

```
======================================================================
Quality Statistics: ecod_weekly_20250905
======================================================================
Batch type: weekly
Total chains analyzed: 100

======================================================================
Coverage Statistics
======================================================================

BLAST Coverage:
  Chains: 100
  Mean: 92.5% ± 12.3%
  Median: 95.2%
  Range: 45.2% - 100.0%

Partition Coverage:
  Chains: 100
  Mean: 88.3% ± 15.1%
  Median: 92.1%
  Range: 52.1% - 100.0%

Partition Coverage Distribution:
  0-25%           2 (  2.0%) █
  25-50%          5 (  5.0%) ██
  50-75%         12 ( 12.0%) ██████
  75-90%         23 ( 23.0%) ███████████
  90-100%        58 ( 58.0%) █████████████████████████████

======================================================================
Domain Statistics
======================================================================
  Chains with domains: 100
  Mean domains/chain: 3.24 ± 2.15
  Median: 3
  Range: 0 - 12

======================================================================
Quality Distribution
======================================================================
  fragmentary          8 (  8.0%) ████
  good                82 ( 82.0%) █████████████████████████████████████████
  low_coverage        10 ( 10.0%) █████

======================================================================
Outliers
======================================================================

Low Coverage (<50%):
  Count: 7
    8abc_A: 35.2% coverage, 2 domains
    8def_B: 42.1% coverage, 1 domains
    ...

High Domain Count (>10 domains):
  Count: 3
    8xyz_A: 12 domains, 1245 residues
    8tuv_C: 11 domains, 987 residues
    ...

Zero Domains:
  Count: 2
    8foo_X: 52.1% coverage
    8bar_Y: 48.3% coverage
```

### CSV Export

Creates a CSV file with columns:
- `pdb_id`
- `chain_id`
- `sequence_length`
- `blast_coverage`
- `hhsearch_coverage`
- `partition_coverage`
- `domain_count`
- `quality`

Useful for:
- Excel analysis
- Plotting with R/Python
- Database import
- Further filtering

---

## Common Workflows

### Daily Monitoring

```bash
# Check latest batch
LATEST_BATCH=$(ls -td /data/ecod/pdb_updates/batches/ecod_weekly_* | head -1)
python scripts/check_batch_status.py $LATEST_BATCH

# Check database sync status
python scripts/check_database_status.py --summary
```

### Quality Assurance

```bash
# Check for outliers
python scripts/batch_quality_stats.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --outliers

# Validate files exist
python scripts/check_batch_status.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --validate-files

# Export for detailed analysis
python scripts/batch_quality_stats.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --csv analysis.csv
```

### Finding Issues

```bash
# Find failed chains in database
python scripts/check_database_status.py --failed

# Find chains pending HHsearch
python scripts/check_database_status.py --hhsearch

# Check incomplete batches
for batch in /data/ecod/pdb_updates/batches/ecod_weekly_*; do
    echo "Checking $batch"
    python scripts/check_batch_status.py $batch | grep "Overall Status"
done
```

### Batch Comparison

```bash
# Compare quality across weeks
for week in 20250905 20250912 20250919; do
    echo "=== Week $week ==="
    python scripts/batch_quality_stats.py /data/ecod/pdb_updates/batches/ecod_weekly_$week --json | \
        jq '.coverage.partition.mean, .domains.statistics.mean'
done
```

### Scripting with JSON

```bash
# Get batch status as JSON
STATUS=$(python scripts/check_batch_status.py /data/ecod/pdb_updates/batches/ecod_weekly_20250905 --json)

# Extract specific fields
echo $STATUS | jq '.processing_status.overall'
echo $STATUS | jq '.coverage.partition.avg'

# Conditional actions
if [ "$(echo $STATUS | jq -r '.processing_status.overall')" = "complete" ]; then
    echo "Batch is complete, syncing to database..."
    python scripts/sync_to_database.py --batch /data/ecod/pdb_updates/batches/ecod_weekly_20250905
fi
```

---

## Tool Comparison

| Feature | check_batch_status | check_database_status | batch_quality_stats |
|---------|-------------------|----------------------|---------------------|
| Source | YAML manifest | PostgreSQL | YAML manifest |
| Speed | Fast | Medium | Fast |
| Requires DB | No | Yes | No |
| Overall status | ✓ | ✓ | - |
| Processing progress | ✓ | ✓ | - |
| Coverage stats | Basic | Basic | Detailed |
| Quality analysis | Basic | Basic | Comprehensive |
| Outlier detection | - | - | ✓ |
| Historical data | - | ✓ | - |
| CSV export | - | - | ✓ |
| File validation | ✓ | - | - |

---

## Tips

1. **Use `check_batch_status.py` for**:
   - Quick local batch checks
   - File validation
   - Progress monitoring during processing

2. **Use `check_database_status.py` for**:
   - Cross-batch analysis
   - Historical tracking
   - Finding failed chains across all weeks
   - Production monitoring

3. **Use `batch_quality_stats.py` for**:
   - Detailed quality assessment
   - Outlier identification
   - Data export for further analysis
   - Publication-ready statistics

4. **Combine tools**:
   ```bash
   # Check batch, then sync if complete
   if python scripts/check_batch_status.py $BATCH --json | jq -e '.processing_status.overall == "complete"'; then
       python scripts/sync_to_database.py --batch $BATCH
       python scripts/batch_quality_stats.py $BATCH --detailed
   fi
   ```

5. **Set up aliases** (add to ~/.bashrc):
   ```bash
   alias check-batch='python /path/to/scripts/check_batch_status.py'
   alias check-db='python /path/to/scripts/check_database_status.py'
   alias batch-stats='python /path/to/scripts/batch_quality_stats.py'
   ```
