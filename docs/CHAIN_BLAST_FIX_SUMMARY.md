# Chain BLAST Integration Fix - October 2025

## Summary

Fixed three critical issues preventing chain BLAST from working correctly in the domain partitioning pipeline. These fixes improved coverage on test case 8yl2_C from 42.6% to 62.7%, and properly flag divergent domains for manual curation.

**Commits:**
- pyecod_mini: `760b939` - "fix: Major chain BLAST integration and partitioning improvements"
- pyecod_prod: `a966dd2` - "fix: Chain BLAST integration with pyecod_mini"

## Problem Discovery

**Test Case**: 8yl2_C (284 residues, 2-domain RAG GTPase)

**Initial State:**
- Only 1 domain assigned: 1-121 (42.6% coverage)
- 213 chain BLAST hits in summary XML
- **0 alignment files loaded** → chain BLAST decomposition impossible
- Strong evidence (6ces_A, e=5.85e-07, range 2-220) not being used

**Root Cause Analysis:**
1. Chain BLAST targets had unparseable IDs (numeric BLAST IDs instead of PDB IDs)
2. No mechanism to pass BLAST directory to pyecod_mini library API
3. Evidence sorted by confidence-first → local optimum trap
4. Decomposed domains bypassed quality thresholds

## Fixes Applied

### Fix 1: Chain BLAST Target ID Extraction

**File**: `pyecod_prod/src/pyecod_prod/core/summary_generator.py`

**Problem**: Used numeric Hit_id (`gnl|BL_ORD_ID|433939`) instead of PDB chain ID

**Solution**: Extract PDB+chain from Hit_def field
```python
def _extract_chain_id(self, hit_def: str) -> Optional[str]:
    """Extract PDB chain ID from Hit_def (e.g., "6ces A" → "6ces_A")"""
    parts = hit_def.strip().split()
    if len(parts) >= 2:
        pdb_id = parts[0].lower()
        chain_id = parts[1]
        return f"{pdb_id}_{chain_id}"
    # ... fallback handling
```

**Impact**: Chain BLAST targets now in parseable "pdb_chain" format

---

### Fix 2: "pdb_chain" Format Support in Parser

**File**: `pyecod_mini/src/pyecod_mini/core/parser.py`

**Problem**: Parser only handled ECOD domain ID format ("e6cesA1"), not chain format ("6ces_A")

**Solution**: Added underscore-split logic
```python
def extract_pdb_chain_robust(domain_id: str, ...):
    # NEW: Check if it's in "pdb_chain" format
    if "_" in domain_id:
        parts = domain_id.split("_")
        if len(parts) >= 2:
            return parts[0], parts[1]  # pdb_id, chain_id
    # ... fallback to ECOD domain ID parsing
```

**Impact**: Can now parse both formats seamlessly

---

### Fix 3: Library API - blast_dir Parameter

**Files**:
- `pyecod_mini/src/pyecod_mini/api.py`
- `pyecod_mini/src/pyecod_mini/cli/partition.py`
- `pyecod_prod/src/pyecod_prod/core/partition_runner.py`
- `pyecod_prod/src/pyecod_prod/batch/weekly_batch.py`

**Problem**: No way to pass BLAST directory through library API

**Solution**: Added `blast_dir` parameter throughout the stack

**api.py**:
```python
def partition_protein(
    summary_xml: str,
    output_xml: str,
    pdb_id: str,
    chain_id: str,
    batch_id: Optional[str] = None,
    blast_dir: Optional[str] = None,  # NEW
) -> PartitionResult:
```

**partition_runner.py**:
```python
def partition(
    self,
    summary_xml: str,
    output_dir: str,
    batch_id: Optional[str] = None,
    blast_dir: Optional[str] = None,  # NEW
) -> PartitionResult:
    # Pass to library or CLI
    mini_result = partition_protein(..., blast_dir=blast_dir)
```

**weekly_batch.py**:
```python
result = self.partition_runner.partition(
    summary_xml=str(summary_full),
    output_dir=str(self.dirs.partitions_dir),
    batch_id=self.batch_name,
    blast_dir=str(self.dirs.blast_dir),  # NEW
)
```

**Impact**: 213 BLAST alignment files now load correctly (was 0)

---

### Fix 4: BLAST Filename Pattern Matching

**File**: `pyecod_mini/src/pyecod_mini/core/blast_parser.py`

