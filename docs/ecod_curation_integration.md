# ecod_curation Integration: Manual Review Workflow

**Date**: 2025-10-23
**Status**: DESIGN SPECIFICATION
**Database**: ecod_curation schema deployed on dione:45000/ecod_protein

**See Also**: [PRODUCTION_WORKFLOW.md](PRODUCTION_WORKFLOW.md) for complete data flow

## Overview

The `ecod_curation` schema is a **manual review queue** for domains that require human judgment.

**IMPORTANT**: ecod_curation receives only ~10-12% of domains:
- Low quality partitions (coverage <80%)
- New Pfam families (no F-group mapping in ecod_rep)
- Conflicting evidence across H-groups

**High-quality auto-assignments (~88-90%)** go directly to ecod_commons and **bypass** ecod_curation entirely.

## Role in Production Pipeline

### ecod_curation is NOT:
- ❌ A staging area for all partitioning results
- ❌ A temporary holding area before ecod_commons
- ❌ A database copy of filesystem partition.xml files

### ecod_curation IS:
- ✅ A review queue for domains needing manual judgment
- ✅ An interface point for pyecod_vis curation UI
- ✅ A workspace for creating new F-groups
- ✅ A tracking system for curator decisions

## Data Flow

```
partition.xml + pfam_hits.tbl
         ↓
    Routing Logic (route_and_load.py)
         ↓
    ┌────┴────┐
    ↓         ↓
ecod_commons  ecod_curation
(~90%)        (~10%)
              ↓
         Manual Review (pyecod_vis)
              ↓
         Accession Script
              ↓
         ecod_commons
```

## Code Components

### 1. Curation Loader Module

**File**: `src/pyecod_prod/database/curation_loader.py`

**Purpose**: Load domains flagged for manual review to ecod_curation

**Called by**: Routing script (route_and_load.py) for domains needing curation

