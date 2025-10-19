#!/usr/bin/env python3
"""
Parse PDB weekly status files and extract protein chains for classification.

The PDB releases weekly status files in /usr2/pdb/data/status/{YYYYMMDD}/
containing lists of added, modified, and obsolete entries.
"""

import gzip
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from Bio.PDB import MMCIFParser
    from Bio.PDB.Polypeptide import is_aa
    HAS_BIOPYTHON = True
except ImportError:
    HAS_BIOPYTHON = False


@dataclass
class ChainInfo:
    """Information about a protein chain"""

    pdb_id: str
    chain_id: str
    sequence: str
    sequence_length: int
    can_classify: bool
    cannot_classify_reason: Optional[str] = None

    def __post_init__(self):
        """Validate chain info"""
        if not self.pdb_id:
            raise ValueError("pdb_id cannot be empty")
        if not self.chain_id:
            raise ValueError("chain_id cannot be empty")
        if self.sequence_length <= 0:
            raise ValueError(f"Invalid sequence length: {self.sequence_length}")


class PDBStatusParser:
    """
    Parse PDB weekly status files and extract chain information.

    Handles:
    - Reading added.pdb, modified.pdb from weekly status
    - Parsing mmCIF files to enumerate chains
    - Filtering out non-classifiable chains (peptides, nucleic acids)
    """

    # Peptide threshold - chains shorter than this are considered peptides
    PEPTIDE_THRESHOLD = 20

    def __init__(
        self,
        pdb_mirror_path: str = "/usr2/pdb/data/structures/divided/mmCIF",
        peptide_threshold: int = 20,
    ):
        """
        Initialize PDB status parser.

        Args:
            pdb_mirror_path: Path to local PDB mmCIF mirror
            peptide_threshold: Minimum length for classifiable protein chain
        """
        self.pdb_mirror_path = Path(pdb_mirror_path)
        self.peptide_threshold = peptide_threshold

        if not HAS_BIOPYTHON:
            raise ImportError(
                "Biopython is required for PDBStatusParser. "
                "Install with: pip install biopython"
            )

        self.parser = MMCIFParser(QUIET=True)

    def get_weekly_additions(self, status_dir: str) -> List[str]:
        """
        Read added.pdb and return list of PDB IDs.

        Args:
            status_dir: Path to weekly status directory (e.g., /usr2/pdb/data/status/20251010)

        Returns:
            List of PDB IDs (lowercase)
        """
        added_file = Path(status_dir) / "added.pdb"

        if not added_file.exists():
            raise FileNotFoundError(f"Status file not found: {added_file}")

        pdb_ids = []
        with open(added_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    # Extract PDB ID (first 4 characters)
                    pdb_id = line[:4].lower()
                    if len(pdb_id) == 4:
                        pdb_ids.append(pdb_id)

        return pdb_ids

    def get_weekly_modifications(self, status_dir: str) -> List[str]:
        """
        Read modified.pdb and return list of PDB IDs.

        Args:
            status_dir: Path to weekly status directory

        Returns:
            List of PDB IDs (lowercase)
        """
        modified_file = Path(status_dir) / "modified.pdb"

        if not modified_file.exists():
            # Modified file is optional - may not exist every week
            return []

        pdb_ids = []
        with open(modified_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    pdb_id = line[:4].lower()
                    if len(pdb_id) == 4:
                        pdb_ids.append(pdb_id)

        return pdb_ids

    def get_mmcif_path(self, pdb_id: str) -> Path:
        """
        Get path to mmCIF file for a PDB ID.

        Args:
            pdb_id: PDB ID (will be converted to lowercase)

        Returns:
            Path to mmCIF file
        """
        pdb_id = pdb_id.lower()
        # mmCIF files are organized as: /path/to/mmCIF/ab/1abc.cif.gz or 1abc.cif
        middle_letters = pdb_id[1:3]
        cif_file = self.pdb_mirror_path / middle_letters / f"{pdb_id}.cif"
        cif_gz_file = self.pdb_mirror_path / middle_letters / f"{pdb_id}.cif.gz"

        if cif_gz_file.exists():
            return cif_gz_file
        elif cif_file.exists():
            return cif_file
        else:
            raise FileNotFoundError(f"mmCIF file not found for {pdb_id} in {self.pdb_mirror_path}")

    def get_chains_for_pdb(self, pdb_id: str) -> List[ChainInfo]:
        """
        Parse mmCIF file and extract all protein chains with sequences.

        Args:
            pdb_id: PDB ID

        Returns:
            List of ChainInfo objects
        """
        mmcif_path = self.get_mmcif_path(pdb_id)

        try:
            # Handle gzipped files
            if str(mmcif_path).endswith('.gz'):
                with gzip.open(mmcif_path, 'rt') as f:
                    structure = self.parser.get_structure(pdb_id, f)
            else:
                structure = self.parser.get_structure(pdb_id, str(mmcif_path))
        except Exception as e:
            raise ValueError(f"Failed to parse {mmcif_path}: {e}")

        chains = []

        for model in structure:
            for chain in model:
                chain_id = chain.get_id()

                # Extract sequence from residues
                sequence = []
                for residue in chain:
                    if residue.id[0] == " ":  # Standard residue (not HETATM)
                        resname = residue.get_resname()
                        # Check if it's a standard amino acid
                        if is_aa(resname, standard=True):
                            # Convert 3-letter to 1-letter code
                            try:
                                from Bio.SeqUtils import seq1
                                aa = seq1(resname)
                                sequence.append(aa)
                            except (KeyError, ValueError):
                                # Unknown residue - skip
                                pass

                if not sequence:
                    # Empty chain or no amino acids
                    continue

                sequence_str = "".join(sequence)
                sequence_length = len(sequence_str)

                # Determine if classifiable
                can_classify, reason = self._is_classifiable(sequence_str, sequence_length)

                chain_info = ChainInfo(
                    pdb_id=pdb_id.lower(),
                    chain_id=chain_id,
                    sequence=sequence_str,
                    sequence_length=sequence_length,
                    can_classify=can_classify,
                    cannot_classify_reason=reason,
                )

                chains.append(chain_info)

        return chains

    def _is_classifiable(self, sequence: str, length: int) -> Tuple[bool, Optional[str]]:
        """
        Determine if a chain can be classified.

        Args:
            sequence: Amino acid sequence
            length: Sequence length

        Returns:
            (can_classify, reason) - reason is None if classifiable
        """
        # Check length - peptides are too short
        if length < self.peptide_threshold:
            return False, "peptide"

        # Could add more filters here:
        # - Check for unusual amino acid composition
        # - Check for disordered regions
        # - Check sequence quality

        return True, None

    def filter_classifiable_chains(self, chains: List[ChainInfo]) -> Dict[str, List[ChainInfo]]:
        """
        Separate chains into classifiable and non-classifiable groups.

        Args:
            chains: List of ChainInfo objects

        Returns:
            Dict with keys:
                - 'classifiable': Chains that can be classified
                - 'peptides': Chains too short (< threshold)
                - 'other': Other non-classifiable chains
        """
        result = {
            "classifiable": [],
            "peptides": [],
            "other": [],
        }

        for chain in chains:
            if chain.can_classify:
                result["classifiable"].append(chain)
            elif chain.cannot_classify_reason == "peptide":
                result["peptides"].append(chain)
            else:
                result["other"].append(chain)

        return result

    def process_weekly_release(self, status_dir: str) -> Dict:
        """
        Process a complete weekly release.

        Args:
            status_dir: Path to weekly status directory

        Returns:
            Dict with:
                - pdb_ids: List of PDB IDs from added.pdb
                - chains: All ChainInfo objects
                - classifiable: Classifiable chains
                - peptides: Peptide chains
                - other: Other non-classifiable chains
                - failed: PDB IDs that failed to parse
        """
        print(f"Processing weekly release: {status_dir}")

        # Get PDB IDs from status files
        pdb_ids = self.get_weekly_additions(status_dir)
        print(f"Found {len(pdb_ids)} new PDB entries")

        # Process each PDB entry
        all_chains = []
        failed = []

        for pdb_id in pdb_ids:
            try:
                chains = self.get_chains_for_pdb(pdb_id)
                all_chains.extend(chains)
            except Exception as e:
                print(f"Warning: Failed to process {pdb_id}: {e}")
                failed.append(pdb_id)

        # Filter chains
        filtered = self.filter_classifiable_chains(all_chains)

        print(f"Total chains: {len(all_chains)}")
        print(f"  Classifiable: {len(filtered['classifiable'])}")
        print(f"  Peptides: {len(filtered['peptides'])}")
        print(f"  Other: {len(filtered['other'])}")
        print(f"  Failed to parse: {len(failed)}")

        return {
            "pdb_ids": pdb_ids,
            "chains": all_chains,
            "classifiable": filtered["classifiable"],
            "peptides": filtered["peptides"],
            "other": filtered["other"],
            "failed": failed,
        }


def main():
    """Command-line interface for testing"""
    import argparse

    parser = argparse.ArgumentParser(description="Parse PDB weekly status files")
    parser.add_argument("status_dir", help="Path to weekly status directory (e.g., /usr2/pdb/data/status/20251010)")
    parser.add_argument("--pdb-mirror", default="/usr2/pdb/data/structures/divided/mmCIF", help="Path to PDB mmCIF mirror")
    parser.add_argument("--peptide-threshold", type=int, default=20, help="Minimum chain length for classification")

    args = parser.parse_args()

    status_parser = PDBStatusParser(
        pdb_mirror_path=args.pdb_mirror,
        peptide_threshold=args.peptide_threshold,
    )

    result = status_parser.process_weekly_release(args.status_dir)

    # Print sample classifiable chains
    print("\nSample classifiable chains:")
    for chain in result["classifiable"][:10]:
        print(f"  {chain.pdb_id}_{chain.chain_id}: {chain.sequence_length} residues")


if __name__ == "__main__":
    main()
