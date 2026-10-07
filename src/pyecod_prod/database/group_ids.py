"""Validation for ECOD group identifiers written to ecod_commons.

Exists because repair item 5 (v295/HIERARCHY_REPAIR_LIST.md) found 78 domains whose
``f_group_assignments.f_group_id`` held something that is not an F-group at all:

* 17 distinct **T-group ids** (``101.1.9``, ``2004.1.1``) across 27 domains
* 20 distinct **protein accessions** (``EPP00001216``, ``JAHQJS010000004.1``) across
  51 domains

Both came from one place: pyecod_mini's ``get_domain_family_name`` returns a
*provenance label* -- T-group, else source PDB/accession, else reference domain id --
and a consumer mapped that label straight into ``f_group_id``. Nothing validated the
shape on the way in, so two production runs (2026-03-29, 2026-06-11) wrote garbage
silently and it surfaced months later in the hierarchy generator.

The mapping is fixed at source. This module is the backstop that makes a recurrence
impossible to write rather than merely unlikely.
"""

from __future__ import annotations

import re
from typing import Optional

# <x>.<h>.<t>.<f>, e.g. 2004.1.1.1. The topology-only form <x>.<h>.<t>.0 is a valid
# f_group_id in ecod_commons and is deliberately accepted here.
F_GROUP_RE = re.compile(r"^[0-9]+(\.[0-9]+){3}$")

# <x>.<h>.<t>, e.g. 2004.1.1 -- a T-group. Called out separately because writing one
# of these into the F column is precisely repair item 5 half A.
T_GROUP_RE = re.compile(r"^[0-9]+(\.[0-9]+){2}$")


def is_f_group(value: Optional[str]) -> bool:
    """True if `value` is a well-formed 4-field F-group id."""
    return bool(value) and bool(F_GROUP_RE.match(value))


def clean_f_group(value: Optional[str], *, context: str, log=None) -> Optional[str]:
    """Return `value` if it is a real F-group id, else None with a loud log line.

    Returning None rather than raising is deliberate: both insert paths fall through
    to ``t_group_only_assignments`` when there is no F-group, which is the correct
    record for a domain whose family is unknown. A malformed value is dropped, never
    written -- but a long batch is not aborted by one bad row.
    """
    if is_f_group(value):
        return value
    if value is None:
        return None

    if T_GROUP_RE.match(value):
        why = "looks like a T-group, not an F-group (repair item 5 half A)"
    else:
        why = "is not a group id at all -- probably a protein accession or a domain id (repair item 5 half B)"
    msg = (
        f"REFUSING to write f_group_id={value!r} for {context}: {why}. "
        "Recording as topology-only instead. This indicates a field-mapping bug "
        "upstream; see pyecod_prod/database/group_ids.py."
    )
    if log is not None:
        log.error(msg)
    else:  # pragma: no cover - only when a caller has no logger to hand
        import warnings

        warnings.warn(msg, stacklevel=2)
    return None
