# Production Pipeline: Routing Logic & Pfam Integration

**Date**: 2025-10-23
**Status**: DESIGN SPECIFICATION

**See**: [PRODUCTION_WORKFLOW.md](PRODUCTION_WORKFLOW.md) for complete end-to-end workflow.

This document focuses on:
1. **Routing logic** for auto-accession vs. manual curation
2. **Pfam integration** for F-group assignment
3. **Quality thresholds** and decision criteria

---

## Overview

**Goal**: Route partition results from filesystem to appropriate destination:
- **ecod_commons**: High-quality auto-assignments (88-90% of domains)
- **ecod_curation**: Domains needing manual review (10-12% of domains)

**Data Flow**: partition.xml + pfam_hits.tbl → routing decision → ecod_commons OR ecod_curation

**Key Principle**: pdb_update schema is for **tracking only**, not staging partition data

---

## Pfam Integration

### Database Setup

**Purpose**: Assign family-level classification to each putative domain using Pfam v38.

#### Pfam Database

**Location**: `~/data/pfam/v38/Pfam-A.hmm`

**Version**: Pfam v38 (1.8GB uncompressed, 340MB compressed)

**Tool**: `hmmscan` from HMMER suite

**Command**:
```bash
hmmscan --cpu 4 -E 0.001 --domtblout domain_pfam_hits.tbl \
    ~/data/pfam/v38/Pfam-A.hmm \
    domain.fasta
```

#### F-group Lookup

**Authoritative Source**: `ecod_rep.cluster` table

**Key field**: `pfam_acc` (Pfam accession like 'PF00562')

**Query pattern**:
```sql
SELECT id, name, pfam_acc
FROM ecod_rep.cluster
WHERE type = 'F' AND pfam_acc = 'PF00562';
```

**Example result**:
```
     id      |        name         | pfam_acc
-------------+---------------------+----------
 e4753.10.4  | RNA-binding domain  | PF00562
```

**Important**: `ecod_rep` is **policy-controlled** - no automated changes allowed (except potentially new F-groups).

---

## Routing Decision Logic

**Input**: For each domain in partition.xml
- Partition quality (coverage-based)
- Pfam hmmscan results
- BLAST/HHsearch evidence

**Output**: Route to ecod_commons (auto) OR ecod_curation (manual)

### Three Routing Paths

#### Path 1: Direct F-group Assignment → ecod_commons

**Criteria** (ALL must be true):
1. `partition_quality = 'good'` (coverage ≥80%)
2. Pfam hit with E-value ≤ 0.001
3. Pfam→F-group mapping exists in `ecod_rep.cluster`
4. Evidence supports single H-group (no conflicts)

**Action**: Load to `ecod_commons.domains` with F-group assignment

**Database**:
```sql
INSERT INTO ecod_commons.domains (
    uid, ecod_domain_id, pdb_id, chain_id,
    f_id, t_id, h_id, x_id,
    classification_method, classification_status,
    domain_version  -- NULL until bundled
) VALUES (
    gen_uid(), '8abc_A_1', '8abc', 'A',
    '123.1.4', '123', '123.1', '123',
    'mini_pyecod_v2', 'auto', NULL
);
```

**Example**:
```
Domain: 8abc_A_1 (residues 10-150)
Pfam hit: PF00562 (RNA-binding domain, E=1e-25)
ecod_rep lookup: e4753.10.4 (RNA-binding domain)
→ Auto-assign to F-group e4753.10.4
→ Load to ecod_commons (auto status)
→ Will be included in next bundle (v291.1)
```

**Estimated**: ~70% of all domains

#### Path 2: Manual Curation → ecod_curation

**Criteria** (ANY is true):
1. Pfam hit exists BUT no F-group mapping in `ecod_rep.cluster`
   - **Reason**: New F-group needed
   - **Priority**: Medium (5)

2. `partition_quality = 'low_coverage'` or `'fragmentary'`
   - **Reason**: Uncertain domain boundaries
   - **Priority**: High (8-10)

3. Evidence from multiple conflicting H-groups
   - **Reason**: Possible domain fusion or chimera
   - **Priority**: High (7)

**Action**: Load to `ecod_curation` schema for manual review

**Database**:
```sql
-- Insert protein and domains to ecod_curation
INSERT INTO ecod_curation.protein (...);
INSERT INTO ecod_curation.domain_assignment (...);
INSERT INTO ecod_curation.domain_evidence (...);

-- Add to curation queue with priority
INSERT INTO ecod_curation.curation_queue
    (protein_id, priority, priority_reason)
VALUES (protein_id, 5, 'new_pfam_family');
```

**Example**:
```
Domain: 9xyz_B_2 (residues 200-350)
Pfam hit: PF12345 (Hypothetical protein family, E=5e-10)
ecod_rep lookup: NULL (no F-group for PF12345)
→ Route to ecod_curation (new F-group needed)
→ Curator reviews, assigns to new F-group e5000.1.1
→ After approval, accessions to ecod_commons
→ Included in next major version bundle (v292)
```

**Estimated**: ~10-12% of all domains

#### Path 3: .0 Pseudo-group Assignment → ecod_commons

**Criteria** (ALL must be true):
1. No Pfam hit (E-value > 0.001 or no alignments)
2. `partition_quality = 'good'` (coverage ≥80%)
3. Evidence supports single H-group with ≥70% consensus

**Action**: Assign to H-group.0 pseudo-group, load to ecod_commons

