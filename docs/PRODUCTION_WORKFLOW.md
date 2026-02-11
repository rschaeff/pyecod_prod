# ECOD Production Workflow: Complete Data Flow

**Date**: 2025-10-23
**Status**: PRODUCTION STANDARD

This document defines the canonical workflow for processing PDB releases into ECOD classifications.

---

## Architecture Principles

### 1. Separation of Concerns

**pdb_update schema**: Release tracking and coordination
- Which chains from which releases
- Clustering information
- ECOD status lookup
- **NOT for partition results or domain data**

**Filesystem**: Working data
- partition.xml files (domain boundaries, coverage)
- pfam_hits.tbl (Pfam family assignments)
- Evidence files (BLAST XMLs, HHR files)

**ecod_commons schema**: Production classifications
- Auto-assigned domains (high quality)
- .0 pseudo-groups (no Pfam hit)
- Curated domains (after manual review)

**ecod_curation schema**: Manual review queue
- Low quality partitions
- New Pfam families (no F-group mapping)
- Conflicting evidence
- **ONLY for domains requiring human review**

### 2. Two-Track System

**Track 1: Auto-Accession** (→ ecod_commons)
- High quality partitions (coverage ≥80%)
- Known Pfam families OR strong H-group consensus
- No manual review needed
- Included in minor version bundles (v291.1, v291.2, etc.)

**Track 2: Manual Curation** (→ ecod_curation → ecod_commons)
- Low quality partitions
- New Pfam families needing F-group creation
- Conflicting evidence across H-groups
- Included in major version bundles (v292, v293, etc.)

---

## Complete Workflow

### Phase 1: Release Tracking (pdb_update schema)

**Purpose**: Record which chains exist and need classification

**Process**:
```bash
python scripts/load_pdb_release.py \
    --status-file /usr2/pdb/data/status/20251005/added.pdb \
    --release-date 2025-10-05
```

**Database updates**:
```sql
-- Insert new release
INSERT INTO pdb_update.weekly_release (release_date, entries_count)
VALUES ('2025-10-05', 342);

-- Insert chain records
INSERT INTO pdb_update.chain_status
    (pdb_id, chain_id, release_date, sequence_length, can_classify)
SELECT ...;

-- Mark chains already in ECOD
UPDATE pdb_update.chain_status
SET ecod_status = 'in_current_ecod'
WHERE (pdb_id, chain_id) IN (SELECT ... FROM ecod_commons.domains);
```

**Output**:
- Chains marked as `ecod_status = 'not_in_ecod'` need classification
- Chains marked as `ecod_status = 'in_current_ecod'` skip processing

---

### Phase 2: Optional Clustering (pdb_update schema)

**Purpose**: Reduce redundancy for large batches

**When to use**:
- Backfills (hundreds/thousands of chains)
- Homology-reduction datasets

**When to skip**:
- Weekly releases (typically <500 chains)
- After clustering representatives

**Process**:
```bash
# Run clustering
python scripts/run_clustering.py \
    fastas/all_chains.fasta \
    clustering/mmseqs_70pct \
    --method mmseqs2 \
    --threshold 0.70

# Load to database
python scripts/load_clustering.py \
    --cluster-file clustering/mmseqs_70pct_cluster.tsv \
    --release-date 2025-10-05
```

**Database updates**:
```sql
UPDATE pdb_update.chain_status
SET is_representative = TRUE,
    cluster_id = ...
WHERE ...;
```

**Result**: Only process cluster representatives (BLAST target reduction)

---

### Phase 3: Evidence Generation (filesystem)

**Purpose**: Generate BLAST/HHsearch evidence for classification

**3a. BLAST Workflow**:
```bash
# Submit BLAST jobs (chain + domain)
cd /data/ecod/pdb_updates/batches/ecod_weekly_20251005
python -c "
from pyecod_prod.batch.weekly_batch import WeeklyBatch
batch = WeeklyBatch(release_date='2025-10-05', ...)
batch.run_blast(partition='96GB', array_limit=500)
"
```

**Output**: `blast/chain_blast/*.xml` and `blast/domain_blast/*.xml`

**3b. Coverage Analysis**:
```bash
# Calculate BLAST coverage, identify low-coverage chains
python scripts/analyze_blast_coverage.py \
    --blast-dir blast/ \
    --output hhsearch_targets.txt
```

