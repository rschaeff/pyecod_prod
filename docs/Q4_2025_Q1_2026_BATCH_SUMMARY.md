# Q4 2025 / Q1 2026 ECOD PDB Assignment Summary

**Date**: 2026-01-23 (Updated)
**Previous Update**: 2026-01-22
**Batch ID**: `ecod_q4_2025_q1_2026`
**PDB Release Range**: October 2025 - January 2026

---

## Executive Summary

This batch processed **33,734 chains** from Q4 2025 and Q1 2026 PDB releases through the automated ECOD domain assignment pipeline. After clustering and classification, **35,920 domains** were assigned across **22,962 unique proteins**.

| Metric | Count |
|--------|-------|
| Input chains | 33,734 |
| Cluster representatives | 4,110 |
| Cluster members | 29,624 |
| **Total domains assigned** | **35,920** |
| Unique proteins with domains | 22,962 |

---

## Pipeline Funnel

### Stage 1: Chain Processing

```
33,734 chains from PDB releases
    ↓
4,110 cluster representatives (70% identity clustering)
    ↓
4,069 direct domains created
    ↓
31,851 propagated domains (to cluster members)
    ↓
35,920 total domains
```

### Stage 2: Pfam Classification

| Track | Description | Domains | % of Total |
|-------|-------------|---------|------------|
| Track 1 | Existing ECOD F-group | 30,764 | 80.4% |
| Track 2a | New single-Pfam F-group | 377 | 1.0% |
| Track 2b | Composite (multi-Pfam) | 4,055 | 10.6% |
| Track 3 | No Pfam hit | 3,043 | 8.0% |
| **Total** | | **38,239** | 100% |

*Note: Domain counts differ from final due to data cleanup (2,136 orphan domains + 187 PDB reference domains + 2 orphan propagated = 2,325 total removed).*

---

## Current Status in ECOD Commons

### Domain Version Breakdown

| Version | Domains | Description |
|---------|---------|-------------|
| `pyecod_prod_ecod_q4_2025_q1_2026` | 4,069 | Direct (representative) domains |
| `pyecod_prod_ecod_q4_2025_q1_2026_propagated` | 31,851 | Propagated to cluster members |
| **Total** | **35,920** | |

### F-group Assignment Status (Updated 2026-01-23)

| Status | Domains | % |
|--------|---------|---|
| Assigned to existing F-group via Pfam | 19,058 | 53.1% |
| T-group.0 placeholder (no Pfam match) | 16,856 | 46.9% |
| **Total** | **35,914** | 100% |

**Note:** Pfam v38.1 hmmscan was run on all 35,914 domain sequences (6 domains deleted due to invalid ranges). Of domains with Pfam hits, 19,058 were mapped to existing F-groups. See "Pfam Scanning Results" and "Composite Domain Analysis" sections below.

### Hierarchy Coverage

| Level | Unique Groups |
|-------|---------------|
| X-groups | 612 |
| H-groups | 814 |
| T-groups | 889 |
| F-groups | 904 |

---

## New F-groups Created

### Track 2a: Single-Pfam F-groups

- **34 unique Pfam families** identified without existing ECOD F-group
- **14 F-groups staged** for approval (241 domains)
- **20 F-groups blocked** - awaiting resolution of related composite domains

Top new Pfam families:
| Pfam | Name | Domains |
|------|------|---------|
| PF25391 | (new) | 86 |
| PF23169 | (new) | 38 |
| PF23618 | (new) | 36 |
| PF07655 | (new) | 17 |
| PF22542 | (new) | 13 |

### Track 2b: Composite F-groups (Pending Curation)

- **4,055 domains** with multiple Pfam hits
- **356 unique Pfam combinations** = potential new F-groups
- Dominated by ribosomal and flagellar proteins

| Pfams in Combo | F-groups Needed | Domains |
|----------------|-----------------|---------|
| 1 (repeat hits) | 118 | 1,299 |
| 2 Pfams | 172 | 2,071 |
| 3 Pfams | 36 | 451 |
| 4+ Pfams | 30 | 234 |
| **Total** | **356** | **4,055** |

---

## Domains Requiring Curation

### 1. Track 2b Composite Domains (4,055 domains)

Top combinations requiring F-group creation:

| Domains | Pfam Combination | Protein Type |
|---------|------------------|--------------|
| 179 | PF00118 | E-set Ig fold |
| 165 | PF00400 | WD40 repeat |
| 143 | PF00520+PF23317+PF25508 | Ion transport |
| 138 | PF04984+PF22671 | Flagellar |
| 132 | PF00460+PF22692 | Flagellar rod |
| 131 | PF00227+PF10584 | Proteasome |
| 93 | PF00163+PF01479 | Ribosomal S4 |

