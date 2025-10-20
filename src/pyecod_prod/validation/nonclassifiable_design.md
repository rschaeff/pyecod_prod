# Modern Non-Classifiable Region Tracking System

## Purpose

Replace the legacy `public.special_architecture` table with a modern system integrated into `ecod_commons` schema for tracking protein regions that cannot be domain-classified.

## Legacy System Analysis

### Current `public.special_architecture` Table
- **Rows**: 129,179 entries
- **Schema**:
  ```sql
  ecod_uid INTEGER
  pdb_id VARCHAR(4)
  chain_id VARCHAR
  seqid_range VARCHAR  -- e.g., "1-50"
  pdb_range VARCHAR
  res_count INTEGER
  struct_res_count INTEGER
  type VARCHAR  -- peptide, expression_tag, coil, etc.
  ```

### Top Non-Classifiable Types (20+ types total):
1. `expression_tag` - 70,369 (54.5%) - Cloning artifacts
2. `peptide` - 23,744 (18.4%) - Chains <20 residues
3. `nonpeptide_poly` - 15,735 (12.2%) - Non-protein polymers
4. `coil` - 5,681 (4.4%) - Coiled-coil regions
5. `emuq` - 4,189 (3.2%) - Extended motif of unknown quality
6. `pss` - 2,887 (2.2%) - Poor secondary structure
7. `leader_sequence` - 1,659 (1.3%)
8. `fragment` - 1,600 (1.2%)
9. `synthetic` - 1,109 (0.9%)
10. `linker` - 1,082 (0.8%)

### Problems with Legacy System:
1. Separate schema (`public`) being phased out
2. No clear integration with modern `ecod_commons` workflow
3. Type field is free-text, inconsistent
4. No standardized detection methods
5. No versioning or tracking of when/how regions were identified

## Proposed Modern System

### 1. New Table: `ecod_commons.nonclassifiable_regions`

```sql
CREATE TABLE ecod_commons.nonclassifiable_regions (
    id SERIAL PRIMARY KEY,

    -- Foreign keys to ecod_commons
    protein_id INTEGER REFERENCES ecod_commons.proteins(id) NOT NULL,
    version_id INTEGER REFERENCES ecod_commons.versions(id),

    -- Region definition
    seqid_range VARCHAR(50) NOT NULL,  -- e.g., "1-50"
    pdb_range VARCHAR(50),  -- Optional, for PDB structures
    residue_count INTEGER NOT NULL,
    structured_residue_count INTEGER,  -- From PDB structure

    -- Classification
    reason_code VARCHAR(50) NOT NULL,  -- Standardized code
    reason_description TEXT,  -- Human-readable explanation
    confidence NUMERIC(3,2),  -- 0.0-1.0 confidence in classification

    -- Detection metadata
    detection_method VARCHAR(50) NOT NULL,  -- 'automatic', 'manual', 'sequence_length', etc.
    detected_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    detected_by VARCHAR(50),  -- User or program name

    -- Notes
    notes TEXT,

    -- Constraints
    CONSTRAINT valid_confidence CHECK (confidence BETWEEN 0.0 AND 1.0),
    CONSTRAINT valid_reason_code CHECK (reason_code IN (
        'peptide', 'expression_tag', 'nonpeptide_poly', 'coil',
        'linker', 'leader_sequence', 'fragment', 'synthetic',
        'disordered', 'low_complexity', 'transmembrane',
        'signal_peptide', 'nucleic_acid_binding',
        'emuq', 'pss', 'other'
    ))
);

-- Indexes for performance
CREATE INDEX idx_nonclass_protein ON ecod_commons.nonclassifiable_regions(protein_id);
CREATE INDEX idx_nonclass_version ON ecod_commons.nonclassifiable_regions(version_id);
CREATE INDEX idx_nonclass_reason ON ecod_commons.nonclassifiable_regions(reason_code);
CREATE INDEX idx_nonclass_method ON ecod_commons.nonclassifiable_regions(detection_method);
```

### 2. Standardized Reason Codes

