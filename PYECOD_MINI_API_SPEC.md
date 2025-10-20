# pyecod_mini API Specification

**Version**: 1.0.0
**Date**: 2025-10-19
**Status**: Draft

---

## Purpose

This document defines the formal API contract between **pyecod_mini** (domain partitioning algorithm) and **pyecod_prod** (production infrastructure). This specification ensures clean separation of concerns and prevents architectural coupling.

## Architectural Principles

### Separation of Concerns

| Responsibility | pyecod_mini (Algorithm) | pyecod_prod (Infrastructure) |
|---------------|------------------------|------------------------------|
| Domain partitioning algorithm | ✅ Owns | ❌ Never modifies |
| Evidence parsing (BLAST, HHsearch) | ✅ Reads evidence XML | ❌ |
| Coverage calculation | ✅ From partition | ⚠️ May verify |
| Evidence generation (BLAST/HHsearch execution) | ❌ | ✅ Owns |
| Quality policy (thresholds) | ❌ | ✅ Owns |
| SLURM integration | ❌ | ✅ Owns |
| Batch orchestration | ❌ | ✅ Owns |
| Database integration | ❌ | ✅ Owns |

### Design Boundaries

**pyecod_mini MUST:**
- Be portable (works on any system: laptop, cluster, cloud)
- Accept all paths via arguments (no hardcoded paths)
- Have no SLURM dependencies
- Have no database dependencies
- Have no knowledge of batch workflows
- Provide clean library API + CLI
- Calculate coverage from its own partitions
- Version its output format

**pyecod_prod MUST:**
- Never modify pyecod_mini algorithm code
- Call pyecod_mini as black box (library or CLI)
- Define ECOD-specific quality policies
- Handle production errors (timeouts, retries)
- Manage batch state independently
- Pin pyecod_mini versions for reproducibility

**Dependency Direction:**
```
pyecod_prod  ──imports──>  pyecod_mini
pyecod_mini  ──────✗─────>  pyecod_prod  (NEVER)
```

---

## API Contract

### Library API (Primary)

```python
from pyecod_mini import partition_protein, PartitionError

def partition_protein(
    summary_xml: str | Path,
    output_xml: str | Path | None = None,
    *,
    pdb_id: str | None = None,
    chain_id: str | None = None,
    batch_id: str | None = None,
    verbose: bool = False,
) -> PartitionResult:
    """
    Partition a protein chain into domains based on evidence.

    Args:
        summary_xml: Path to domain_summary.xml (contains evidence)
        output_xml: Path to write partition.xml (None = in-memory only)
        pdb_id: Override PDB ID from XML metadata
        chain_id: Override chain ID from XML metadata
        batch_id: Optional batch identifier for tracking/logging
        verbose: Enable detailed logging to stderr

    Returns:
        PartitionResult containing domains, coverage, and metadata

    Raises:
        FileNotFoundError: summary_xml does not exist
        PartitionError: Partitioning failed (parse error, algorithm failure)
        ValueError: Invalid arguments

    Notes:
        - All file paths are relative to caller's working directory
        - No assumptions about file locations
        - Thread-safe (no global state)
        - Deterministic given same input
    """
```

**Return Type:**

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class PartitionResult:
    """Result from domain partitioning."""

    # Protein metadata
    pdb_id: str
    chain_id: str
    sequence_length: int
    sequence: str  # Amino acid sequence

    # Partition results
    domains: List[Domain]
    coverage: float  # Fraction of sequence covered (0.0 - 1.0)

    # Algorithm metadata
    algorithm_version: str  # Semantic version (e.g., "1.0.0")
    success: bool  # True if partitioning succeeded
    error_message: Optional[str]  # None if success=True

    # Optional metadata
    batch_id: Optional[str] = None
    timestamp: Optional[str] = None  # ISO 8601 format

@dataclass
class Domain:
    """A partitioned domain."""

    domain_id: str  # e.g., "8ovp_A_001"
    range_string: str  # e.g., "10-110,150-200" (1-indexed, inclusive)
    residue_count: int  # Number of residues in domain

    # ECOD classification
    ecod_domain_id: str  # e.g., "e1suaA1" (representative domain)
    family_name: str  # Human-readable name (e.g., "GFP-like")

    # Evidence source
    source: str  # "chain_blast", "domain_blast", "hhsearch", "combined"
    confidence: Optional[float] = None  # Algorithm-specific confidence (0.0-1.0)

