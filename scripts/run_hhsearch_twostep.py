#!/usr/bin/env python3
"""
Run hhblits (profile building) + hhsearch (profile search) in two steps.

This script implements the two-pass HH-suite workflow:
1. hhblits: Build query profile against UniRef30 (staged in /tmp)
2. hhsearch: Search query profile against ECOD HMM database

Requires:
- UniRef30 database staged in /tmp/UniRef30_2023_02/
- ECOD HMM database in /data/ecod/database_versions/v291/ecod_v291
- Input FASTA in fastas/ directory
- Output directories: profiles/ and hhsearch/

Usage:
    python run_hhsearch_twostep.py <chain_id>

Example:
    python run_hhsearch_twostep.py 6o9f_A
"""
import sys
import subprocess
from pathlib import Path

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} CHAIN_ID")
        sys.exit(1)

    chain_id = sys.argv[1]

    # Paths
    fasta = Path(f"fastas/{chain_id}.fa")
    profile_a3m = Path(f"profiles/{chain_id}.a3m")
    hhsearch_hhr = Path(f"hhsearch/{chain_id}.hhr")

    # Ensure directories exist
    profile_a3m.parent.mkdir(exist_ok=True)
    hhsearch_hhr.parent.mkdir(exist_ok=True)

    if not fasta.exists():
        print(f"ERROR: FASTA not found: {fasta}")
        sys.exit(1)

    # Verify UniRef30 is staged in /tmp
    uniref_db = Path("/tmp/UniRef30_2023_02")
    if not uniref_db.exists():
        print(f"ERROR: UniRef30 not staged in /tmp on this node!")
        print(f"Expected: {uniref_db}")
        print(f"Please run staging script first: stage_uniref_to_nodes.sh")
        sys.exit(1)

    print(f"Processing {chain_id}...")
    print(f"  UniRef30 database: {uniref_db}")

    # STEP 1: hhblits - Build query profile against UniRef30
    print(f"  [1/2] Building profile with hhblits...")
    hhblits_cmd = [
        "/sw/apps/hh-suite/bin/hhblits",
        "-i", str(fasta),
        "-d", str(uniref_db),
        "-oa3m", str(profile_a3m),
        "-n", "2",          # 2 iterations
        "-e", "0.001",      # E-value threshold
        "-cpu", "4",        # 4 CPUs
        "-v", "0"           # Minimal verbosity
    ]

    try:
        result = subprocess.run(hhblits_cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        print(f"✗ hhblits timed out after 30 minutes")
        sys.exit(1)

    if result.returncode != 0:
        print(f"✗ hhblits failed: {result.stderr}")
        sys.exit(1)

    if not profile_a3m.exists():
        print(f"✗ Profile not created: {profile_a3m}")
        sys.exit(1)

    print(f"  ✓ Profile built: {profile_a3m}")

    # STEP 2: hhsearch - Search query profile against ECOD HMMs
    print(f"  [2/2] Searching ECOD with hhsearch...")
    hhsearch_cmd = [
        "/sw/apps/hh-suite/bin/hhsearch",
        "-i", str(profile_a3m),
        "-d", "/data/ecod/database_versions/v291/ecod_v291",
        "-o", str(hhsearch_hhr),
        "-e", "0.001",      # E-value threshold
        "-p", "50",         # Min probability
        "-Z", "5000",       # Max seqs in output alignment
        "-z", "1",          # Min number of seqs in output alignment
        "-b", "5000",       # Max number of alignments
        "-B", "5000",       # Max number of alignments in summary
        "-cpu", "4",        # 4 CPUs
        "-v", "0"           # Minimal verbosity
    ]

    try:
        result = subprocess.run(hhsearch_cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        print(f"✗ hhsearch timed out after 10 minutes")
        sys.exit(1)

    if result.returncode != 0:
        print(f"✗ hhsearch failed: {result.stderr}")
        sys.exit(1)

    if not hhsearch_hhr.exists():
        print(f"✗ HHR output not created: {hhsearch_hhr}")
        sys.exit(1)

    print(f"  ✓ HHsearch completed: {hhsearch_hhr}")
    print(f"✓ {chain_id} processed successfully")

if __name__ == "__main__":
    main()