### 2. Track 3 No-Pfam Domains (3,043 domains)

Domains without Pfam hits - require structural comparison or manual assignment.

---

## Summary Statistics

### What Was Accomplished

| Task | Status | Details |
|------|--------|---------|
| Chain processing | ✅ Complete | 33,734 chains processed |
| Sequence clustering | ✅ Complete | 4,110 representatives at 70% identity |
| BLAST/HHsearch | ✅ Complete | Evidence generated for representatives |
| Domain partitioning | ✅ Complete | 4,069 direct domains |
| Cluster propagation | ✅ Complete | 31,851 propagated domains |
| **Pfam scanning** | ✅ Complete | 35,914 domain sequences scanned (Pfam v38.1) |
| **F-group assignment** | ✅ Partial | 19,058 domains (53.1%) assigned to existing F-groups |
| **Composite analysis** | ✅ Complete | 3,767 multi-Pfam domains classified |
| T-group assignment | ✅ Complete | All domains have valid T-groups |
| Data cleanup | ✅ Complete | 2,325 + 6 domains removed |

### What Remains

| Task | Domains | Priority |
|------|---------|----------|
| Handle overlapping Pfam hits | 2,286 | High |
| Review large-gap composites | 395 | Medium |
| Create Track 2a F-groups | 241 | Medium |
| Handle Track 3 no-Pfam domains | ~16,856 | Low |

---

## Files and Locations

```
/data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/
├── batch_manifest.yaml           # Processing state
├── fastas/                       # Input sequences
├── blast/                        # BLAST XML results
├── hhsearch/                     # HHsearch HHR results
├── summaries/                    # Domain evidence XML
├── partitions/                   # Partition XML (original)
├── partitions_repartitioned/     # Repartitioned (292 chains)
├── pfam/                         # Pfam hmmscan results
│   ├── all_domains.fasta         # 35,914 domain sequences
│   ├── chunks/                   # Split FASTA (36 chunks)
│   ├── hmmscan/                  # hmmscan output files
│   │   └── hmmscan_XXXX.domtblout
│   ├── pfam_hits_raw_clean.tsv   # 28,527 parsed Pfam hits
│   ├── true_composites.tsv       # 1,481 non-overlapping composites
│   ├── duo_composites.txt        # 290 duo combinations
│   ├── run_pfam_hmmscan.slurm    # SLURM job script
│   └── parse_pfam_hits.awk       # Parser script
└── slurm_logs/                   # Job logs
```

---

## F-group Assignment Gap (Resolved)

### Status: Option B Executed ✅

Pfam v38.1 hmmscan was run on all 35,914 domain sequences (comprehensive scan).

**Results:**
- 19,058 domains (53.1%) → Assigned to existing F-groups via Pfam mapping
- 16,856 domains (46.9%) → Remain T-group.0 (no Pfam hit or no F-group mapping)

### Why Some Domains Still Have T-group.0

1. **No Pfam hit (18,038 domains):** Domain sequence did not match any Pfam family above the gathering threshold
2. **Pfam hit but no F-group mapping (241 domains):** Pfam family exists but is not yet mapped to an ECOD F-group (Track 2a candidates)
3. **Multi-Pfam complications:** See "Composite Domain Analysis" section

### F-group Assignment Method

```
For each domain with Pfam hit:
  1. Look up pfam_acc in ecod_rep.cluster WHERE type='F'
  2. If single match AND parent matches domain T-group:
     → f_group_id = cluster.id (e.g., "11.1.1.5")
  3. If multiple matches: Select F-group whose parent = domain's T-group
  4. If no match: Keep f_group_id = T-group.0 (Track 2a candidate)
```

**Assignment recorded with:**
- `assignment_method = 'manual'`
- `notes = 'F-group assigned via Pfam v38.1 hmmscan'`

---

## Pfam v38.1 Scanning Results (2026-01-23)

### Execution Summary

Pfam hmmscan was executed on all domain sequences (Option B: Comprehensive scan).

| Metric | Count |
|--------|-------|
| Domain sequences extracted | 35,914 |
| Domains with invalid ranges (deleted) | 6 |
| Total Pfam domain hits | 25,476 |
| Unique domains with hits | 17,876 (49.8%) |
| Unique Pfam families matched | 1,617 |

### F-group Mapping Results

