# Production Pipeline: pdb_update → ecod_commons

This document describes the production workflow for routing pyecod_mini partition results from the `pdb_update` staging schema to the `ecod_commons` production schema.

## Overview

**Goal**: Automatically classify new PDB domains into ECOD, with separate tracks for:
- **Minor versions** (v291.1, v291.2, etc.): Auto-accession only (high confidence)
- **Major versions** (v292, v293, etc.): Curated results + new F-groups + hierarchical changes

**Bundle Frequency**: Twice yearly (every 6 months) aggregating ~26 weekly PDB releases

**Previous Run**: 114,146 domains classified as `mini_pyecod_v2_20250627` in ecod_commons

---

## Workflow Phases

### Phase 1: Partition Generation (pdb_update schema)

**Input**: Weekly PDB releases → BLAST + HHsearch evidence → domain_summary.xml

**Process**: pyecod_mini partitioning

**Output**: partition.xml files with domain assignments

**Storage**: `pdb_update.chain_partitions` table (not yet implemented)

**Schema** (proposed):
```sql
CREATE TABLE pdb_update.chain_partitions (
    pdb_id text NOT NULL,
    chain_id text NOT NULL,
    release_date date NOT NULL,
    partition_status text,  -- 'complete', 'failed', 'pending'
    partition_quality text, -- 'good', 'low_coverage', 'fragmentary', 'no_domains'
    coverage float,
    domain_count integer,
    classification_method text,  -- 'mini_pyecod_v2'
    algorithm_version text,      -- '2.0.0'
    PRIMARY KEY (pdb_id, chain_id, release_date)
);
```

---

### Phase 2: F-group Assignment via Pfam

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

### Phase 3: Routing Decision Logic

After partitioning + Pfam hmmscan, each domain follows one of three paths:

#### Path 1: Direct Auto-Accession (Minor Version)

**Criteria** (ALL must be true):
1. `partition_quality = 'good'` (coverage ≥80%)
2. Pfam hit with E-value ≤ 0.001
3. Pfam→F-group mapping exists in `ecod_rep.cluster`
4. Evidence supports single H-group (no conflicts)

**Action**: Assign to F-group, stage for minor version bundle

**Storage**: `ecod_commons.domains` with `classification_status = 'auto'`

**Example**:
```
Domain: 8abc_A_1 (residues 10-150)
Pfam hit: PF00562 (RNA-binding domain, E=1e-25)
ecod_rep lookup: e4753.10.4 (RNA-binding domain)
→ Auto-assign to F-group e4753.10.4
→ Include in next minor version (v291.1)
```

#### Path 2: Route to Curation (Major Version)

**Criteria** (ANY is true):
1. Pfam hit exists BUT no F-group mapping in `ecod_rep.cluster`
   - **Reason**: New F-group needed
   - **Action**: Flag for curator review, create new F-group in ecod_rep

2. `partition_quality = 'low_coverage'` or `'fragmentary'`
   - **Reason**: Uncertain domain boundaries
   - **Action**: Manual inspection of partition + evidence

3. Evidence from multiple conflicting H-groups
   - **Reason**: Possible domain fusion or chimera
   - **Action**: Curator determines correct classification

**Storage**: `ecod_curation` schema (for review)

**Output**: Curated results included in next major version (v292)

**Example**:
```
Domain: 9xyz_B_2 (residues 200-350)
Pfam hit: PF12345 (Hypothetical protein family, E=5e-10)
ecod_rep lookup: NULL (no F-group for PF12345)
→ Route to curation (new F-group needed)
→ Curator assigns to new F-group e5000.1.1
→ Include in next major version (v292)
```

#### Path 3: .0 Pseudo-group Assignment (Minor Version)

**Criteria**:
1. No Pfam hit (E-value > 0.001 or no alignments)
2. `partition_quality = 'good'` (coverage ≥80%)
3. Evidence supports single H-group

**Action**: Assign to H-group.0 pseudo-group

**Storage**: `ecod_commons.f_group_assignments` (NOT in ecod_rep)

**Pseudo-group naming**: `{X}.{H}.0` (e.g., `123.1.0`)

**Example**:
```
Domain: 7def_C_1 (residues 1-120)
Pfam hit: None
BLAST evidence: Multiple hits to H-group e123.1 (all E<0.001)
→ Assign to pseudo-group e123.1.0
→ Include in next minor version (v291.1)
```

**Note**: .0 pseudo-groups represent domains that:
- Are confidently domains (good partition quality)
- Belong to known H-groups (strong BLAST evidence)
- Lack Pfam family assignment (may be ECOD-specific or poorly characterized)

---

### Phase 4: Bundle Creation

#### Minor Version Bundle (v291.1, v291.2, etc.)

