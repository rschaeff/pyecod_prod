# Version Tracking for pyecod-mini Integration

## Current Status

### ✅ Already Implemented in pyecod_prod

1. **partition_runner.py** expects `algorithm_version` from pyecod_mini:
   - `PartitionResult.algorithm_version` field defined (line 56)
   - Captures version from library API (line 216)
   - Parses version from CLI XML output (line 408)
   - Logs version in output (line 204, 511)

2. **Manifest tracking** includes version information:
   - Stored with partition results
   - Available for reporting and analysis

3. **API Spec** defines version requirements:
   - Library API should return `algorithm_version` (PYECOD_MINI_API_SPEC.md:120)
   - Partition XML should include `algorithm_version` attribute (PYECOD_MINI_API_SPEC.md:267)

### ⏳ Pending Implementation in pyecod_mini

1. **Library API** needs to be created:
   - Export `partition_protein()` function from `pyecod_mini/__init__.py`
   - Define `PartitionResult` dataclass with `algorithm_version` field
   - Return `algorithm_version` from `__version__`

2. **XML Writer** needs to include version:
   - `write_domain_partition()` should write `algorithm_version` attribute to `<partition>` root element
   - Use `pyecod_mini.__version__` (currently "2.0.0")

3. **CLI** needs to support `--version`:
   - Print version and exit
   - Follow standard CLI conventions

## Implementation Tasks

### Task 1: Create Library API in pyecod_mini

**File**: `/home/rschaeff/dev/pyecod_mini/src/pyecod_mini/__init__.py`

```python
"""
pyECOD Mini - Clean Domain Partitioning Tool
"""

__version__ = "2.0.0"
__author__ = "pyECOD Mini Development Team"

# Export library API
from pyecod_mini.api import partition_protein, PartitionResult, PartitionError

__all__ = ["partition_protein", "PartitionResult", "PartitionError", "__version__"]
```

**New File**: `/home/rschaeff/dev/pyecod_mini/src/pyecod_mini/api.py`

```python
"""
Library API for pyecod_mini - Clean interface for integration with pyecod_prod.

Per PYECOD_MINI_API_SPEC.md.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pyecod_mini


class PartitionError(Exception):
    """Raised when partitioning fails"""
    pass


@dataclass
class Domain:
    """A single partitioned domain"""
    domain_id: str
    range_string: str  # e.g., "10-110" or "10-50,60-110"
    residue_count: int
    source: str  # 'chain_blast', 'domain_blast', 'hhsearch'
    family_name: str
    confidence: Optional[float] = None


@dataclass
class PartitionResult:
    """Result from domain partitioning"""
    success: bool
    pdb_id: str
    chain_id: str
    sequence_length: int
    domains: List[Domain]
    coverage: float  # 0.0-1.0
    partition_xml_path: str
    algorithm_version: str  # e.g., "2.0.0"
    error_message: Optional[str] = None


def partition_protein(
    summary_xml: str,
    output_xml: str,
    pdb_id: str,
    chain_id: str,
    batch_id: Optional[str] = None,
) -> PartitionResult:
    """
    Partition a protein into domains using evidence from domain_summary.xml.

    Args:
        summary_xml: Path to domain_summary.xml (input)
        output_xml: Path to partition.xml (output)
        pdb_id: PDB ID
        chain_id: Chain ID
        batch_id: Optional batch ID for tracking

    Returns:
        PartitionResult with domains, coverage, and metadata

    Raises:
        PartitionError: If partitioning fails
        FileNotFoundError: If summary_xml doesn't exist

    Example:
        >>> result = partition_protein(
        ...     summary_xml="/path/to/8abc_A.summary.xml",
        ...     output_xml="/path/to/8abc_A.partition.xml",
        ...     pdb_id="8abc",
        ...     chain_id="A",
        ... )
        >>> print(f"Found {len(result.domains)} domains, {result.coverage:.1%} coverage")
    """

    # Implementation will call existing partition logic and convert to PartitionResult
    # This is the integration point between pyecod_mini and pyecod_prod

    try:
        # Parse summary XML, run partitioning, write partition XML
        # ... (implementation details)

        # Return result with version
        return PartitionResult(
            success=True,
            pdb_id=pdb_id,
            chain_id=chain_id,
            sequence_length=sequence_length,
            domains=converted_domains,
            coverage=calculated_coverage,
            partition_xml_path=output_xml,
            algorithm_version=pyecod_mini.__version__,  # "2.0.0"
            error_message=None,
        )

    except Exception as e:
        raise PartitionError(f"Partitioning failed: {e}") from e
```

### Task 2: Update XML Writer to Include Version

**File**: `/home/rschaeff/dev/pyecod_mini/src/pyecod_mini/core/writer.py`

Update `write_domain_partition()` to include `algorithm_version` attribute:

