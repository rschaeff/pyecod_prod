# Q4 2025 / Q1 2026 ECOD PDB Assignment Summary

**Date**: 2026-01-21
**Batch ID**: `ecod_q4_2025_q1_2026`
**PDB Release Range**: October 2025 - January 2026

---

## Executive Summary

This batch processed **33,734 chains** from Q4 2025 and Q1 2026 PDB releases through the automated ECOD domain assignment pipeline. After clustering and classification, **36,109 domains** were assigned across **23,021 unique proteins**.

| Metric | Count |
|--------|-------|
| Input chains | 33,734 |
| Cluster representatives | 4,110 |
| Cluster members | 29,624 |
| **Total domains assigned** | **36,109** |
| Unique proteins with domains | 23,021 |

---

## Pipeline Funnel

### Stage 1: Chain Processing

```
33,734 chains from PDB releases
    ↓
4,110 cluster representatives (70% identity clustering)
    ↓
4,081 direct domains created
    ↓
32,028 propagated domains (to cluster members)
    ↓
36,109 total domains
```

### Stage 2: Pfam Classification

| Track | Description | Domains | % of Total |
|-------|-------------|---------|------------|
| Track 1 | Existing ECOD F-group | 30,764 | 80.4% |
| Track 2a | New single-Pfam F-group | 377 | 1.0% |
| Track 2b | Composite (multi-Pfam) | 4,055 | 10.6% |
| Track 3 | No Pfam hit | 3,043 | 8.0% |
| **Total** | | **38,239** | 100% |

*Note: Domain counts differ from final due to orphan deletion (2,136 domains removed).*

---

## Current Status in ECOD Commons

### Domain Version Breakdown

| Version | Domains | Description |
|---------|---------|-------------|
| `pyecod_prod_ecod_q4_2025_q1_2026` | 4,081 | Direct (representative) domains |
| `pyecod_prod_ecod_q4_2025_q1_2026_propagated` | 32,028 | Propagated to cluster members |
| **Total** | **36,109** | |

### F-group Assignment Status

| Status | Domains | % |
|--------|---------|---|
| Valid F-group (X.H.T.F format) | 35,922 | 99.5% |
| Pending curation (PDB reference) | 187 | 0.5% |
| **Total** | **36,109** | 100% |

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

### 1. PDB Reference Domains (187 domains)

These domains have PDB IDs instead of proper F-group assignments:

| PDB Reference | Domains | Notes |
|---------------|---------|-------|
| 7xm1 | 60 | Needs T-group assignment |
| 5gj4 | 40 | Needs T-group assignment |
| 8pqx | 36 | Needs T-group assignment |
| 8iog | 14 | Needs T-group assignment |
| 7lhe | 11 | Needs T-group assignment |
| Others (10) | 26 | Needs T-group assignment |

### 2. Track 2b Composite Domains (4,055 domains)

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

### 3. Track 3 No-Pfam Domains (3,043 domains)

Domains without Pfam hits - require structural comparison or manual assignment.

---

## Summary Statistics

### What Was Accomplished

| Task | Status | Details |
|------|--------|---------|
| Chain processing | ✅ Complete | 33,734 chains processed |
| Sequence clustering | ✅ Complete | 4,110 representatives at 70% identity |
| BLAST/HHsearch | ✅ Complete | Evidence generated for representatives |
| Domain partitioning | ✅ Complete | 4,081 direct domains |
| Cluster propagation | ✅ Complete | 32,028 propagated domains |
| Pfam scanning | ✅ Complete | All domains scanned |
| Track 1 assignment | ✅ Complete | 30,764 domains (80.4%) |
| Track 2a staging | ⚠️ Partial | 14/34 F-groups staged |
| Data cleanup | ✅ Complete | 2,136 orphan domains deleted |

### What Remains

| Task | Domains | Priority |
|------|---------|----------|
| Fix PDB reference domains | 187 | High |
| Create Track 2b composite F-groups | 4,055 | Medium |
| Handle Track 3 no-Pfam domains | 3,043 | Low |
| Complete Track 2a staging | 136 | Medium |

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
│   ├── domain_pfam_assignments.tsv
│   └── pfam_classification_report.json
└── slurm_logs/                   # Job logs
```

---

## Next Steps

1. **Immediate**: Fix 187 PDB reference domains by looking up correct T-groups
2. **Short-term**: Create F-groups for top Track 2b combinations (ribosomal, flagellar)
3. **Medium-term**: Complete Track 2a F-group staging (remaining 20 families)
4. **Long-term**: Handle Track 3 no-Pfam domains through structural comparison

---

*Generated by pyecod_prod auto-accession pipeline*