**Composition**: All domains from 6-month period that meet auto-accession criteria

**Includes**:
- Path 1: Direct F-group assignments (known Pfam families)
- Path 3: .0 pseudo-group assignments (no Pfam hit)

**Excludes**:
- Curated results (go to major version)
- Low quality partitions
- Domains needing new F-groups

**Version increment**: `v291 → v291.1 → v291.2 → ...`

**Timeline**: Released twice yearly (January, July)

**Database operations**:
1. INSERT domains into `ecod_commons.domains`
2. INSERT .0 assignments into `ecod_commons.f_group_assignments`
3. UPDATE `domain_version` field to track bundle (e.g., `mini_pyecod_v2_20260115`)
4. Mark chains in `pdb_update.chain_status` as `ecod_status = 'in_current_ecod'`

**SQL pattern**:
```sql
-- Insert auto-accession domains
INSERT INTO ecod_commons.domains
    (uid, ecod_domain_id, pdb_id, chain_id, f_id, t_id, h_id, x_id,
     classification_method, classification_status, domain_version)
SELECT
    gen_uid(),
    gen_domain_id(pdb_id, chain_id, domain_num),
    pdb_id, chain_id,
    f_group_id, t_group_id, h_group_id, x_group_id,
    'mini_pyecod_v2',
    'auto',
    'mini_pyecod_v2_20260115'
FROM pdb_update.chain_partitions cp
JOIN pdb_update.domain_assignments da USING (pdb_id, chain_id)
WHERE cp.partition_quality = 'good'
  AND da.assignment_type IN ('direct_fgroup', 'pseudo_fgroup')
  AND cp.release_date BETWEEN '2025-07-01' AND '2025-12-31';
```

#### Major Version Bundle (v292, v293, etc.)

**Composition**: Curated results + hierarchical changes + new F-groups

**Includes**:
- Path 2: Curated domain assignments
- New F-groups (added to ecod_rep.cluster)
- Hierarchical reorganizations (H-group splits, merges, etc.)
- Policy changes (coverage thresholds, evidence cutoffs)

**Version increment**: `v291 → v292 → v293 → ...`

**Timeline**: As needed (typically annually or when major curation effort completes)

**Process**:
1. Curators review flagged domains in ecod_curation schema
2. New F-groups added to ecod_rep.cluster with pfam_acc
3. Hierarchical changes applied to ecod_rep
4. Bundle created with both curated and auto domains
5. Website regenerated with new hierarchy

**Downstream impacts**:
- ECOD website rebuild (hierarchy visualizations)
- Distributable updates (XML, flat files)
- HMM database regeneration (for BLAST/HHsearch)
- Literature announcement (publications, release notes)

---

## Database Schemas

### pdb_update Schema (Staging)

**Purpose**: Temporary storage for new PDB releases and classification results

**Key tables**:
- `chain_status`: Track chains from weekly releases, clustering, ECOD status
- `chain_partitions`: Store partition results (quality, coverage)
- `domain_assignments`: Store domain ranges + F-group assignments
- `pfam_hits`: Store hmmscan results for each domain

### ecod_curation Schema (Review)

**Purpose**: Queue for manual curation

**Key tables**:
- `domains_pending`: Domains flagged for review
- `new_fgroups_proposed`: Pfam families needing new F-groups
- `curation_decisions`: Curator actions (approve, reject, reassign)

**Not yet implemented** - requires design

### ecod_commons Schema (Production)

**Purpose**: Live production data (includes .0 pseudo-groups)

**Key tables**:
- `domains`: All classified domains (auto + curated)
- `f_group_assignments`: F-group assignments including .0 pseudo-groups
- `domain_versions`: Track bundle metadata

**Fields for tracking**:
- `classification_method`: 'mini_pyecod_v2'
- `classification_status`: 'auto' | 'curated'
- `domain_version`: Bundle identifier (e.g., 'mini_pyecod_v2_20260115')

### ecod_rep Schema (Authoritative)

**Purpose**: Hierarchical policy (manual curation only)

**Key tables**:
- `cluster`: H-groups, T-groups, F-groups (with pfam_acc)
- `cluster_members`: Domain→cluster assignments

**Important**: NO automated changes (except new F-groups with approval)

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

## Implementation Roadmap

### Phase 1: Database Schema (pdb_update)
- [ ] Create `chain_partitions` table
- [ ] Create `domain_assignments` table
- [ ] Create `pfam_hits` table
- [ ] Add indexes for performance

### Phase 2: Pfam Integration
- [ ] Write `pfam_scanner.py` to run hmmscan on domain FASTAs
- [ ] Parse domain table output (--domtblout)
- [ ] Load results to `pdb_update.pfam_hits`
- [ ] Implement F-group lookup against `ecod_rep.cluster`