```python
def write_domain_partition(...):
    """Write partition results to XML"""

    root = ET.Element("partition")
    root.set("version", "1.0")  # Schema version
    root.set("algorithm", "pyecod-mini")

    # ADD THIS LINE:
    import pyecod_mini
    root.set("algorithm_version", pyecod_mini.__version__)

    # ... rest of XML generation
```

### Task 3: Add CLI --version Support

**File**: `/home/rschaeff/dev/pyecod_mini/src/pyecod_mini/cli/__main__.py`

```python
def main():
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--version", action="version", version=f"pyecod-mini {pyecod_mini.__version__}")
    # ... rest of CLI
```

## Version Compatibility Policy

### Semantic Versioning

pyecod_mini follows semantic versioning: `MAJOR.MINOR.PATCH`

- **MAJOR**: Breaking changes to API or algorithm behavior
- **MINOR**: New features, backward-compatible
- **PATCH**: Bug fixes, no algorithm changes

### Compatibility Matrix

| pyecod_mini | pyecod_prod | Status | Notes |
|-------------|-------------|--------|-------|
| 2.0.0       | 1.0.0+      | ✅ Compatible | Current production |
| 2.1.x       | 1.0.0+      | ✅ Compatible | Minor updates OK |
| 3.0.0       | 2.0.0+      | ⚠️  Breaking | Requires prod update |

### Version Checking in pyecod_prod

**Optional Enhancement**: Add version compatibility checks in `partition_runner.py`:

```python
def _check_version_compatibility(self, algorithm_version: str):
    """Check if pyecod_mini version is compatible"""
    import packaging.version as pv

    mini_version = pv.parse(algorithm_version)
    min_required = pv.parse("2.0.0")
    max_supported = pv.parse("3.0.0")

    if mini_version < min_required:
        logger.warning(f"pyecod_mini {algorithm_version} is older than required {min_required}")
    elif mini_version >= max_supported:
        logger.warning(f"pyecod_mini {algorithm_version} may have breaking changes (max supported: {max_supported})")
```

## Testing Version Tracking

### Unit Tests

**File**: `/home/rschaeff/dev/pyecod_mini/tests/test_api.py`

```python
def test_partition_result_includes_version():
    """Test that PartitionResult includes algorithm_version"""
    result = partition_protein(...)
    assert result.algorithm_version == pyecod_mini.__version__
    assert result.algorithm_version.startswith("2.")
```

**File**: `/home/rschaeff/dev/pyecod_prod/tests/test_partition_runner.py`

```python
def test_version_captured_from_library():
    """Test that partition_runner captures version from pyecod_mini"""
    result = runner.partition(...)
    assert result.algorithm_version is not None
    assert "." in result.algorithm_version  # Semantic version format
```

### Integration Tests

```bash
# Verify version in output XML
python -m pyecod_mini 8abc_A --summary-xml /path/to/summary.xml --output /tmp/partition.xml
grep 'algorithm_version' /tmp/partition.xml
# Should show: algorithm_version="2.0.0"

# Verify CLI --version
pyecod-mini --version
# Should print: pyecod-mini 2.0.0
```

## Migration Plan

### Phase 1: pyecod_mini Library API (Week 1)
- [ ] Create `api.py` with `partition_protein()` function
- [ ] Define `PartitionResult` and `PartitionError` classes
- [ ] Export from `__init__.py`
- [ ] Add unit tests

### Phase 2: Version Tracking (Week 1)
- [ ] Update `writer.py` to include `algorithm_version` in XML
- [ ] Add CLI `--version` support
- [ ] Test version appears in all outputs

### Phase 3: pyecod_prod Integration (Week 2)
- [ ] Update `partition_runner.py` to use library API (already done!)
- [ ] Test library API integration
- [ ] Verify version captured in manifests

### Phase 4: Documentation (Week 2)
- [ ] Update PYECOD_MINI_API_SPEC.md with library API examples
- [ ] Document version compatibility policy
- [ ] Add version tracking to CLAUDE.md

## References

- **API Spec**: `/home/rschaeff/dev/pyecod_prod/PYECOD_MINI_API_SPEC.md`
- **pyecod_mini Version**: `/home/rschaeff/dev/pyecod_mini/src/pyecod_mini/__init__.py:7`
- **partition_runner.py**: `/home/rschaeff/dev/pyecod_prod/src/pyecod_prod/core/partition_runner.py`
- **Writer**: `/home/rschaeff/dev/pyecod_mini/src/pyecod_mini/core/writer.py`

## Notes

- pyecod_prod is **already ready** to use version information from pyecod_mini
- pyecod_mini needs to **implement the library API** per spec
- Version tracking enables reproducibility and debugging
- Semantic versioning allows controlled evolution of the algorithm