**Problem**: Only looked for `.develop291.xml`, not pyecod_prod's `.chain_blast.xml`

**Solution**: Try multiple patterns
```python
filename_patterns = [
    f"{pdb_id}_{chain_id}.chain_blast.xml",  # pyecod_prod format
    f"{pdb_id}_{chain_id}.develop291.xml",    # pyecod_mini batch format
    f"{pdb_id.upper()}_{chain_id}.develop291.xml",  # uppercase variant
    f"{pdb_id}_{chain_id}.chain.blast.xml",   # alternate format
]

for pattern in filename_patterns:
    candidate = os.path.join(blast_dir, pattern)
    if os.path.exists(candidate):
        blast_file = candidate
        break
```

**Impact**: Cross-compatible with both pyecod_prod and pyecod_mini file naming

---

### Fix 5: Sort Order - Coverage-First Strategy

**File**: `pyecod_mini/src/pyecod_mini/core/partitioner.py` (lines 381-406)

**Problem**: Confidence-first sorting created local optimum trap

**Example**:
```
OLD (confidence-first):
  #1  5di3  3-121   conf=0.810 → SELECTED FIRST → blocks positions 3-121
  #20 6ces  2-220   conf=0.630 → arrives late, 45% new coverage → REJECTED

NEW (coverage-first):
  #1  6ces  2-220   coverage=219 → SELECTED FIRST → decomposes to 2 domains
  #2  other hits process remaining positions
```

**Solution**: Sort by query coverage first
```python
def _sort_evidence_by_priority(evidence_list):
    """
    Sort by query coverage first (greedy best-coverage-first).

    CRITICAL: In a greedy algorithm, processing order determines final coverage.
    """
    def evidence_sort_key(e):
        query_positions = len(e.get_positions())
        return (
            -query_positions,  # MOST COVERAGE FIRST (prevents local optimum)
            e.evalue if e.evalue else 999,  # Then best E-value
            -e.confidence,  # Then confidence as tiebreaker
        )
    return sorted(evidence_list, key=evidence_sort_key)
```

**Impact**:
- 8yl2_C: 42.6% → 77.5% coverage (before quality filtering)
- Prevents short high-confidence hits from blocking long medium-confidence hits
- Greedy algorithm now achieves near-optimal coverage in one pass

---

### Fix 6: Quality Filter for Decomposed Domains

**File**: `pyecod_mini/src/pyecod_mini/core/partitioner.py` (lines 472-486)

**Problem**: Decomposed domains bypassed quality thresholds entirely

**Solution**: Apply quality checks AFTER decomposition
```python
for dec_evidence in decomposed_evidence:
    # Apply quality thresholds to decomposed evidence
    if dec_evidence.reference_length and dec_evidence.hit_range:
        ref_coverage = dec_evidence.hit_range.total_length / dec_evidence.reference_length

        # Use same thresholds as EVIDENCE_THRESHOLDS["chain_blast_decomposed"]
        if ref_coverage < 0.5 or dec_evidence.confidence < 0.5:
            if verbose:
                print(f"  ✗ Rejected decomposed domain: {dec_evidence.domain_id}")
                print(f"     Reference coverage: {ref_coverage:.1%} (threshold: 50%)")
                print(f"     → Candidate for new representative")
            decomposition_stats["rejected_poor_quality"] += 1
            continue  # Skip this decomposed domain

    # ... create domain if quality checks pass
```

**Impact**:
- Correctly rejects poor-quality decomposed domains
- 8yl2_C e6cesA2 (35.8% reference coverage) properly rejected
- Flags cases needing manual curation / new representative definition

## Test Results

### 8yl2_C (284 residues, RAG GTPase)

**Before Fixes:**
- Domains: 1 (1-121, 2004.1.1)
- Coverage: 42.6% (121/284)
- Chain BLAST: 0 alignments loaded
- Sequence length: 183 (WRONG - estimation bug)
- Evidence: Strong 6ces_A hit (2-220) ranked #20, rejected

**After All Fixes:**
- Domains: 1 (1-178, 2004.1.1)
- Coverage: 62.7% (178/284)
- Chain BLAST: 213 alignments loaded ✓
- Sequence length: 284 (correct from XML) ✓
- Evidence: 6ces_A ranked #1, decomposed to 2 domains
  - e6cesA1 (93.9% ref coverage) → ACCEPTED ✓
  - e6cesA2 (35.8% ref coverage) → REJECTED ✓