class PartitionError(Exception):
    """Raised when domain partitioning fails."""
    pass
```

---

### CLI API (Secondary)

```bash
pyecod-mini <pdb_chain_id> \
  --summary-xml <path> \
  --output <path> \
  [--batch-id <id>] \
  [--verbose] \
  [--version]

# Examples:
pyecod-mini 8ovp_A \
  --summary-xml summaries/8ovp_A.summary.xml \
  --output partitions/8ovp_A.partition.xml

pyecod-mini 8ovp_A \
  --summary-xml summaries/8ovp_A.summary.xml \
  --output partitions/8ovp_A.partition.xml \
  --batch-id ecod_weekly_20251019 \
  --verbose
```

**Exit Codes:**
- `0`: Success - partition.xml created
- `1`: Partition error - algorithm failed
- `2`: File not found - summary_xml missing
- `3`: Invalid arguments
- `124`: Timeout (if applicable)

**Output:**
- Writes partition.xml to specified path
- Logs to stderr (if --verbose)
- Minimal stdout (for scripting)

---

## Data Formats

### Input: domain_summary.xml

**Schema Version**: 1.0

```xml
<?xml version="1.0"?>
<domain_summary version="1.0">
  <protein pdb_id="8ovp" chain_id="A" length="475">
    <sequence>MSKGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLVTTFSYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGITHGMDELYK</sequence>
  </protein>

  <evidence>
    <!-- BLAST chain-level hits -->
    <hit type="chain_blast"
         target="e1suaA1"
         target_family="GFP-like"
         evalue="1.2e-50"
         bitscore="245.3"
         identity="0.85"
         coverage="0.87"
         query_range="10-200,350-450"
         target_range="5-195,340-440"/>

    <!-- BLAST domain-level hits -->
    <hit type="domain_blast"
         target="e3baeA1"
         target_family="PBP-like"
         evalue="2.5e-30"
         bitscore="180.2"
         identity="0.72"
         coverage="0.65"
         query_range="220-350"
         target_range="15-145"/>

    <!-- HHsearch hits (if BLAST coverage was low) -->
    <hit type="hhsearch"
         target="e1suaA1"
         target_family="GFP-like"
         probability="95.2"
         evalue="1.5e-25"
         score="125.8"
         query_range="360-470"
         target_range="10-120"/>
  </evidence>

  <metadata>
    <batch_id>ecod_weekly_20251019</batch_id>
    <timestamp>2025-10-19T10:30:00Z</timestamp>
  </metadata>
</domain_summary>
```

**Required Elements:**
- `<protein>` with attributes: `pdb_id`, `chain_id`, `length`
- `<sequence>` - amino acid sequence
- `<evidence>` - at least one `<hit>` element

**Hit Attributes (all required):**
- `type`: "chain_blast", "domain_blast", or "hhsearch"
- `target`: ECOD domain ID (e.g., "e1suaA1")
- `target_family`: Human-readable family name
- `query_range`: Alignment range in query sequence (1-indexed, inclusive)
- `evalue`: E-value (BLAST/HHsearch)
- Plus type-specific attributes (bitscore, probability, etc.)

**Coordinate System:**
- All ranges are **1-indexed** (first residue = 1)
- All ranges are **inclusive** (10-20 includes both 10 and 20)
- Discontinuous ranges: "10-20,30-40" (comma-separated)

---

### Output: partition.xml

**Schema Version**: 1.0

```xml
<?xml version="1.0"?>
<partition version="1.0" algorithm="pyecod-mini" algorithm_version="1.0.0">
  <protein pdb_id="8ovp" chain_id="A" length="475">
    <sequence>MSKGEELFT...</sequence>
    <coverage>0.89</coverage>
    <domain_count>3</domain_count>
  </protein>

  <domains>
    <domain id="8ovp_A_001"
            range="10-110,150-200"
            size="161"
            ecod_domain="e1suaA1"
            family="GFP-like"
            source="chain_blast"
            confidence="0.95"/>

    <domain id="8ovp_A_002"
            range="220-350"
            size="131"
            ecod_domain="e3baeA1"
            family="PBP-like"
            source="domain_blast"
            confidence="0.87"/>

    <domain id="8ovp_A_003"
            range="360-470"
            size="111"
            ecod_domain="e1suaA1"
            family="GFP-like"
            source="hhsearch"
            confidence="0.72"/>
  </domains>

  <metadata>
    <batch_id>ecod_weekly_20251019</batch_id>
    <timestamp>2025-10-19T10:32:15Z</timestamp>
  </metadata>
