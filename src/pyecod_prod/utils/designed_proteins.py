#!/usr/bin/env python3
"""
Designed protein detection utilities.

Detects computationally designed, de novo, and synthetic proteins that should
be excluded from ECOD classification (which focuses on naturally evolved proteins).

Detection is based on PDB metadata:
- Source organism: "synthetic construct"
- Keywords: "DE NOVO PROTEIN"
- Title patterns: "designed", "de novo", "miniprotein", etc.
- Design method mentions: Rosetta, RFdiffusion, ProteinMPNN, etc.

The detection uses a scoring system to handle varying confidence levels.
"""

import gzip
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class DesignedProteinConfidence(Enum):
    """Confidence level for designed protein detection."""
    HIGH = "high"       # Score >= 3: Almost certainly designed
    MEDIUM = "medium"   # Score 1-2: Likely designed, may need review
    NONE = "none"       # Score 0: Not detected as designed


@dataclass
class DesignedProteinResult:
    """Result of designed protein detection for a PDB entry."""
    pdb_id: str
    is_designed: bool
    confidence: DesignedProteinConfidence
    score: int
    reasons: List[str] = field(default_factory=list)
    title: str = ""
    keywords: str = ""
    source_organism: str = ""

    @property
    def should_exclude(self) -> bool:
        """Whether this entry should be excluded from classification."""
        return self.confidence == DesignedProteinConfidence.HIGH


# Detection patterns with associated scores
TITLE_PATTERNS = {
    # High confidence patterns (score +2)
    r'\bde novo\b': ('de_novo_title', 2),
    r'\bcomputational(ly)?\s+design': ('computational_design', 2),
    r'\bminiprotein\b': ('miniprotein', 2),
    r'\bminibinder\b': ('minibinder', 2),

    # Design method mentions (score +2)
    r'\brosetta\b': ('rosetta_method', 2),
    r'\brfdiffusion\b': ('rfdiffusion_method', 2),
    r'\bproteinmpnn\b': ('proteinmpnn_method', 2),
    r'\bhallucin': ('hallucination_method', 2),
    r'\bchroma\b': ('chroma_method', 2),
    r'\balphafold\s*design': ('alphafold_design', 2),

    # Medium confidence patterns (score +1)
    r'\bdesigned\b': ('designed_title', 1),
    r'\bartificial\s+protein': ('artificial_protein', 1),
    r'\bsynthetic\s+protein': ('synthetic_protein', 1),
}

KEYWORD_PATTERNS = {
    # High confidence keywords (score +3)
    'DE NOVO PROTEIN': ('de_novo_keyword', 3),
}

# Patterns to avoid false positives
FALSE_POSITIVE_PATTERNS = [
    r'synthetic\s+lethality',  # Not a designed protein
    r'synthetic\s+biology',    # Field name, not designed protein
    r'designed\s+to\s+',       # "designed to study..." - not a designed protein
    r'designed\s+for\s+',      # "designed for..." - not a designed protein
]