| Code | Description | Auto-Detectable | Detection Method |
|------|-------------|-----------------|------------------|
| `peptide` | Chain <20 residues | Yes | Sequence length |
| `expression_tag` | Cloning/purification tag | Partial | Sequence motifs, N/C-terminal position |
| `nonpeptide_poly` | Non-protein polymer | No | Manual / SEQRES analysis |
| `coil` | Coiled-coil region | Yes | COILS, Marcoil |
| `linker` | Inter-domain linker | Partial | Secondary structure, flexibility |
| `leader_sequence` | Signal/transit peptide | Yes | SignalP, TargetP |
| `fragment` | Incomplete/partial chain | Partial | Alignment coverage |
| `synthetic` | Artificial sequence | No | Manual annotation |
| `disordered` | Intrinsically disordered | Yes | IUPred, PONDR |
| `low_complexity` | Low-complexity region | Yes | SEG, CAST |
| `transmembrane` | Membrane-spanning region | Yes | TMHMM, Phobius |
| `signal_peptide` | Signal peptide | Yes | SignalP |
| `nucleic_acid_binding` | Nucleic acid binding | Partial | Structure, sequence motifs |
| `emuq` | Extended motif unknown quality | No | Manual |
| `pss` | Poor secondary structure | No | Manual / structure analysis |
| `other` | Other reason | No | Manual |

### 3. Integration with Weekly Batch Processing

**Location**: `/home/rschaeff/dev/pyecod_prod/src/pyecod_prod/filters/nonclassifiable.py`

```python
from dataclasses import dataclass
from typing import Optional, List
from enum import Enum

class ReasonCode(Enum):
    """Standardized non-classifiable reason codes"""
    PEPTIDE = "peptide"
    EXPRESSION_TAG = "expression_tag"
    NONPEPTIDE_POLY = "nonpeptide_poly"
    COIL = "coil"
    LINKER = "linker"
    LEADER_SEQUENCE = "leader_sequence"
    FRAGMENT = "fragment"
    SYNTHETIC = "synthetic"
    DISORDERED = "disordered"
    LOW_COMPLEXITY = "low_complexity"
    TRANSMEMBRANE = "transmembrane"
    SIGNAL_PEPTIDE = "signal_peptide"
    NUCLEIC_ACID_BINDING = "nucleic_acid_binding"
    EMUQ = "emuq"
    PSS = "pss"
    OTHER = "other"

@dataclass
class NonClassifiableRegion:
    """A region of a protein that cannot be domain-classified"""

    protein_id: int  # Foreign key to ecod_commons.proteins
    seqid_range: str  # e.g., "1-50"
    residue_count: int
    reason_code: ReasonCode
    reason_description: str
    detection_method: str
    confidence: float = 1.0
    pdb_range: Optional[str] = None
    structured_residue_count: Optional[int] = None
    notes: Optional[str] = None

class NonClassifiableDetector:
    """
    Detect and classify non-classifiable regions in protein chains.

    Integrates with weekly batch processing to automatically identify
    regions that should not be domain-classified.
    """

    def __init__(self, peptide_threshold: int = 20):
        self.peptide_threshold = peptide_threshold

    def detect_peptides(self, chain_info) -> Optional[NonClassifiableRegion]:
        """Detect peptide chains (< threshold residues)"""
        if chain_info.sequence_length < self.peptide_threshold:
            return NonClassifiableRegion(
                protein_id=chain_info.protein_id,
                seqid_range=f"1-{chain_info.sequence_length}",
                residue_count=chain_info.sequence_length,
                reason_code=ReasonCode.PEPTIDE,
                reason_description=f"Chain shorter than {self.peptide_threshold} residues",
                detection_method="automatic_length",
                confidence=1.0
            )
        return None

    def detect_expression_tags(self, sequence: str, chain_info) -> List[NonClassifiableRegion]:
        """
        Detect common expression tags (His-tag, GST-tag, etc.)

        Common tags:
        - His-tag: HHHHHH (6xHis) or HHHHHHHHHH (10xHis)
        - FLAG-tag: DYKDDDDK
        - Strep-tag: WSHPQFEK
        - GST-tag: First ~220 residues if GST sequence
        """
        regions = []

        # Check N-terminus for His-tag
        if sequence[:6] == "H" * 6 or sequence[:10] == "H" * 10:
            tag_len = 10 if sequence[:10] == "H" * 10 else 6
            regions.append(NonClassifiableRegion(
                protein_id=chain_info.protein_id,
                seqid_range=f"1-{tag_len}",
                residue_count=tag_len,
                reason_code=ReasonCode.EXPRESSION_TAG,
                reason_description=f"N-terminal {tag_len}xHis tag",
                detection_method="automatic_sequence_motif",
                confidence=0.95
            ))

        # Check C-terminus for His-tag
        if sequence[-6:] == "H" * 6 or sequence[-10:] == "H" * 10:
            tag_len = 10 if sequence[-10:] == "H" * 10 else 6
            start = len(sequence) - tag_len + 1
            regions.append(NonClassifiableRegion(
                protein_id=chain_info.protein_id,
                seqid_range=f"{start}-{len(sequence)}",
                residue_count=tag_len,
                reason_code=ReasonCode.EXPRESSION_TAG,
                reason_description=f"C-terminal {tag_len}xHis tag",
                detection_method="automatic_sequence_motif",
                confidence=0.95
            ))

        # Additional tag detection can be added here

        return regions

    def detect_all(self, chain_info, sequence: str) -> List[NonClassifiableRegion]:
        """
        Run all automatic detection methods.

        Returns:
            List of detected non-classifiable regions
        """
        regions = []

        # Check for peptides
        peptide = self.detect_peptides(chain_info)
        if peptide:
            regions.append(peptide)
            return regions  # Entire chain is peptide, no need for further checks

        # Check for expression tags
        tags = self.detect_expression_tags(sequence, chain_info)
        regions.extend(tags)

        # Future: Add more detectors
        # - Coiled coils (COILS algorithm)
        # - Disordered regions (IUPred)
        # - Low complexity (SEG)
        # - Transmembrane (TMHMM)
        # - Signal peptides (SignalP)

        return regions
```

