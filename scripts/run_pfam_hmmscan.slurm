#!/bin/bash
#SBATCH --job-name=pfam_domains
#SBATCH --cpus-per-task=16
#SBATCH --mem=16G
#SBATCH --time=2:00:00
#SBATCH --partition=96GB
#SBATCH --output=slurm_logs/pfam_%a.out
#SBATCH --error=slurm_logs/pfam_%a.err

# Pfam v38.1 hmmscan for pyecod_prod auto-accessioned domains
# Note: --array parameter set by submit script based on chunk count

set -euo pipefail

# Configuration
HMMER_BIN="/data/ecod/hmmer-3.1b2/binaries"
PFAM_DB="${HOME}/data/pfam/v38.1/Pfam-A.hmm"
BATCH_DIR="${BATCH_DIR:-/data/ecod/pdb_updates/batches/ecod_q4_2025_q1_2026}"
CHUNK_DIR="${BATCH_DIR}/domains/chunks"
RESULT_DIR="${BATCH_DIR}/pfam"

mkdir -p "$RESULT_DIR"

# Array task configuration
CHUNK_ID=$(printf "%04d" ${SLURM_ARRAY_TASK_ID})
INPUT_FASTA="${CHUNK_DIR}/chunk_${CHUNK_ID}.fasta"
OUTPUT_BASE="${RESULT_DIR}/hmmscan_${CHUNK_ID}"

# Verify input exists
if [ ! -f "$INPUT_FASTA" ]; then
    echo "ERROR: Input file not found: $INPUT_FASTA"
    exit 1
fi

# Count sequences in this chunk
NUM_SEQS=$(grep -c '^>' "$INPUT_FASTA")

echo "========================================================================"
echo "Pfam v38.1 hmmscan - pyecod_prod Batch"
echo "========================================================================"
echo "Start time: $(date)"
echo "Node: $(hostname)"
echo "CPUs: ${SLURM_CPUS_PER_TASK}"
echo "Batch dir: $BATCH_DIR"
echo "Input: $INPUT_FASTA"
echo "Sequences: $NUM_SEQS"
echo "Output: ${OUTPUT_BASE}.domtblout"
echo ""

# Run hmmscan with GA (gathering) cutoffs
# --cut_ga uses Pfam curated thresholds for each family
# --noali suppresses alignment output (not needed, saves space)
echo "Running hmmscan..."
time ${HMMER_BIN}/hmmscan \
    --cpu ${SLURM_CPUS_PER_TASK} \
    --cut_ga \
    --tblout ${OUTPUT_BASE}.tblout \
    --domtblout ${OUTPUT_BASE}.domtblout \
    --noali \
    ${PFAM_DB} \
    ${INPUT_FASTA} > ${OUTPUT_BASE}.out

echo ""
echo "Hmmscan completed successfully"
echo "End time: $(date)"
echo ""

# Report hit statistics
TOTAL_HITS=$(grep -cv '^#' ${OUTPUT_BASE}.tblout 2>/dev/null || echo "0")
DOM_HITS=$(grep -cv '^#' ${OUTPUT_BASE}.domtblout 2>/dev/null || echo "0")

echo "Results:"
echo "  Total sequence hits: $TOTAL_HITS"
echo "  Total domain hits: $DOM_HITS"
echo ""

# Compress main output file (keep tables uncompressed for parsing)
gzip -f ${OUTPUT_BASE}.out

echo "Done!"