class DesignedProteinDetector:
    """
    Detect designed/synthetic proteins from PDB metadata.

    Uses a scoring system:
    - Score >= 3: High confidence designed protein
    - Score 1-2: Medium confidence (may need review)
    - Score 0: Not detected as designed
    """

    def __init__(
        self,
        pdb_mirror_path: str = "/usr2/pdb/data/structures/divided/mmCIF",
        high_confidence_threshold: int = 3,
        exclude_medium_confidence: bool = False,
    ):
        """
        Initialize detector.

        Args:
            pdb_mirror_path: Path to local PDB mmCIF mirror
            high_confidence_threshold: Minimum score for high confidence
            exclude_medium_confidence: If True, also exclude medium confidence entries
        """
        self.pdb_mirror_path = Path(pdb_mirror_path)
        self.high_confidence_threshold = high_confidence_threshold
        self.exclude_medium_confidence = exclude_medium_confidence

        # Compile regex patterns
        self._title_patterns = {
            re.compile(pattern, re.IGNORECASE): (name, score)
            for pattern, (name, score) in TITLE_PATTERNS.items()
        }
        self._false_positive_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in FALSE_POSITIVE_PATTERNS
        ]

        # Cache for PDB metadata
        self._metadata_cache: Dict[str, Dict[str, str]] = {}

    def get_pdb_metadata(self, pdb_id: str) -> Dict[str, str]:
        """
        Extract relevant metadata from mmCIF file.

        Args:
            pdb_id: PDB identifier

        Returns:
            Dict with 'title', 'keywords', 'source_organism'
        """
        pdb_id = pdb_id.lower()

        # Check cache
        if pdb_id in self._metadata_cache:
            return self._metadata_cache[pdb_id]

        metadata = {
            'title': '',
            'keywords': '',
            'source_organism': '',
        }

        # Find mmCIF file
        try:
            from pyecod_prod.utils.pdb_ids import get_directory_hash
            dir_hash = get_directory_hash(pdb_id)
        except (ImportError, ValueError):
            # Fallback for legacy IDs
            dir_hash = pdb_id[1:3]

        mmcif_path = self.pdb_mirror_path / dir_hash / f"{pdb_id}.cif.gz"
        if not mmcif_path.exists():
            mmcif_path = self.pdb_mirror_path / dir_hash / f"{pdb_id}.cif"

        if not mmcif_path.exists():
            self._metadata_cache[pdb_id] = metadata
            return metadata

        try:
            opener = gzip.open if str(mmcif_path).endswith('.gz') else open
            with opener(mmcif_path, 'rt', errors='replace') as f:
                in_title = False
                title_lines = []

                for line in f:
                    # Title (can be multi-line)
                    if line.startswith('_struct.title'):
                        if "'" in line:
                            metadata['title'] = line.split("'")[1]
                        elif ';' in line:
                            in_title = True
                        else:
                            parts = line.strip().split(None, 1)
                            if len(parts) > 1:
                                metadata['title'] = parts[1]
                    elif in_title:
                        if line.startswith(';'):
                            metadata['title'] = ' '.join(title_lines)
                            in_title = False
                        else:
                            title_lines.append(line.strip())

                    # Keywords
                    elif line.startswith('_struct_keywords.pdbx_keywords'):
                        parts = line.strip().split(None, 1)
                        if len(parts) > 1:
                            metadata['keywords'] = parts[1].strip("'\"")

                    # Source organism (check multiple fields)
                    elif line.startswith('_entity_src_gen.pdbx_gene_src_scientific_name'):
                        parts = line.strip().split(None, 1)
                        if len(parts) > 1 and parts[1] not in ['?', '.']:
                            org = parts[1].strip("'\"")
                            if org and not metadata['source_organism']:
                                metadata['source_organism'] = org

                    # Also check for "synthetic construct" anywhere
                    if 'synthetic construct' in line.lower():
                        metadata['source_organism'] = 'synthetic construct'

                    # Stop early if we have everything
                    if all(metadata.values()):
                        break

        except Exception:
            pass

        self._metadata_cache[pdb_id] = metadata
        return metadata

    def detect(self, pdb_id: str, metadata: Optional[Dict[str, str]] = None) -> DesignedProteinResult:
        """
        Detect if a PDB entry is a designed protein.

        Args:
            pdb_id: PDB identifier
            metadata: Optional pre-fetched metadata (title, keywords, source_organism)

        Returns:
            DesignedProteinResult with detection details
        """
        pdb_id = pdb_id.lower()

        # Get metadata if not provided
        if metadata is None:
            metadata = self.get_pdb_metadata(pdb_id)

        title = metadata.get('title', '')
        keywords = metadata.get('keywords', '')
        source_organism = metadata.get('source_organism', '')

        score = 0
        reasons = []

        # Check for false positive patterns first
        combined_text = f"{title} {keywords}".lower()
        for fp_pattern in self._false_positive_patterns:
            if fp_pattern.search(combined_text):
                # Reduce confidence if false positive pattern found
                # Don't return immediately - still check other markers
                pass

        # Check source organism (high confidence)
        if 'synthetic construct' in source_organism.lower():
            score += 3
            reasons.append('synthetic_construct_organism')

        # Check keywords
        keywords_upper = keywords.upper()
        for kw, (name, kw_score) in KEYWORD_PATTERNS.items():
            if kw in keywords_upper:
                score += kw_score
                reasons.append(name)

        # Check title patterns
        for pattern, (name, pattern_score) in self._title_patterns.items():
            if pattern.search(title):
                score += pattern_score
                reasons.append(name)

        # Determine confidence level
        if score >= self.high_confidence_threshold:
            confidence = DesignedProteinConfidence.HIGH
        elif score >= 1:
            confidence = DesignedProteinConfidence.MEDIUM
        else:
            confidence = DesignedProteinConfidence.NONE

        is_designed = confidence != DesignedProteinConfidence.NONE

        return DesignedProteinResult(
            pdb_id=pdb_id,
            is_designed=is_designed,
            confidence=confidence,
            score=score,
            reasons=reasons,
            title=title,
            keywords=keywords,
            source_organism=source_organism,
        )

    def detect_batch(self, pdb_ids: List[str]) -> Dict[str, DesignedProteinResult]:
        """
        Detect designed proteins for a batch of PDB IDs.

        Args:
            pdb_ids: List of PDB identifiers

        Returns:
            Dict mapping pdb_id -> DesignedProteinResult
        """
        results = {}
        for pdb_id in pdb_ids:
            results[pdb_id] = self.detect(pdb_id)
        return results

    def filter_designed(
        self,
        pdb_ids: List[str],
        include_medium_confidence: bool = False,
    ) -> Tuple[List[str], List[str]]:
        """
        Filter out designed proteins from a list of PDB IDs.

        Args:
            pdb_ids: List of PDB identifiers
            include_medium_confidence: If True, also filter medium confidence

        Returns:
            Tuple of (natural_pdb_ids, designed_pdb_ids)
        """
        natural = []
        designed = []

        for pdb_id in pdb_ids:
            result = self.detect(pdb_id)

            should_filter = (
                result.confidence == DesignedProteinConfidence.HIGH or
                (include_medium_confidence and result.confidence == DesignedProteinConfidence.MEDIUM)
            )

            if should_filter:
                designed.append(pdb_id)
            else:
                natural.append(pdb_id)

        return natural, designed

    def clear_cache(self):
        """Clear the metadata cache."""
        self._metadata_cache.clear()


def is_designed_protein(
    pdb_id: str,
    pdb_mirror_path: str = "/usr2/pdb/data/structures/divided/mmCIF",
) -> bool:
    """
    Quick check if a PDB entry is a designed protein.

    Args:
        pdb_id: PDB identifier
        pdb_mirror_path: Path to PDB mmCIF mirror

    Returns:
        True if high-confidence designed protein
    """
    detector = DesignedProteinDetector(pdb_mirror_path=pdb_mirror_path)
    result = detector.detect(pdb_id)
    return result.should_exclude


def get_designed_protein_info(
    pdb_id: str,
    pdb_mirror_path: str = "/usr2/pdb/data/structures/divided/mmCIF",
) -> DesignedProteinResult:
    """
    Get detailed designed protein detection info.

    Args:
        pdb_id: PDB identifier
        pdb_mirror_path: Path to PDB mmCIF mirror

    Returns:
        DesignedProteinResult with full detection details
    """
    detector = DesignedProteinDetector(pdb_mirror_path=pdb_mirror_path)
    return detector.detect(pdb_id)