```python
"""
Load partition results into ecod_curation schema for manual curation.
"""

import psycopg2
from datetime import date
from typing import List, Optional
from pyecod_mini import PartitionResult, Evidence

def load_partition_to_curation(
    pdb_id: str,
    chain_id: str,
    release_date: date,
    sequence: str,
    partition_result: PartitionResult,
    processing_version: str = 'pyecod_prod_v1.0'
) -> int:
    """
    Load a protein's partition results into ecod_curation schema.

    Args:
        pdb_id: PDB identifier (e.g., '8abc')
        chain_id: Chain identifier (e.g., 'A')
        release_date: PDB weekly release date
        sequence: Protein sequence
        partition_result: Results from pyecod_mini partitioning
        processing_version: Version string for provenance

    Returns:
        protein_id: ID of the created protein record

    Example:
        protein_id = load_partition_to_curation(
            pdb_id='8abc',
            chain_id='A',
            release_date=date(2025, 1, 20),
            sequence=seq,
            partition_result=result
        )
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 1. Insert protein
        cursor.execute("""
            INSERT INTO ecod_curation.protein
            (source_id, pdb_id, chain_id, release_date,
             sequence, sequence_length, sequence_md5,
             processed_at, processing_version,
             partition_coverage, domain_count, partition_quality,
             can_curate, cannot_curate_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            f"{pdb_id}_{chain_id}",
            pdb_id,
            chain_id,
            release_date,
            sequence,
            len(sequence),
            hashlib.md5(sequence.encode()).hexdigest(),
            processing_version,
            partition_result.coverage,
            len(partition_result.domains),
            classify_partition_quality(partition_result),
            can_curate(sequence, partition_result),
            get_cannot_curate_reason(sequence, partition_result)
        ))

        protein_id = cursor.fetchone()[0]

        # 2. Insert domain assignments
        for i, domain in enumerate(partition_result.domains, 1):
            cursor.execute("""
                INSERT INTO ecod_curation.domain_assignment
                (protein_id, domain_number, start_pos, end_pos, residue_range,
                 assigned_t_group, assigned_h_group, assigned_x_group, assigned_f_group,
                 best_match_ecod_uid, assignment_method, classification_level,
                 confidence, source, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                protein_id,
                i,
                domain.start,
                domain.end,
                domain.range_string,
                domain.t_group,
                domain.h_group,
                domain.x_group,
                domain.f_group,  # May be NULL if only T-group assignment
                domain.best_match_ecod_uid,
                domain.assignment_method,  # 'blast', 'hhsearch', 'inheritance'
                domain.classification_level,  # 'f_group_specific', 't_group_only', etc.
                domain.confidence,
                'automated',
                processing_version
            ))

            domain_id = cursor.fetchone()[0]

            # 3. Insert evidence for this domain
            for evidence in domain.evidence:
                cursor.execute("""
                    INSERT INTO ecod_curation.domain_evidence
                    (domain_id, evidence_type,
                     hit_ecod_domain_id, hit_ecod_uid, hit_pdb_id, hit_chain_id,
                     evalue, score, identity, similarity,
                     query_coverage, hit_coverage,
                     query_range, hit_range,
                     ref_t_group, ref_h_group, ref_x_group, ref_f_group,
                     source_file)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    domain_id,
                    evidence.type,  # 'blast_chain', 'blast_domain', 'hhsearch'
                    evidence.hit_ecod_domain_id,
                    evidence.hit_ecod_uid,
                    evidence.hit_pdb_id,
                    evidence.hit_chain_id,
                    evidence.evalue,
                    evidence.score,
                    evidence.identity,
                    evidence.similarity,
                    evidence.query_coverage,
                    evidence.hit_coverage,
                    evidence.query_range,
                    evidence.hit_range,
                    evidence.ref_t_group,
                    evidence.ref_h_group,
                    evidence.ref_x_group,
                    evidence.ref_f_group,
                    evidence.source_file  # Relative path to BLAST XML or HHR
                ))

        # 4. Optionally add to curation queue
        should_queue, reason = should_queue_for_curation(partition_result)
        if should_queue:
            priority = calculate_queue_priority(partition_result)

            cursor.execute("""
                INSERT INTO ecod_curation.curation_queue
                (protein_id, priority, priority_reason)
                VALUES (%s, %s, %s)
            """, (protein_id, priority, reason))

        conn.commit()
        return protein_id

    except Exception as e:
        conn.rollback()
        raise Exception(f"Failed to load {pdb_id}_{chain_id} to ecod_curation: {e}")

    finally:
        cursor.close()
        conn.close()


def classify_partition_quality(result: PartitionResult) -> str:
    """
    Classify partition quality based on coverage and confidence.

    Returns: 'good', 'low_coverage', 'fragmentary', or 'failed'
    """
    if result.coverage >= 0.9 and min(d.confidence for d in result.domains) >= 0.8:
        return 'good'
    elif result.coverage < 0.5:
        return 'fragmentary'
    elif result.coverage < 0.8:
        return 'low_coverage'
    else:
        return 'good'


def can_curate(sequence: str, result: PartitionResult) -> bool:
    """
    Determine if protein is suitable for curation.

    Returns False for peptides, nucleic acids, etc.
    """
    # Too short (peptide)
    if len(sequence) < 50:
        return False

    # Check for nucleic acid (simple heuristic)
    nucleic_chars = sum(1 for c in sequence.upper() if c in 'ATCGUN')
    if nucleic_chars / len(sequence) > 0.5:
        return False

    return True


def get_cannot_curate_reason(sequence: str, result: PartitionResult) -> Optional[str]:
    """Get reason why protein cannot be curated, if any."""
    if len(sequence) < 50:
        return 'too_short'

    nucleic_chars = sum(1 for c in sequence.upper() if c in 'ATCGUN')
    if nucleic_chars / len(sequence) > 0.5:
        return 'nucleic_acid'

    return None


def should_queue_for_curation(result: PartitionResult) -> tuple[bool, str]:
    """
    Decide if protein should be added to curation queue.

    Returns: (should_queue, reason)

    Heuristics:
    - Low confidence domains → needs review
    - Low coverage → needs review
    - Novel architecture → needs review
    - High confidence + good coverage → auto-accept (skip queue)
    """
    min_confidence = min(d.confidence for d in result.domains)

    # Low confidence
    if min_confidence < 0.7:
        return (True, 'low_confidence')

    # Low coverage
    if result.coverage < 0.8:
        return (True, 'low_coverage')

    # Check for novel architecture (no f-group assigned)
    has_unassigned = any(d.f_group is None for d in result.domains)
    if has_unassigned:
        return (True, 'incomplete_classification')

    # Conflicting evidence (multiple strong hits with different classifications)
    # TODO: Implement this check

    # High quality - can auto-accept
    return (False, 'auto_accepted')


def calculate_queue_priority(result: PartitionResult) -> int:
    """
    Calculate priority for curation queue.

    Higher number = higher priority

    Priority scale:
    10 = Very low confidence or major issues
    5  = Medium confidence or partial classification
    1  = Minor issues or borderline cases
    """
    min_confidence = min(d.confidence for d in result.domains)

    if min_confidence < 0.5:
        return 10  # Very urgent

    if result.coverage < 0.6:
        return 8  # High priority

    if min_confidence < 0.7:
        return 5  # Medium priority

    if result.coverage < 0.8:
        return 3  # Lower priority

    return 1  # Low priority
```

