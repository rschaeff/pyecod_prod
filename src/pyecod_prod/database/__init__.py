"""Database integration for pyECOD Production Framework"""

from .sync import DatabaseSync
from .curation_loader import (
    load_partition_to_curation,
    classify_partition_quality,
    can_curate,
    get_cannot_curate_reason,
    should_queue_for_curation,
    calculate_queue_priority,
)
from .domain_overlap import (
    DomainOverlapChecker,
    OverlapSeverity,
    OverlapConflict,
    DomainRange,
    RangeSegment,
    parse_range,
    calculate_overlap,
    assess_overlap_severity,
)
from .auto_accession import (
    AutoAccessionLoader,
    AccessionDecision,
    AccessionResult,
    BatchAccessionSummary,
    ProcessingContext,
    get_pyecod_mini_version,
    get_pyecod_prod_version,
)

__all__ = [
    # Sync
    "DatabaseSync",
    # Curation loader
    "load_partition_to_curation",
    "classify_partition_quality",
    "can_curate",
    "get_cannot_curate_reason",
    "should_queue_for_curation",
    "calculate_queue_priority",
    # Domain overlap detection
    "DomainOverlapChecker",
    "OverlapSeverity",
    "OverlapConflict",
    "DomainRange",
    "RangeSegment",
    "parse_range",
    "calculate_overlap",
    "assess_overlap_severity",
    # Auto-accession
    "AutoAccessionLoader",
    "AccessionDecision",
    "AccessionResult",
    "BatchAccessionSummary",
    "ProcessingContext",
    "get_pyecod_mini_version",
    "get_pyecod_prod_version",
]