</partition>
```

**Required Elements:**
- `<partition>` root with `version` and `algorithm_version` attributes
- `<protein>` with `pdb_id`, `chain_id`, `length`
- `<coverage>` - fraction of sequence covered (0.0-1.0)
- `<domain_count>` - number of domains found (may be 0)
- `<domains>` - list of `<domain>` elements (empty if domain_count=0)

**Domain Attributes (all required except confidence):**
- `id`: Unique domain identifier (e.g., "8ovp_A_001")
- `range`: Residue range (same format as input: 1-indexed, inclusive)
- `size`: Number of residues
- `ecod_domain`: ECOD representative domain ID
- `family`: Human-readable family name
- `source`: Evidence source ("chain_blast", "domain_blast", "hhsearch", "combined")
- `confidence`: Optional confidence score (0.0-1.0)

**Coverage Calculation:**
```python
# Union of all domain ranges divided by sequence length
covered_positions = set()
for domain in domains:
    for segment in domain.range.split(','):
        start, end = map(int, segment.split('-'))
        covered_positions.update(range(start, end + 1))

coverage = len(covered_positions) / sequence_length
```

---

## Error Handling Contract

### pyecod_mini Responsibilities

**MUST raise exceptions for:**
- `FileNotFoundError`: Input file not found
- `PartitionError`: Algorithm failures (parse errors, decomposition failures)
- `ValueError`: Invalid arguments

**Exception messages MUST:**
- Be actionable (tell caller what went wrong)
- Include context (file paths, protein IDs)
- Not include stack traces in message

**Example:**
```python
# Good
raise PartitionError(
    f"No valid evidence found in {summary_xml} for {pdb_id}_{chain_id}. "
    f"Summary must contain at least one hit with query_range."
)

# Bad
raise PartitionError("Failed")
```

### pyecod_prod Responsibilities

**MUST handle:**
- All exceptions from pyecod_mini
- Timeouts (via subprocess timeout or asyncio)
- Missing output files
- Corrupt output XML

**MUST NOT:**
- Assume success based on exit code alone
- Continue without error logging
- Re-raise exceptions (breaks batch processing)

**Example:**
```python
try:
    result = partition_protein(summary_xml, output_xml)
    manifest.mark_partition_complete(pdb_id, chain_id, result.coverage)

except PartitionError as e:
    manifest.mark_partition_failed(pdb_id, chain_id, error=str(e))
    logger.error(f"Partition failed for {pdb_id}_{chain_id}: {e}")
    # Continue to next protein

except Exception as e:
    manifest.mark_partition_failed(pdb_id, chain_id, error=f"Unexpected: {e}")
    logger.exception(f"Unexpected error for {pdb_id}_{chain_id}")
    # Continue to next protein
```

---

## Versioning Strategy

### Semantic Versioning

Both XML formats and library API follow [Semantic Versioning 2.0.0](https://semver.org/):

**MAJOR.MINOR.PATCH** (e.g., 1.0.0)

- **MAJOR**: Breaking changes (incompatible API/format changes)
- **MINOR**: New features (backward-compatible)
- **PATCH**: Bug fixes (backward-compatible)

### XML Schema Versions

- `domain_summary.xml`: version="1.0" (set by pyecod_prod)
- `partition.xml`: version="1.0", algorithm_version="1.0.0" (set by pyecod_mini)

### Version Compatibility Matrix

| pyecod_mini | Summary XML | Partition XML | pyecod_prod |
|-------------|-------------|---------------|-------------|
| 1.0.x       | 1.0         | 1.0           | 1.x.x       |
| 1.1.x       | 1.0, 1.1    | 1.0, 1.1      | 1.x.x       |
| 2.0.x       | 2.0         | 2.0           | 2.x.x       |

**Backward Compatibility Rules:**
- pyecod_mini MUST support all MINOR versions within same MAJOR
- pyecod_prod SHOULD pin pyecod_mini version for reproducibility
- Breaking changes require MAJOR version bump and coordination

---

## Integration Patterns

### Pattern 1: Library API (Recommended)

```python
# In pyecod_prod/core/partition_runner.py