| Category | Domains | % |
|----------|---------|---|
| Mapped to existing F-group | 19,058 | 53.1% |
| No Pfam hit (Track 3) | 18,038 | 50.2% |
| Pfam hit but no F-group mapping | 241 | 0.7% |

**Files Generated:**
- `/data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/pfam/all_domains.fasta` - 35,914 sequences
- `/data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/pfam/hmmscan/*.domtblout` - 36 chunk results
- `/data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/pfam/pfam_hits_raw_clean.tsv` - 28,527 hits

---

## Composite Domain Analysis (2026-01-23)

### Overview

A detailed analysis was performed on domains with multiple Pfam hits to determine:
1. Whether hits are overlapping (same region) or sequential (different regions)
2. Whether sequential hits represent legitimate multi-domain architectures or partitioning errors

### Key Finding: Most "Composites" Are Overlapping Hits

| Classification | Domains | % | Interpretation |
|----------------|---------|---|----------------|
| **Overlapping hits** | 2,286 | 60.7% | Single domain matching related Pfam families |
| **True composites** (non-overlapping) | 1,481 | 39.3% | Potentially multi-domain or partitioning errors |
| **Total multi-Pfam domains** | 3,767 | 100% | |

### Overlapping Hits (2,286 domains) - NOT True Composites

These domains have multiple Pfam hits covering the **same region** (>30% overlap). This occurs because related Pfam families (e.g., immunoglobulin subtypes) match the same structural fold.

**Top overlapping combinations:**
| Count | Pfam Combination | Description |
|-------|------------------|-------------|
| 127 | C1-set + C2-set_2 | Immunoglobulin subtypes (same ~90 aa region) |
| 180 | ig + V-set | Generic Ig + V-set specific (same region) |
| 133 | Asp + TAXi_N | Aspartyl protease (TAXi_N is N-terminal lobe of Asp) |

**Recommendation:** Use best-scoring Pfam hit for F-group assignment, not "composite" classification.

### True Composites (1,481 domains) - Gap Analysis

For domains with non-overlapping sequential Pfam hits, the gap between hits was analyzed:

| Gap Range | Count | % | Interpretation |
|-----------|-------|---|----------------|
| 0 residues | 142 | 9.6% | Adjacent domains (legitimate) |
| 1-10 residues | 514 | 34.7% | Short linker (legitimate) |
| 11-30 residues | 143 | 9.7% | Normal linker (legitimate) |
| 31-50 residues | 267 | 18.0% | Long linker (review recommended) |
| 51-100 residues | 311 | 21.0% | **Suspicious** - potential error |
| >100 residues | 84 | 5.7% | **Likely partitioning error** |

### Potential Partitioning Errors (395 domains)

Domains with >50 residue gaps between Pfam hits may represent incorrectly merged domains that should have been split during partitioning.

**Largest gap cases:**
| Domain | Gap | Pfam A | Pfam B | Notes |
|--------|-----|--------|--------|-------|
| e9og9A1 | 236 aa | PF08767 | PF18784 | Mincle receptor |
| e9c4kP1 | 226 aa | PF03534 (SpvB) | PF12255 (TcdB_toxin) | Bacterial toxin |
| e9j84 series | 222 aa | PF25508 (TRPM2) | PF23317 (YVC1_C) | TRP ion channel |
| e9p3 series | 192 aa | PF25508 (TRPM2) | PF23317 (YVC1_C) | TRP ion channel |

**Note:** Some large-gap cases (e.g., e9c4kP1) have a third Pfam hit in the gap region, indicating complex multi-domain architecture rather than error. Manual review is recommended.

### Duo Composite Component Independence Analysis

For duo composites (exactly 2 different Pfam families), we checked whether each component exists independently as a solo F-group in ECOD:

| Category | Combinations | Domains | Interpretation |
|----------|--------------|---------|----------------|
| **Both exist as solo F-groups** | 274 (94.5%) | 2,347 | Domain fusions, not minimal units |
| One exists as solo F-group | 16 (5.5%) | 341 | One component is novel |
| Neither exists | 0 (0%) | 0 | - |

**Key insight:** 94.5% of duo composites are fusions of Pfam families that each appear independently in ECOD. These are NOT minimal composite units requiring new F-group definitions.

**Additional finding:** 88 duo combinations (627 domains) already have matching composite F-groups in ECOD (with comma-separated pfam_acc).

### Recommendations

1. **Overlapping hits (2,286 domains):** ✅ RESOLVED - Already assigned via best-scoring Pfam
2. **Small-gap composites (799 domains, ≤30 aa gap):** Accept as legitimate multi-domain architectures
3. **Medium-gap composites (267 domains, 31-50 aa gap):** Flag for manual review
4. **Large-gap composites (395 domains, >50 aa gap):** Investigate for potential re-partitioning