### 4. Integration Points

**Weekly Batch Processing**:
1. After parsing PDB chains, run `NonClassifiableDetector.detect_all()`
2. Store detected regions in `ecod_commons.nonclassifiable_regions`
3. Mark these regions to exclude from BLAST/HHsearch/partitioning
4. Generate summary reports showing nonclassifiable statistics

**Database Queries**:
```sql
-- Get all nonclassifiable regions for a protein
SELECT * FROM ecod_commons.nonclassifiable_regions
WHERE protein_id = 12345;

-- Get statistics by reason code
SELECT reason_code, COUNT(*), AVG(residue_count)
FROM ecod_commons.nonclassifiable_regions
GROUP BY reason_code
ORDER BY COUNT(*) DESC;

-- Get automatically detected vs manually annotated
SELECT detection_method, COUNT(*)
FROM ecod_commons.nonclassifiable_regions
GROUP BY detection_method;
```

### 5. Migration Plan

**Phase 1**: Create new table and Python module
- Add `ecod_commons.nonclassifiable_regions` table
- Implement `NonClassifiableDetector` class
- Integrate with weekly batch processing for NEW entries

**Phase 2**: Migrate legacy data
```sql
-- Migrate from public.special_architecture to new table
INSERT INTO ecod_commons.nonclassifiable_regions
    (protein_id, seqid_range, pdb_range, residue_count,
     structured_residue_count, reason_code, reason_description,
     detection_method, detected_by, notes)
SELECT
    p.id as protein_id,
    sa.seqid_range,
    sa.pdb_range,
    sa.res_count as residue_count,
    sa.struct_res_count as structured_residue_count,
    sa.type as reason_code,
    'Migrated from legacy special_architecture' as reason_description,
    'legacy_migration' as detection_method,
    'system' as detected_by,
    'Original ecod_uid: ' || sa.ecod_uid as notes
FROM public.special_architecture sa
JOIN ecod_commons.proteins p
    ON sa.pdb_id = p.pdb_id AND sa.chain_id = p.chain_id
WHERE p.source_type = 'pdb';
```

**Phase 3**: Validation and cleanup
- Verify migration completeness
- Run quality checks on automated detection
- Archive `public.special_architecture` table

### 6. Benefits of Modern System

1. **Integration**: Seamless with `ecod_commons` schema
2. **Automation**: Automatic detection during weekly processing
3. **Standardization**: Controlled vocabulary for reason codes
4. **Traceability**: Track detection method, confidence, timestamp
5. **Versioning**: Link to ECOD versions for reproducibility
6. **Extensibility**: Easy to add new detection methods
7. **Performance**: Indexed for fast queries
8. **Quality**: Confidence scores for automatic vs manual annotations

## Next Steps

1. ✅ Design complete (this document)
2. Create `ecod_commons.nonclassifiable_regions` table in database
3. Implement `NonClassifiableDetector` class
4. Integrate with weekly batch processing
5. Migrate legacy data from `public.special_architecture`
6. Add advanced detectors (coils, disorder, transmembrane, etc.)
7. Create monitoring/reporting tools for nonclassifiable statistics