**Output**: List of chains needing HHsearch (<90% BLAST coverage)

**3c. HHsearch Workflow** (if needed):
```bash
# Submit HHsearch for low-coverage chains
sbatch submit_hhsearch_batch*.sh
```

**Output**: `hhsearch/*.hhr` files

**3d. Summary Generation**:
```bash
# Combine BLAST + HHsearch evidence
python scripts/generate_summaries.py \
    --blast-dir blast/ \
    --hhsearch-dir hhsearch/ \
    --output summaries/
```

**Output**: `summaries/*.summary.xml` (one per chain, domain_summary.xml format)

---

### Phase 4: Domain Partitioning (filesystem)

**Purpose**: Identify domain boundaries

**Process**:
```bash
# Run pyecod_mini partitioning
python scripts/run_partitioning.py \
    --summaries summaries/ \
    --output partitions/
```

**Output**: `partitions/*.partition.xml`

**Example partition.xml**:
```xml
<partition pdb_id="8abc" chain_id="A" coverage="0.95">
  <domain number="1" start="10" end="150" range="10-150">
    <assignment t_group="123" h_group="123.1" f_group="123.1.4"/>
    <evidence type="blast_domain" ecod_uid="e1234A1" evalue="1e-50"/>
  </domain>
</partition>
```

---

### Phase 5: Pfam Scanning (filesystem)

**Purpose**: Assign Pfam families to domains for F-group lookup

**5a. Extract Domain Sequences**:
```bash
python scripts/extract_domain_fastas.py \
    --partitions partitions/*.xml \
    --output domains.fasta
```

**5b. Run hmmscan**:
```bash
hmmscan --cpu 32 -E 0.001 --domtblout pfam_hits.tbl \
    ~/data/pfam/v38/Pfam-A.hmm \
    domains.fasta
```

**Output**: `pfam_hits.tbl` (domain-level Pfam hits)

**Example pfam_hits.tbl**:
```
# target name        accession  query name           evalue  score
RNA_bind             PF00562    8abc_A_1             1.2e-25 85.3
```

---

### Phase 6: Routing & Loading (filesystem → ecod_commons/ecod_curation)

**Purpose**: Apply routing logic and load to appropriate schema

**6a. Routing Script**:
```bash
python scripts/route_and_load.py \
    --partitions partitions/ \
    --pfam-hits pfam_hits.tbl \
    --release-date 2025-10-05 \
    --dry-run  # Preview decisions

# After review:
python scripts/route_and_load.py \
    --partitions partitions/ \
    --pfam-hits pfam_hits.tbl \
    --release-date 2025-10-05 \
    --execute
```

**6b. Routing Logic**:

```python
def route_domain(partition, domain, pfam_hits):
    """
    Route a single domain to ecod_commons or ecod_curation.

    Returns: ('ecod_commons', details) OR ('ecod_curation', reason)
    """
    quality = partition.quality  # 'good' if coverage ≥0.80

    # Get top Pfam hit for this domain
    pfam_hit = pfam_hits.get_top_hit(domain.number, evalue_cutoff=0.001)

    # TRACK 1: Direct auto-accession (known Pfam family)
    if quality == 'good' and pfam_hit is not None:
        fgroup = lookup_fgroup_from_pfam(pfam_hit.pfam_acc)

        if fgroup is not None:
            return ('ecod_commons', {
                'assignment_type': 'direct_fgroup',
                'f_group_id': fgroup.id,
                'classification_status': 'auto',
                'pfam_acc': pfam_hit.pfam_acc,
                'pfam_evalue': pfam_hit.evalue
            })
        else:
            # Pfam hit but no F-group mapping → needs curation
            return ('ecod_curation', {
                'reason': 'new_pfam_family',
                'pfam_acc': pfam_hit.pfam_acc,
                'priority': 5  # Medium priority
            })

    # TRACK 2: .0 pseudo-group (no Pfam hit, good quality)
    if quality == 'good' and pfam_hit is None:
        h_group = get_consensus_hgroup(domain.evidence)

        if h_group is not None and h_group.confidence >= 0.7:
            return ('ecod_commons', {
                'assignment_type': 'pseudo_fgroup',
                'h_group_id': h_group.id,
                'f_group_name': f"{h_group.name}.0",
                'classification_status': 'auto'
            })

    # TRACK 3: Needs curation (low quality or conflicts)
    reasons = []
    priority = 1

    if quality in ('low_coverage', 'fragmentary'):
        reasons.append(f'quality={quality}')
        priority = 8 if quality == 'fragmentary' else 5

    if has_conflicting_hgroups(domain.evidence):
        reasons.append('conflicting_hgroups')
        priority = max(priority, 7)

    if quality == 'good' and pfam_hit is None and h_group is None:
        reasons.append('insufficient_evidence')
        priority = 10  # High priority for investigation

    return ('ecod_curation', {
        'reason': ', '.join(reasons),
        'priority': priority
    })
```