### Overlapping Hits Resolution (2026-01-23)

The 2,286 overlapping Pfam hit domains were analyzed and found to be **already resolved**:

| Category | Count | Status |
|----------|-------|--------|
| Mapped to F-group via best Pfam | 2,088 | ✅ 2,085 already assigned, 3 newly assigned |
| Unmapped - Novel Pfam (Track 2a) | ~95 | Awaiting F-group creation |
| Unmapped - T-group mismatch | ~103 | Requires investigation |

**Conclusion:** The initial F-group assignment strategy (single-best-Pfam) correctly handled overlapping hits. These domains were never true "composites" - they were single domains matching multiple related Pfam families.

### Files Generated

- `/data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/pfam/true_composites.tsv` - 1,481 true composite domains with gap analysis
- `/data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/pfam/duo_composites.txt` - 290 unique duo combinations
- `/data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026/pfam/overlapping_domains_best_pfam.tsv` - 2,286 overlapping domains with best Pfam

---

## Validation Summary (2026-01-23)

| Check | Result | Details |
|-------|--------|---------|
| Total domains | ✅ 35,914 | 4,063 direct + 31,851 propagated (6 deleted for invalid ranges) |
| Propagated → valid representative | ✅ Pass | All propagated domains reference valid direct domains |
| T-group validity | ✅ Pass | All T-groups exist in ecod_rep.cluster |
| F-group assignment | ✅ 53.1% | 19,061 domains mapped to existing F-groups |
| F-group pending | ⚠️ 46.9% | 16,853 domains still have T-group.0 placeholder |
| Pfam scanning | ✅ Complete | 35,914 sequences scanned against Pfam v38.1 |
| Orphan cleanup | ✅ Complete | Removed 2 orphan propagated + 6 invalid range domains |
| Composite analysis | ✅ Complete | 3,767 multi-Pfam domains analyzed for overlaps |
| Overlapping hits | ✅ Resolved | 2,286 domains - already assigned via best Pfam |

---

## Next Steps

### Completed ✅
1. ~~Extract domain sequences~~ → 35,914 sequences extracted
2. ~~Run Pfam hmmscan~~ → All sequences scanned against Pfam v38.1
3. ~~Map Pfam hits → F-groups~~ → 19,058 domains assigned to existing F-groups
4. ~~Analyze composite domains~~ → Overlap vs. true composite classification complete

### Pending Decisions

**~~Decision 1: Overlapping Pfam Hits (2,286 domains)~~** ✅ RESOLVED
- These were already assigned F-groups via best-scoring Pfam during initial assignment
- 198 remain unmapped (95 Track 2a, 103 T-group mismatch)

**Decision 2: True Composites with Small Gaps (799 domains, ≤30 aa)**
- Likely legitimate multi-domain architectures
- Option A: Accept as composites, create new composite F-groups
- Option B: Assign to dominant Pfam's F-group

**Decision 3: True Composites with Large Gaps (395 domains, >50 aa)**
- Potential partitioning errors
- Option A: Re-run partitioning with stricter parameters
- Option B: Manual review and correction
- Option C: Accept as legitimate complex architectures

**Decision 4: Track 2a Novel Pfams (~336 domains total)**
- 241 from single-Pfam hits + ~95 from overlapping unmapped
- Pfam hits without existing F-group in ECOD
- Option A: Create new F-groups for these Pfam families
- Option B: Wait for curator approval

**Decision 5: T-group Mismatch Domains (~103 domains)**
- Best Pfam has F-groups, but none match domain's T-group
- Option A: Investigate and correct T-group assignment
- Option B: Leave as T-group.0 for manual curation

**Decision 6: Track 3 No-Pfam Domains (~16,853 domains)**
- No Pfam hit above threshold
- Option A: Leave as T-group.0 pending structural analysis
- Option B: Lower Pfam threshold and re-scan
- Option C: Run structural comparison (Foldseek/DALI)

### Remaining Tasks

| Task | Domains Affected | Priority |
|------|------------------|----------|
| ~~Handle overlapping Pfam hits~~ | ~~2,286~~ | ~~High~~ ✅ |
| Review large-gap composites | 395 | Medium |
| Investigate T-group mismatches | 103 | Medium |
| Create Track 2a F-groups | ~336 | Medium |
| Handle Track 3 no-Pfam | ~16,853 | Low |

---

*Generated by pyecod_prod auto-accession pipeline*
*Last updated: 2026-01-23*