### 2. Routing Integration

**File**: `scripts/route_and_load.py`

**Purpose**: Route domains based on quality + Pfam hits

```python
from pyecod_prod.database.curation_loader import load_partition_to_curation

def route_and_load_batch(batch_dir, release_date):
    """
    Route partition results to ecod_commons or ecod_curation.

    Only domains needing manual review are loaded to ecod_curation.
    """
    partitions = parse_partitions(f"{batch_dir}/partitions/*.xml")
    pfam_hits = parse_pfam_hits(f"{batch_dir}/pfam_hits.tbl")

    stats = {'ecod_commons': 0, 'ecod_curation': 0}

    for partition in partitions:
        for domain in partition.domains:
            destination, details = route_domain(partition, domain, pfam_hits)

            if destination == 'ecod_commons':
                # Direct load to production (auto-assignment)
                load_to_ecod_commons(partition, domain, details)
                stats['ecod_commons'] += 1

            elif destination == 'ecod_curation':
                # Load to curation queue (manual review)
                load_partition_to_curation(
                    pdb_id=partition.pdb_id,
                    chain_id=partition.chain_id,
                    release_date=release_date,
                    sequence=partition.sequence,
                    partition_result=partition,
                    processing_version='pyecod_prod_v1.0'
                )
                stats['ecod_curation'] += 1

    print(f"Routed {stats['ecod_commons']} to ecod_commons (auto)")
    print(f"Routed {stats['ecod_curation']} to ecod_curation (manual)")
```

### 3. Accession Script

Create: `scripts/accession.py`