**6c. Loading to ecod_commons**:

For domains routed to auto-accession:

```sql
-- Insert protein record
INSERT INTO ecod_commons.proteins
    (pdb_id, chain_id, release_date, sequence, ...)
VALUES (...);

-- Insert domain record
INSERT INTO ecod_commons.domains
    (uid, ecod_domain_id, protein_id,
     pdb_id, chain_id, range,
     f_id, t_id, h_id, x_id,
     classification_method, classification_status,
     domain_version)
VALUES (
    gen_uid(),  -- Auto-generate UID
    '8abc_A_1',
    protein_id,
    '8abc', 'A', '10-150',
    123.1.4,  -- F-group from Pfam lookup
    123, 123.1, 123,
    'mini_pyecod_v2',
    'auto',
    NULL  -- Assigned during bundle creation
);

-- For .0 pseudo-groups
INSERT INTO ecod_commons.f_group_assignments
    (domain_id, f_group_name, assignment_type)
VALUES (domain_id, '123.1.0', 'pseudo');
```

**6d. Loading to ecod_curation**:

For domains needing manual review:

```sql
-- Insert protein (if not exists)
INSERT INTO ecod_curation.protein
    (source_id, pdb_id, chain_id, release_date, sequence, ...)
VALUES (...)
ON CONFLICT (source_id) DO NOTHING;

-- Insert domain assignment
INSERT INTO ecod_curation.domain_assignment
    (protein_id, domain_number, start_pos, end_pos,
     assigned_t_group, assigned_h_group, assigned_f_group,
     confidence, source)
VALUES (...);

-- Insert evidence
INSERT INTO ecod_curation.domain_evidence (...)
VALUES (...);

-- Add to curation queue
INSERT INTO ecod_curation.curation_queue
    (protein_id, priority, priority_reason)
VALUES (protein_id, 7, 'conflicting_hgroups');
```

**Output Summary**:
```
Routing Summary for 2025-10-05
===============================
Total domains: 1,234

Auto-accession (→ ecod_commons):
  Direct F-group: 856 (69.4%)
  .0 pseudo-group: 234 (19.0%)
  Subtotal: 1,090 (88.3%)

Needs curation (→ ecod_curation):
  New Pfam families: 45 (3.6%)
  Low quality: 67 (5.4%)
  Conflicting evidence: 32 (2.6%)
  Subtotal: 144 (11.7%)
```

---

### Phase 7: Update Tracking (pdb_update schema)

**Purpose**: Mark chains as processed

```sql
-- Update chains loaded to ecod_commons
UPDATE pdb_update.chain_status
SET ecod_status = 'in_current_ecod',
    last_updated = NOW()
WHERE (pdb_id, chain_id) IN (
    SELECT pdb_id, chain_id
    FROM ecod_commons.domains
    WHERE classification_status = 'auto'
    AND domain_version IS NULL  -- Not yet bundled
);

-- Update chains in curation queue
UPDATE pdb_update.chain_status
SET ecod_status = 'in_curation',
    last_updated = NOW()
WHERE (pdb_id, chain_id) IN (
    SELECT pdb_id, chain_id
    FROM ecod_curation.protein
);
```

---

### Phase 8: Manual Curation (ecod_curation schema)

**Purpose**: Human review of flagged domains

**Process**:
1. Curator accesses pyecod_vis interface
2. Reviews domain boundaries and evidence
3. Validates/modifies F-group assignments
4. Creates new F-groups in ecod_rep if needed
5. Marks domain as "ready for accession"

**Not covered in this document** - see pyecod_vis documentation