from pyecod_mini import partition_protein, PartitionError

class PartitionRunner:
    def partition(self, summary_xml: str, output_dir: str) -> PartitionResult:
        """Run pyecod_mini and add ECOD-specific quality assessment."""

        output_xml = Path(output_dir) / f"{pdb_id}_{chain_id}.partition.xml"

        try:
            # Call pyecod_mini library
            result = partition_protein(
                summary_xml=summary_xml,
                output_xml=output_xml,
                batch_id=self.batch_id,
            )

            # Add ECOD-specific quality assessment
            quality = self._assess_ecod_quality(
                result.domain_count,
                result.coverage,
                result.sequence_length
            )

            # Return pyecod_prod-specific result
            return PartitionResult(
                pdb_id=result.pdb_id,
                chain_id=result.chain_id,
                domains=result.domains,
                coverage=result.coverage,
                quality=quality,  # ECOD-specific
                ...
            )

        except PartitionError as e:
            logger.error(f"Partition failed: {e}")
            return self._create_failure_result(...)
```

**Advantages:**
- ✅ Better error handling (exceptions vs exit codes)
- ✅ No subprocess overhead
- ✅ Direct access to result objects
- ✅ Type safety with IDE support

---

### Pattern 2: CLI Subprocess (Fallback)

```python
# In pyecod_prod/core/partition_runner.py

import subprocess

class PartitionRunner:
    def partition_via_cli(self, summary_xml: str, output_xml: str) -> PartitionResult:
        """Call pyecod_mini CLI as subprocess."""

        cmd = [
            "pyecod-mini",
            f"{pdb_id}_{chain_id}",
            "--summary-xml", summary_xml,
            "--output", output_xml,
            "--batch-id", self.batch_id,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes
                check=False,  # Don't raise on non-zero exit
            )

            if result.returncode != 0:
                logger.error(f"CLI failed: {result.stderr}")
                return self._create_failure_result(...)

            # Parse output XML manually
            return self._parse_partition_xml(output_xml)

        except subprocess.TimeoutExpired:
            logger.error("Partition timed out after 5 minutes")
            return self._create_failure_result(...)
```

**Use When:**
- pyecod_mini not installed as Python package
- Testing CLI compatibility
- Running as SLURM job (isolation)

---

### Pattern 3: Hybrid (Best Practice)

```python
class PartitionRunner:
    def __init__(self):
        # Try to import library
        try:
            from pyecod_mini import partition_protein
            self.use_library = True
            self.partition_fn = partition_protein
        except ImportError:
            self.use_library = False
            logger.warning("pyecod_mini not available as library, using CLI")

    def partition(self, summary_xml, output_xml):
        if self.use_library:
            return self._partition_via_library(...)
        else:
            return self._partition_via_cli(...)
```

---

## Quality Assessment (ECOD-Specific)

**This is pyecod_prod policy, NOT pyecod_mini algorithm.**

```python
# In pyecod_prod/core/partition_runner.py

def _assess_ecod_quality(
    self,
    domain_count: int,
    coverage: float,
    sequence_length: int
) -> str:
    """
    Assess partition quality using ECOD production thresholds.

    This is ECOD-specific policy, not part of the algorithm.
    Thresholds can be adjusted based on production experience.
    """
    if domain_count == 0:
        return "no_domains"

    # ECOD production thresholds (tunable)
    if coverage >= 0.80:
        return "good"
    elif coverage >= 0.50:
        return "low_coverage"
    else:
        return "fragmentary"
