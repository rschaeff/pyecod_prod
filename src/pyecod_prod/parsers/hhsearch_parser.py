#!/usr/bin/env python3
"""
Parse HHsearch HHR output files.

HHsearch produces HHR (HHsuite results) format files containing
profile-to-profile search results.
"""

import os
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class HHsearchHit:
    """Represent an HHsearch hit"""

    hit_number: int
    hit_id: str  # ECOD domain ID
    description: str
    probability: float  # 0-100
    evalue: float
    pvalue: float
    score: float
    query_range: str  # e.g., "10-110"
    template_range: str  # e.g., "1-95"
    query_length: int
    template_length: int
    aligned_cols: int
    identities: float  # Fraction 0.0-1.0


class HHsearchParser:
    """
    Parse HHsearch HHR output files.

    HHR format contains hit table and alignments for
    profile-to-profile searches.
    """

    def parse_hhr(self, hhr_file: str) -> List[HHsearchHit]:
        """
        Parse HHR file and extract hits.

        Args:
            hhr_file: Path to HHR file

        Returns:
            List of HHsearchHit objects
        """
        if not os.path.exists(hhr_file):
            raise FileNotFoundError(f"HHR file not found: {hhr_file}")

        hits = []

        try:
            with open(hhr_file) as f:
                content = f.read()

            # Parse hit table section
            # Starts after "No Hit" line and ends before alignment section
            hit_table_pattern = r"No Hit.*?Prob.*?\n(.*?)\n\s*No \d+"
            match = re.search(hit_table_pattern, content, re.DOTALL)

            if not match:
                # Try alternate pattern for when there are few hits
                hit_table_pattern = r"No Hit.*?Prob.*?\n(.*?)\nNo 1\n"
                match = re.search(hit_table_pattern, content, re.DOTALL)

            if match:
                hit_table = match.group(1)
                hits = self._parse_hit_table(hit_table)

        except Exception as e:
            print(f"Warning: Failed to parse {hhr_file}: {e}")
            return []

        return hits

    def _parse_hit_table(self, hit_table: str) -> List[HHsearchHit]:
        """
        Parse HHR hit table.

        Format:
        No Hit                             Prob E-value P-value  Score    SS Cols Query HMM  Template HMM
         1 e2ia4A1 2ia4.A.1-94            99.9 1.3E-30 1.9E-35  200.5   0.0  100    1-100      1-94 (94)
        """
        hits = []

        for line in hit_table.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            # Parse hit line
            # Format: No Hit_ID Description Prob E-value P-value Score SS Cols Query_range Template_range
            parts = line.split()

            if len(parts) < 10:
                continue

            try:
                # Extract hit number
                hit_num = int(parts[0])

                # Extract hit ID (ECOD domain)
                hit_id = parts[1]

                # Description may contain spaces - reconstruct
                desc_start = 2
                # Find where numerical values start (Prob column)
                desc_end = desc_start
                for i in range(desc_start, len(parts)):
                    try:
                        float(parts[i])
                        desc_end = i
                        break
                    except ValueError:
                        continue

                description = " ".join(parts[desc_start:desc_end])

                # Parse numerical columns
                prob_idx = desc_end
                probability = float(parts[prob_idx])
                evalue = float(parts[prob_idx + 1])
                pvalue = float(parts[prob_idx + 2])
                score = float(parts[prob_idx + 3])
                # SS column (prob_idx + 4)
                aligned_cols = int(parts[prob_idx + 5])

                # Parse query and template ranges
                query_range_str = parts[prob_idx + 6]
                template_range_str = parts[prob_idx + 7]

                # Extract ranges and lengths
                # Format: "10-110" or "1-94(94)"
                query_range, query_len = self._parse_range(query_range_str)
                template_range, template_len = self._parse_range(template_range_str)

                # Identities not directly in table - would need alignment section
                # Set to 0 for now, can be parsed from alignment if needed
                identities = 0.0

                hit = HHsearchHit(
                    hit_number=hit_num,
                    hit_id=hit_id,
                    description=description,
                    probability=probability,
                    evalue=evalue,
                    pvalue=pvalue,
                    score=score,
                    query_range=query_range,
                    template_range=template_range,
                    query_length=query_len,
                    template_length=template_len,
                    aligned_cols=aligned_cols,
                    identities=identities,
                )

                hits.append(hit)

            except (ValueError, IndexError) as e:
                # Skip malformed lines
                continue

        return hits

    def _parse_range(self, range_str: str) -> tuple:
        """
        Parse range string from HHR format.

        Args:
            range_str: Range string like "10-110" or "1-94(94)"

        Returns:
            (range_string, length) tuple
        """
        # Remove parenthetical length if present
        range_str = re.sub(r"\([^)]+\)$", "", range_str)

        # Extract start-end
        match = re.match(r"(\d+)-(\d+)", range_str)
        if match:
            start = int(match.group(1))
            end = int(match.group(2))
            length = end - start + 1
            return f"{start}-{end}", length
        else:
            return range_str, 0

    def calculate_coverage(self, hits: List[HHsearchHit], query_length: int) -> float:
        """
        Calculate query coverage from HHsearch hits.

        Args:
            hits: List of HHsearchHit objects
            query_length: Total query sequence length

        Returns:
            Coverage fraction (0.0-1.0)
        """
        if query_length == 0:
            return 0.0

        # Track covered positions
        covered = set()

        for hit in hits:
            # Parse query range
            for segment in hit.query_range.split(","):
                segment = segment.strip()
                if "-" in segment:
                    try:
                        start, end = map(int, segment.split("-"))
                        for pos in range(start, end + 1):
                            covered.add(pos)
                    except ValueError:
                        continue

        coverage = len(covered) / query_length
        return coverage


def main():
    """Command-line interface for testing"""
    import argparse

    parser = argparse.ArgumentParser(description="Parse HHsearch HHR files")
    parser.add_argument("hhr_file", help="Path to HHR file")
    parser.add_argument("--query-length", type=int, help="Query sequence length for coverage calculation")

    args = parser.parse_args()

    hhr_parser = HHsearchParser()

    hits = hhr_parser.parse_hhr(args.hhr_file)

    print(f"\nFound {len(hits)} HHsearch hits:\n")

    for hit in hits[:10]:  # Show top 10
        print(f"{hit.hit_number:3d}. {hit.hit_id:15s} Prob={hit.probability:5.1f}% "
              f"E={hit.evalue:.2e} Score={hit.score:6.1f} "
              f"Query={hit.query_range} Template={hit.template_range}")

    if args.query_length:
        coverage = hhr_parser.calculate_coverage(hits, args.query_length)
        print(f"\nQuery coverage: {coverage:.1%}")


if __name__ == "__main__":
    main()