**Database**:
```sql
-- Insert domain with H-group only
INSERT INTO ecod_commons.domains (
    uid, ecod_domain_id, pdb_id, chain_id,
    f_id, t_id, h_id, x_id,
    classification_method, classification_status,
    domain_version
) VALUES (
    gen_uid(), '7def_C_1', '7def', 'C',
    NULL,  -- No F-group
    '123', '123.1', '123',
    'mini_pyecod_v2', 'auto', NULL
);

-- Record .0 pseudo-group assignment
INSERT INTO ecod_commons.f_group_assignments (
    domain_id, f_group_name, assignment_type
) VALUES (
    domain_id, '123.1.0', 'pseudo'
);
```

**Example**:
```
Domain: 7def_C_1 (residues 1-120)
Pfam hit: None
BLAST evidence: Multiple hits to H-group e123.1 (all E<0.001)
→ Assign to pseudo-group e123.1.0
→ Load to ecod_commons (auto status)
→ Will be included in next bundle (v291.1)
```

**Note**: .0 pseudo-groups represent domains that:
- Are confidently domains (good partition quality)
- Belong to known H-groups (strong BLAST evidence)
- Lack Pfam family assignment (may be ECOD-specific or poorly characterized)

**Estimated**: ~18-20% of all domains

---

## Bundle Creation

### Minor Version Bundle (v291.1, v291.2, etc.)

**Purpose**: Aggregate auto-assigned domains into versioned release

**Frequency**: Twice yearly (January, July) covering ~26 weekly releases

**Includes**:
- Path 1: Direct F-group assignments (~70%)
- Path 3: .0 pseudo-group assignments (~20%)
- **Total**: ~88-90% of processed domains

**Excludes**:
- Domains in ecod_curation (awaiting manual review)
- Curated results (go to major version)

**Process**:
```bash
python scripts/create_bundle.py \
    --start-date 2025-07-01 \
    --end-date 2025-12-31 \
    --version v291.1 \
    --type minor
```

**What it does**:
1. Query all auto-assigned domains from ecod_commons (domain_version IS NULL)
2. Assign bundle version to `domain_version` field
3. Generate distributable files (XML, flat files)
4. Update ECOD website data
5. Mark chains in pdb_update.chain_status as processed

**Database operations**:
```sql
-- Assign bundle version to unbundled auto domains
UPDATE ecod_commons.domains
SET domain_version = 'v291.1_20260115'
WHERE classification_status = 'auto'
  AND domain_version IS NULL
  AND created_at BETWEEN '2025-07-01' AND '2025-12-31';

-- Update tracking in pdb_update
UPDATE pdb_update.chain_status
SET ecod_status = 'in_current_ecod',
    bundle_version = 'v291.1'
WHERE (pdb_id, chain_id) IN (
    SELECT DISTINCT pdb_id, chain_id
    FROM ecod_commons.domains
    WHERE domain_version = 'v291.1_20260115'
);
```

### Major Version Bundle (v292, v293, etc.)

**Purpose**: Release curated results + new F-groups + hierarchical changes

**Frequency**: Annually or when major curation effort completes

**Includes**:
- Curated domains from ecod_curation (Path 2 after manual review)
- New F-groups added to ecod_rep
- Hierarchical reorganizations
- All unbundled auto domains

**Process**:
```bash
# Accession curated domains from ecod_curation → ecod_commons
python scripts/accession.py batch --name v292

# Create major version bundle
python scripts/create_bundle.py \
    --version v292 \
    --type major \
    --include-curated
```

**Downstream impacts**:
- ECOD website rebuild (new hierarchy)
- Distributable updates (XML, flat files)
- HMM database regeneration
- Literature announcement

---

## Quality Thresholds

### Partition Quality (from pyecod_mini)

**Coverage-based** (tunable):
```python
def assess_quality(coverage):
    if coverage >= 0.80:
        return "good"           # Auto-accession eligible
    elif coverage >= 0.50:
        return "low_coverage"   # Needs review
    else:
        return "fragmentary"    # Likely incomplete
```

**Note**: Coverage calculated by pyecod_mini, quality labels applied by pyecod_prod

### Pfam Hit Thresholds

**E-value**: ≤ 0.001 (domain-level)

**Coverage**: Domain coverage by Pfam HMM ≥ 50% (prevent spurious matches)

**Top hit only**: Use best-scoring Pfam family per domain

### BLAST Evidence Thresholds

**E-value**: ≤ 0.002 (already applied in evidence generation)

**H-group consensus**: ≥70% of hits support same H-group (prevent conflicts)

---

## Summary

This document defines the **routing logic** for classifying partition results:

**Three Paths**:
1. **Direct F-group** (→ ecod_commons): Good quality + known Pfam family (~70%)
2. **Manual curation** (→ ecod_curation): Low quality or new Pfam families (~10-12%)
3. **.0 pseudo-group** (→ ecod_commons): Good quality + no Pfam hit (~18-20%)

**Key Technologies**:
- **Pfam v38**: Family-level classification
- **hmmscan**: Pfam hit detection (E ≤ 0.001)
- **ecod_rep**: Authoritative Pfam→F-group mapping

**Implementation Status**:
- ✅ Pfam database setup
- ✅ F-group lookup logic (ecod_rep.cluster)
- ✅ Quality thresholds defined
- 🔄 Routing script (route_and_load.py) - in progress
- ⏳ Pfam scanning integration
- ⏳ Bundle creation scripts

---


## References

- **Complete Workflow**: [PRODUCTION_WORKFLOW.md](PRODUCTION_WORKFLOW.md) - End-to-end data flow
- **Curation Workflow**: [ecod_curation_integration.md](ecod_curation_integration.md) - Manual review process
- **pyecod_mini API**: [PYECOD_MINI_API_SPEC.md](PYECOD_MINI_API_SPEC.md)
- **Pfam database**: ~/data/pfam/v38/Pfam-A.hmm
- **ECOD hierarchy**: ecod_rep schema on dione:45000/ecod_protein
- **Database**: ecod_commons, ecod_curation, pdb_update schemas