```

**Quality Levels:**
- `good`: ≥80% coverage - ready for production
- `low_coverage`: 50-80% coverage - may need manual review
- `fragmentary`: <50% coverage - likely incomplete
- `no_domains`: 0 domains - failed to partition

**Note:** pyecod_mini does NOT make quality judgments. It only:
- Partitions domains
- Calculates coverage
- Reports success/failure

---

## Testing Requirements

### pyecod_mini Tests

**MUST include:**
- Unit tests for all public functions
- Regression tests (6+ known-good proteins)
- Edge cases (no domains, discontinuous domains, low evidence)
- Error handling (missing files, corrupt XML)
- Performance benchmarks (< 10s per protein)

**Example:**
```python
def test_8ovp_A_regression():
    """Regression test for 8ovp_A (known good case)."""
    result = partition_protein(
        summary_xml="tests/data/8ovp_A.summary.xml",
        output_xml="tests/output/8ovp_A.partition.xml"
    )

    assert result.success
    assert result.domain_count == 3
    assert result.coverage >= 0.85
    assert "GFP-like" in [d.family_name for d in result.domains]
```

### pyecod_prod Tests

**MUST include:**
- Integration tests with real pyecod_mini
- Manifest tracking after partition
- Error handling (timeouts, failures)
- Quality assessment thresholds
- Both library and CLI integration paths

**Example:**
```python
def test_partition_runner_integration():
    """Test PartitionRunner with real pyecod_mini."""
    runner = PartitionRunner()

    result = runner.partition(
        summary_xml="test_data/8ovp_A.summary.xml",
        output_dir="test_output"
    )

    assert result.quality in ["good", "low_coverage", "fragmentary", "no_domains"]
    assert result.partition_xml_path.exists()
```

---

## Migration Path

### Phase 1: Define API (Current)
- ✅ Document this specification
- ✅ Review with team
- ✅ Commit to both repos

### Phase 2: Implement in pyecod_mini
- Add library API (`partition_protein()`)
- Add coverage to output XML
- Add version to output XML
- Update tests

### Phase 3: Update pyecod_prod
- Update `PartitionRunner` to use library API
- Separate quality assessment
- Add version pinning
- Update tests

### Phase 4: Validate
- Run small batch (15 chains) end-to-end
- Compare results with old implementation
- Verify all integration points

---

## Appendix: Common Pitfalls

### ❌ DON'T: Let pyecod_mini make policy decisions

```python
# BAD: Quality thresholds in pyecod_mini
def partition_protein(...) -> PartitionResult:
    ...
    if coverage >= 0.80:
        result.quality = "good"  # ❌ This is policy, not algorithm
```

### ✅ DO: Keep pyecod_mini focused on algorithm

```python
# GOOD: pyecod_mini only provides data
def partition_protein(...) -> PartitionResult:
    ...
    result.coverage = calculate_coverage(domains, seq_length)
    return result  # ✅ Caller decides what coverage is "good"
```

---

### ❌ DON'T: Hardcode paths in pyecod_mini

```python
# BAD: Hardcoded ECOD paths
DEFAULT_OUTPUT_DIR = "/data/ecod/partitions"  # ❌ Not portable
```

### ✅ DO: All paths via arguments

```python
# GOOD: Caller provides all paths
def partition_protein(
    summary_xml: str,  # ✅ Caller's responsibility
    output_xml: str | None = None,  # ✅ Optional
):
    ...
```

---

### ❌ DON'T: Silent failures

```python
# BAD: Return partial results on failure
try:
    domains = decompose(...)
except DecompositionError:
    domains = []  # ❌ Hides error from caller

return PartitionResult(domains=domains, success=True)  # ❌ Lies about success
```

### ✅ DO: Explicit errors

```python
# GOOD: Raise exception on failure
try:
    domains = decompose(...)
except DecompositionError as e:
    raise PartitionError(f"Decomposition failed: {e}")  # ✅ Clear error
```

---

### ❌ DON'T: Duplicate coverage calculation

```python
# BAD: pyecod_prod recalculates coverage
result = partition_protein(...)  # Calculates coverage
coverage = recalculate_coverage(result.domains)  # ❌ Duplicate work, may diverge
```

### ✅ DO: Trust pyecod_mini's coverage

```python
# GOOD: Use provided coverage
result = partition_protein(...)
quality = assess_quality(result.coverage)  # ✅ Use algorithm's coverage
```

---

## Document Revision History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0.0   | 2025-10-19 | Initial specification | Claude Code |

---

## References

- [Semantic Versioning 2.0.0](https://semver.org/)
- [XML Best Practices](https://www.w3.org/TR/xml/)
- pyecod_prod CLAUDE.md
- pyecod_mini NEXT_STEPS.md

---

**This is a living document. Changes require review and version bump.**