- Unassigned: 179-284 (flagged for manual curation) ✓

**Decomposition Summary:**
```
Chain BLAST decomposition summary:
  Evaluated: 213
  Decomposed: 1
  Rejected Coverage: 212
  Rejected Poor Quality: 1  ← e6cesA2 correctly rejected
```

**Outcome**: Algorithm correctly identifies this as a candidate for new representative definition (not an automatic assignment).

## ECOD Workflow Implications

These fixes ensure the algorithm follows proper ECOD workflow:

1. ✅ **Find best matches** - Coverage-first sort maximizes evidence usage
2. ✅ **Decompose chain hits** - Alignment data enables accurate decomposition
3. ✅ **Apply quality thresholds** - Filters both original and decomposed evidence
4. ✅ **Accept good matches** - High reference coverage (≥50%) passes
5. ✅ **Reject poor matches** - Low reference coverage (<50%) rejected
6. ✅ **Flag for curation** - Unassigned regions signal need for manual review

The algorithm **does not force-fit everything**. Instead, it properly signals "this needs human expertise" by leaving regions unassigned when matches are poor.

## Files Modified

### pyecod_mini (5 files)
- `src/pyecod_mini/api.py` - Added blast_dir parameter to library API
- `src/pyecod_mini/cli/partition.py` - Accept blast_dir, check directory existence
- `src/pyecod_mini/core/blast_parser.py` - Multiple filename pattern support
- `src/pyecod_mini/core/parser.py` - Handle "pdb_chain" format
- `src/pyecod_mini/core/partitioner.py` - Coverage-first sort + quality filtering

### pyecod_prod (3 files)
- `src/pyecod_prod/core/summary_generator.py` - Extract PDB chain IDs from Hit_def
- `src/pyecod_prod/core/partition_runner.py` - Pass blast_dir to pyecod_mini
- `src/pyecod_prod/batch/weekly_batch.py` - Provide BLAST directory

## Testing Commands

```bash
# Test chain BLAST integration
cd /home/rschaeff/dev/pyecod_mini
python3 -c "
from pyecod_mini import partition_protein

result = partition_protein(
    summary_xml='/data/ecod/test_batches/ecod_weekly_20250905/summaries/8yl2_C.summary.xml',
    output_xml='/tmp/8yl2_C.test.xml',
    pdb_id='8yl2',
    chain_id='C',
    batch_id='ecod_weekly_20250905',
    blast_dir='/data/ecod/test_batches/ecod_weekly_20250905/blast'
)

print(f'Domains: {len(result.domains)}')
print(f'Coverage: {result.coverage:.1%}')
for d in result.domains:
    print(f'  {d.domain_id}: {d.range_string} ({d.family_name})')
"

# Expected output:
# Domains: 1
# Coverage: 62.7%
#   d1: 1-178 (2004.1.1)
```

## Future Considerations

### Confidence Abstraction
The current system uses an AI-generated "confidence" mapping that converts E-values to a 0-1 scale:
```python
if evalue < 0.01:
    confidence = 0.5  # Arbitrary cutoff
```

This is **not standard ECOD methodology**. ECOD traditionally uses:
- Direct E-value thresholds (e.g., < 0.002)
- Direct coverage thresholds (e.g., > 50%)
- No intermediate confidence mapping

**Recommendation**: Consider removing the confidence abstraction and using direct E-value thresholds. The confidence mapping adds complexity and obscures the underlying methodology.

**Current Status**: Confidence is still calculated and stored, but the critical sort order now uses coverage first, making the confidence values less impactful.

## Credits

Investigation and fixes completed during debugging session for 8yl2_C domain assignment issue.

**Key Insight**: The user correctly identified that "chain blast without decomposition SHOULD get rejected, but we should never encounter that scenario in a well constructed reference." This led to discovering that chain BLAST alignment data was never being loaded, making decomposition impossible.

**Debugging Strategy**:
1. Traced evidence flow from BLAST XML → summary XML → parser → partitioner
2. Identified missing link (no blast_dir parameter in library API)
3. Fixed entire integration stack (8 files across 2 repositories)
4. Validated with test case showing 42.6% → 62.7% coverage improvement

---

*Document created: October 20, 2025*
*pyecod_mini commit: 760b939*
*pyecod_prod commit: a966dd2*