```python
"""
Accession script: Move curated proteins from ecod_curation → ecod_commons

Usage:
    python -m pyecod_prod.scripts.accession batch --name weekly_20250120
    python -m pyecod_prod.scripts.accession validate --protein-id 12345
    python -m pyecod_prod.scripts.accession cleanup --older-than 30days
"""

import click
from rich.console import Console
from rich.table import Table
from datetime import datetime, timedelta

@click.group()
def accession():
    """Accession commands for moving curated proteins to ecod_commons"""
    pass

@accession.command()
@click.option('--name', required=True, help='Batch name (e.g., weekly_20250120)')
@click.option('--dry-run', is_flag=True, help='Show what would be done')
def batch(name, dry_run):
    """
    Accession a batch of curated proteins from ecod_curation → ecod_commons

    Workflow:
    1. Query ecod_curation.ready_for_accession
    2. Validate all domains have f-groups
    3. Assign ECOD UIDs and domain IDs
    4. Create records in ecod_commons.proteins
    5. Create records in ecod_commons.domains
    6. Create records in ecod_commons.f_group_assignments
    7. Mark as accessioned in ecod_curation
    """
    console = Console()

    # Get proteins ready for accession
    ready = db.query("SELECT * FROM ecod_curation.ready_for_accession")

    console.print(f"[bold]Found {len(ready)} proteins ready for accession[/bold]")

    if len(ready) == 0:
        console.print("[yellow]No proteins ready. Exiting.[/yellow]")
        return

    # Show table
    table = Table(title="Proteins Ready for Accession")
    table.add_column("Source ID")
    table.add_column("Curator")
    table.add_column("Domains")
    table.add_column("With F-Group")

    for protein in ready:
        table.add_row(
            protein.source_id,
            protein.curator_name,
            str(protein.domain_count),
            str(protein.domains_with_f_group)
        )

    console.print(table)

    if dry_run:
        console.print("[yellow]Dry run - no changes made[/yellow]")
        return

    if not click.confirm(f"Accession {len(ready)} proteins?"):
        return

    # Process each protein
    for protein in ready:
        try:
            accession_protein(protein, batch_name=name)
            console.print(f"[green]✓[/green] {protein.source_id}")
        except Exception as e:
            console.print(f"[red]✗[/red] {protein.source_id}: {e}")

    console.print(f"[bold green]Accessioned {len(ready)} proteins to ecod_commons[/bold green]")

@accession.command()
@click.option('--protein-id', type=int, required=True)
def validate(protein_id):
    """Validate a protein is ready for accession"""
    # Check all domains have f-groups
    # Check f-groups exist in ecod_rep
    # Check no duplicate boundaries
    # etc.
    pass

@accession.command()
@click.option('--older-than', default='30days')
def cleanup(older_than):
    """Clean up old accessioned records from ecod_curation"""
    # Delete proteins accessioned > N days ago
    pass

def accession_protein(protein, batch_name: str):
    """
    Accession a single protein to ecod_commons.

    1. Create ecod_commons.proteins record
    2. Create ecod_commons.domains records (assign UIDs)
    3. Create ecod_commons.f_group_assignments records
    4. Mark as accessioned in ecod_curation
    """
    # TODO: Implement
    pass

if __name__ == '__main__':
    accession()
```

## Testing

1. **Run small test batch** (10 proteins)
   ```bash
   python scripts/run_small_test.py --release-date 2025-01-20 --limit 10
   ```

2. **Check ecod_curation**
   ```sql
   SELECT COUNT(*) FROM ecod_curation.protein;
   SELECT COUNT(*) FROM ecod_curation.domain_assignment;
   SELECT * FROM ecod_curation.queue_view;
   ```

3. **Verify data quality**
   - All domains have evidence
   - F-groups assigned where possible
   - Queue populated appropriately

## Timeline

- **Week 1**: Implement `curation_loader.py`
- **Week 2**: Test with small batch, iterate
- **Week 3**: Implement `accession.py` script
- **Week 4**: End-to-end test with pyecod_vis

## Summary

**ecod_curation** is a manual review queue for ~10-12% of domains that need human judgment:
- Low quality partitions (coverage <80%)
- New Pfam families (no F-group mapping)
- Conflicting evidence

**High-quality domains (~88-90%)** bypass ecod_curation and go directly to ecod_commons via auto-accession.

**Key modules**:
- `curation_loader.py` - Load domains to review queue (✅ implemented)
- `route_and_load.py` - Routing logic (⏳ in progress)
- `accession.py` - Move curated domains to ecod_commons (⏳ not started)

## References

- **Complete workflow**: [PRODUCTION_WORKFLOW.md](PRODUCTION_WORKFLOW.md)
- **Routing logic**: [PRODUCTION_PIPELINE.md](PRODUCTION_PIPELINE.md)
- **pyecod_vis schema**: `/home/rschaeff/dev/pyecod_vis/SCHEMA_CONTRACT_v2.md`
- **Operations boundary**: `/home/rschaeff/dev/pyecod_vis/OPERATIONS_BOUNDARY.md`
- **Database**: ecod_curation schema on dione:45000/ecod_protein