---

### Phase 9: Bundle Creation (ecod_commons schema)

**Purpose**: Aggregate classifications for versioned release

**9a. Minor Version Bundle** (every 6 months):

```bash
python scripts/create_bundle.py \
    --start-date 2025-07-01 \
    --end-date 2025-12-31 \
    --version v291.1 \
    --type minor \
    --dry-run
```

**What it does**:
1. Query all auto-assigned domains from date range
2. Assign bundle version to `domain_version` field
3. Generate distributable files (XML, flat files)
4. Update ECOD website data

**Includes**:
- Direct F-group assignments (Track 1)
- .0 pseudo-groups (Track 2)

**Excludes**:
- Domains still in ecod_curation
- Curated results (go to major version)

**9b. Major Version Bundle** (annually or as needed):

```bash
python scripts/create_bundle.py \
    --version v292 \
    --type major \
    --include-curated
```

**What it does**:
1. Query curated domains marked "ready for accession"
2. Accession from ecod_curation → ecod_commons
3. Include new F-groups added to ecod_rep
4. Apply any hierarchical changes
5. Regenerate HMM databases
6. Update ECOD website with new hierarchy

**Includes**:
- All auto-assigned domains since last major version
- Curated domain assignments
- New F-groups
- Hierarchical reorganizations

---

## Database Schemas

### pdb_update Schema (Tracking)

**Tables**:
- `weekly_release` - Release metadata
- `chain_status` - Chain tracking, clustering, ECOD status
- `clustering_run` - Clustering metadata
- `sequence` - Protein sequences (for clustering)

**Purpose**: Answer coordination questions
- "Which chains from 2025-10-05 need classification?"
- "Which chains are cluster representatives?"
- "Has this chain been processed?"

### ecod_commons Schema (Production)

**Tables**:
- `proteins` - Protein metadata
- `domains` - All classified domains (auto + curated)
- `f_group_assignments` - F-group links (including .0 pseudo)
- `domain_versions` - Bundle metadata

**Purpose**: Live production ECOD data

**Key fields**:
- `classification_method`: 'mini_pyecod_v2'
- `classification_status`: 'auto' | 'curated'
- `domain_version`: 'v291.1_20260115' | NULL (unbundled)

### ecod_curation Schema (Review Queue)

**Tables**:
- `protein` - Proteins needing review
- `domain_assignment` - Domain boundaries and assignments
- `domain_evidence` - BLAST/HHsearch evidence
- `curation_queue` - Prioritized review queue
- `curation_session` - Curator activity tracking

**Purpose**: Manual review workflow
- Only receives domains that need human judgment
- Interfaces with pyecod_vis for visualization
- After approval, domains accession to ecod_commons

### ecod_rep Schema (Hierarchical Policy)

**Tables**:
- `cluster` - T/H/X/F-groups with Pfam mappings
- `cluster_members` - Domain→cluster assignments

**Purpose**: Authoritative ECOD hierarchy
- **Manual curation only**
- No automated changes (except new F-groups with approval)
- Source of truth for Pfam→F-group mappings

---

## Implementation Status

### ✅ Implemented
- Phase 1: Release tracking (pdb_update)
- Phase 2: Clustering (mmseqs2/CD-HIT)
- Phase 3: Evidence generation (BLAST + HHsearch)
- Phase 4: Partitioning (pyecod_mini integration)
- Phase 7: Status tracking updates

### 🔄 In Progress
- Phase 6: Routing script (route_and_load.py)
- Phase 9: Bundle creation scripts

### ⏳ Not Started
- Phase 5: Pfam scanning integration
- Phase 8: Curation interface (in pyecod_vis repo)

---

## References

- **pyecod_mini API**: [PYECOD_MINI_API_SPEC.md](PYECOD_MINI_API_SPEC.md)
- **Backfill workflow**: [BACKFILL_STATUS_REPORT.md](BACKFILL_STATUS_REPORT.md)
- **HHsearch details**: [HHSEARCH_WORKFLOW.md](HHSEARCH_WORKFLOW.md)
- **Database schemas**: Contact DBA for latest DDL
- **Pfam database**: ~/data/pfam/v38/Pfam-A.hmm
- **ECOD hierarchy**: ecod_rep schema on dione:45000/ecod_protein