### Phase 3: Routing Logic
- [ ] Implement decision tree (auto vs. curation vs. .0)
- [ ] Generate reports: auto-eligible, needs-curation, no-pfam
- [ ] Populate `pdb_update.domain_assignments` with routing decisions

### Phase 4: Bundle Preparation
- [ ] Write bundle SQL scripts (minor version)
- [ ] Implement .0 pseudo-group generation
- [ ] Write validation queries (check for conflicts, duplicates)
- [ ] Dry-run bundle creation on test data

### Phase 5: ecod_curation Integration
- [ ] Design curation schema (tables + workflow)
- [ ] Build curation UI or CLI tools
- [ ] Implement major version bundle workflow

---

## Example Workflow: 6-Month Bundle (v291.1)

**Timeline**: July 2025 - December 2025 (26 weekly releases)

**Step 1**: Aggregate partition results
```sql
-- Count domains ready for auto-accession
SELECT
    COUNT(*) as total_domains,
    COUNT(*) FILTER (WHERE partition_quality = 'good') as good_quality,
    COUNT(*) FILTER (WHERE partition_quality != 'good') as needs_review
FROM pdb_update.chain_partitions
WHERE release_date BETWEEN '2025-07-01' AND '2025-12-31';
```

**Step 2**: Run Pfam hmmscan on all good-quality domains
```bash
# Generate domain FASTAs from partition.xml files
python scripts/extract_domain_sequences.py \
    --partitions /data/ecod/pdb_updates/batches/*/partitions/*.xml \
    --output domains_july_dec_2025.fasta

# Run hmmscan
hmmscan --cpu 32 -E 0.001 --domtblout domains_pfam_hits.tbl \
    ~/data/pfam/v38/Pfam-A.hmm \
    domains_july_dec_2025.fasta

# Load to database
python scripts/load_pfam_hits.py domains_pfam_hits.tbl
```

**Step 3**: Apply routing logic
```sql
-- Auto-accession: Known F-groups
UPDATE pdb_update.domain_assignments da
SET assignment_type = 'direct_fgroup',
    f_group_id = rc.id
FROM pdb_update.pfam_hits ph
JOIN ecod_rep.cluster rc ON rc.pfam_acc = ph.pfam_acc AND rc.type = 'F'
WHERE da.pdb_id = ph.pdb_id
  AND da.chain_id = ph.chain_id
  AND da.domain_num = ph.domain_num
  AND ph.evalue <= 0.001;

-- .0 pseudo-groups: No Pfam hit
UPDATE pdb_update.domain_assignments da
SET assignment_type = 'pseudo_fgroup',
    h_group_id = consensus_h_group(da.pdb_id, da.chain_id)
WHERE NOT EXISTS (
    SELECT 1 FROM pdb_update.pfam_hits ph
    WHERE ph.pdb_id = da.pdb_id
      AND ph.chain_id = da.chain_id
      AND ph.domain_num = da.domain_num
      AND ph.evalue <= 0.001
);

-- Curation: New Pfam families
INSERT INTO ecod_curation.domains_pending
SELECT da.*
FROM pdb_update.domain_assignments da
JOIN pdb_update.pfam_hits ph USING (pdb_id, chain_id, domain_num)
WHERE ph.evalue <= 0.001
  AND NOT EXISTS (
      SELECT 1 FROM ecod_rep.cluster rc
      WHERE rc.pfam_acc = ph.pfam_acc AND rc.type = 'F'
  );
```

**Step 4**: Generate bundle report
```
v291.1 Bundle Summary (2025-07-01 to 2025-12-31)
=================================================
PDB releases processed: 26 weeks
Total chains: 8,432
Total domains: 12,567

Auto-accession breakdown:
  Direct F-group: 9,234 (73.5%)
  .0 pseudo-group: 2,156 (17.2%)

Needs curation:
  New Pfam families: 456 (3.6%)
  Low coverage: 721 (5.7%)

Bundle size: 11,390 domains (90.7% auto)
```

**Step 5**: Load to ecod_commons
```bash
# Dry-run validation
python scripts/create_bundle.py \
    --start-date 2025-07-01 \
    --end-date 2025-12-31 \
    --version v291.1 \
    --dry-run

# Load bundle
python scripts/create_bundle.py \
    --start-date 2025-07-01 \
    --end-date 2025-12-31 \
    --version v291.1 \
    --execute
```

---

## References

- **Pfam**: https://www.ebi.ac.uk/interpro/entry/pfam/
- **HMMER**: http://hmmer.org/
- **ECOD**: https://prodata.swmed.edu/ecod/
- **pyecod_mini**: `/home/rschaeff/dev/pyecod_mini/`
- **Database**: `ecod_protein` on PostgreSQL server
