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

# mmCIF source-organism fields, one per source category
SOURCE_ORGANISM_FIELDS = [
    ('_entity_src_gen', 'pdbx_gene_src_scientific_name'),
    ('_entity_src_nat', 'pdbx_organism_scientific'),
    ('_pdbx_entity_src_syn', 'organism_scientific'),
]

# Source organisms that do not tie an entity to a natural protein. Entry-level
# design language (title, keywords) is attributed only to entities like these.
UNANCHORED_ORGANISMS = {
    'synthetic construct',
    'unidentified',
    'unknown',
    'artificial sequence',
}


def _cif_values(cif: Dict, key: str) -> List[str]:
    """Return an MMCIF2Dict field as a list, with '?' and '.' mapped to ''."""
    value = cif.get(key, [])
    if isinstance(value, str):
        value = [value]
    return [v.strip() if v not in ('?', '.') else '' for v in value]


def _is_unanchored(organisms: List[str]) -> bool:
    """True if an entity has no natural source organism."""
    return all(o.lower() in UNANCHORED_ORGANISMS for o in organisms)


def _has_synthetic_construct(organisms: List[str]) -> bool:
    return any(o.lower() == 'synthetic construct' for o in organisms)


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
        self._entry_cache: Dict[str, Dict] = {}

    def _get_mmcif_path(self, pdb_id: str) -> Optional[Path]:
        """Locate the mmCIF file for a PDB ID, or None if it is not on the mirror."""
        try:
            from pyecod_prod.utils.pdb_ids import get_directory_hash
            dir_hash = get_directory_hash(pdb_id)
        except (ImportError, ValueError):
            # Fallback for legacy IDs
            dir_hash = pdb_id[1:3]

        for name in (f"{pdb_id}.cif.gz", f"{pdb_id}.cif"):
            path = self.pdb_mirror_path / dir_hash / name
            if path.exists():
                return path
        return None

    def get_entry_info(self, pdb_id: str) -> Dict:
        """
        Read entry- and entity-level provenance from the mmCIF file.

        Uses Biopython's MMCIF2Dict so quoted and multi-line values parse
        correctly. Only polypeptide entities are returned.

        Args:
            pdb_id: PDB identifier

        Returns:
            Dict with 'title', 'keywords' and 'entities', where 'entities' maps
            entity_id -> {'description', 'organisms', 'chains'}. 'chains' are
            author chain IDs (_entity_poly.pdbx_strand_id), matching the chain
            IDs Biopython's MMCIFParser assigns.
        """
        pdb_id = pdb_id.lower()
        if pdb_id in self._entry_cache:
            return self._entry_cache[pdb_id]

        info: Dict = {'title': '', 'keywords': '', 'entities': {}}
        mmcif_path = self._get_mmcif_path(pdb_id)
        if mmcif_path is None:
            self._entry_cache[pdb_id] = info
            return info

        try:
            from Bio.PDB.MMCIF2Dict import MMCIF2Dict

            opener = gzip.open if str(mmcif_path).endswith('.gz') else open
            with opener(mmcif_path, 'rt', errors='replace') as f:
                cif = MMCIF2Dict(f)
        except Exception:
            self._entry_cache[pdb_id] = info
            return info

        info['title'] = ' '.join(_cif_values(cif, '_struct.title'))
        info['keywords'] = ' '.join(_cif_values(cif, '_struct_keywords.pdbx_keywords'))

        descriptions = dict(zip(
            _cif_values(cif, '_entity.id'),
            _cif_values(cif, '_entity.pdbx_description'),
        ))

        entities = info['entities']
        for entity_id, poly_type, strands in zip(
            _cif_values(cif, '_entity_poly.entity_id'),
            _cif_values(cif, '_entity_poly.type'),
            _cif_values(cif, '_entity_poly.pdbx_strand_id'),
        ):
            if 'polypeptide' not in poly_type.lower():
                continue
            entities[entity_id] = {
                'description': descriptions.get(entity_id, ''),
                'organisms': [],
                'chains': [c.strip() for c in strands.split(',') if c.strip()],
            }

        # An entity can have several source rows (chimeras, fusions).
        for category, field_name in SOURCE_ORGANISM_FIELDS:
            for entity_id, organism in zip(
                _cif_values(cif, f'{category}.entity_id'),
                _cif_values(cif, f'{category}.{field_name}'),
            ):
                if entity_id in entities and organism:
                    entities[entity_id]['organisms'].append(organism)

        self._entry_cache[pdb_id] = info
        return info

    def get_pdb_metadata(self, pdb_id: str) -> Dict[str, str]:
        """
        Extract entry-level metadata from mmCIF file.

        'source_organism' is 'synthetic construct' only when every polypeptide
        entity is unanchored (no natural source organism) and at least one is
        a synthetic construct. A synthetic DNA strand, peptide ligand or tag on
        one entity no longer marks the whole entry.

        Args:
            pdb_id: PDB identifier

        Returns:
            Dict with 'title', 'keywords', 'source_organism'
        """
        pdb_id = pdb_id.lower()

        # Check cache
        if pdb_id in self._metadata_cache:
            return self._metadata_cache[pdb_id]

        info = self.get_entry_info(pdb_id)
        entities = list(info['entities'].values())

        source_organism = ''
        if entities and all(_is_unanchored(e['organisms']) for e in entities):
            if any(_has_synthetic_construct(e['organisms']) for e in entities):
                source_organism = 'synthetic construct'
        else:
            for entity in entities:
                natural = [o for o in entity['organisms'] if o.lower() not in UNANCHORED_ORGANISMS]
                if natural:
                    source_organism = natural[0]
                    break

        metadata = {
            'title': info['title'],
            'keywords': info['keywords'],
            'source_organism': source_organism,
        }
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

        # Remove false-positive phrases ("designed for bacterial expression",
        # "synthetic biology") so they cannot match the title patterns below
        match_title = title
        for fp_pattern in self._false_positive_patterns:
            match_title = fp_pattern.sub(' ', match_title)

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
            if pattern.search(match_title):
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

    def detect_chains(self, pdb_id: str) -> Dict[str, DesignedProteinResult]:
        """
        Detect designed proteins per author chain.

        Each chain is scored from its own entity: the entity description and
        source organism. Entry-level signals (title, DE NOVO PROTEIN keyword)
        are attributed only to entities with no natural source organism, so a
        natural binding partner in a design paper is not marked designed.

        Args:
            pdb_id: PDB identifier

        Returns:
            Dict mapping author chain ID -> DesignedProteinResult. Empty if the
            mmCIF file is missing or unreadable.
        """
        pdb_id = pdb_id.lower()
        info = self.get_entry_info(pdb_id)

        results = {}
        for entity in info['entities'].values():
            unanchored = _is_unanchored(entity['organisms'])
            text = entity['description']
            if unanchored:
                text = f"{text} {info['title']}"
            metadata = {
                'title': text,
                'keywords': info['keywords'] if unanchored else '',
                # A fusion's tag or linker row must not mark its natural partner
                'source_organism': (
                    'synthetic construct'
                    if unanchored and _has_synthetic_construct(entity['organisms'])
                    else '; '.join(
                        o for o in entity['organisms']
                        if o.lower() not in UNANCHORED_ORGANISMS
                    )
                ),
            }
            result = self.detect(pdb_id, metadata=metadata)
            for chain_id in entity['chains']:
                results[chain_id] = result
        return results

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
