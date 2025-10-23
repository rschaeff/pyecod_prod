#!/bin/bash
#
# Submit HHsearch jobs to nodes with staged UniRef30 database
#
# This script submits hhblits + hhsearch jobs ONLY to nodes where the UniRef30
# database has been staged in /tmp. Jobs are submitted in batches to avoid
# exceeding SLURM array limits (max 1000 per array).
#
# Prerequisites:
#   1. Run stage_uniref_to_nodes.sh first
#   2. Verify staging completed: ls staging/*_staged.txt
#   3. Ensure hhsearch_targets.txt exists with chains needing HHsearch
#
# Usage:
#   ./submit_hhsearch_staged.sh [node_list]
#
# Example:
#   ./submit_hhsearch_staged.sh leda20,leda21,leda22,leda23
#

# Parse arguments
if [ $# -gt 0 ]; then
    STAGED_NODES="$1"
else
    # Default: Use nodes that have staging markers
    STAGING_DIR="staging"
    if [ -d "${STAGING_DIR}" ]; then
        STAGED_NODES=$(ls ${STAGING_DIR}/*_staged.txt 2>/dev/null | \
            sed 's/.*\/\(.*\)_staged.txt/\1/' | \
            tr '\n' ',' | \
            sed 's/,$//')
    fi

    if [ -z "${STAGED_NODES}" ]; then
        echo "ERROR: No staged nodes found"
        echo "Please run stage_uniref_to_nodes.sh first"
        exit 1
    fi

    echo "Using staged nodes: ${STAGED_NODES}"
fi

# Configuration
TARGETS_FILE="hhsearch_targets.txt"
TOTAL_CHAINS=$(wc -l < "${TARGETS_FILE}")
BATCH_SIZE=1000
ARRAY_LIMIT=500

# Validate targets file exists
if [ ! -f "${TARGETS_FILE}" ]; then
    echo "ERROR: ${TARGETS_FILE} not found"
    echo "Please generate it first with the coverage analysis script"
    exit 1
fi

# Create output directories
mkdir -p profiles hhsearch slurm_logs

echo "=========================================="
echo "HHsearch Job Submission"
echo "=========================================="
echo "Targets file: ${TARGETS_FILE}"
echo "Total chains: ${TOTAL_CHAINS}"
echo "Staged nodes: ${STAGED_NODES}"
echo "Batch size: ${BATCH_SIZE}"
echo "Array concurrency limit: ${ARRAY_LIMIT}"
echo ""

# Calculate number of batches
NUM_BATCHES=$(( (TOTAL_CHAINS + BATCH_SIZE - 1) / BATCH_SIZE ))
echo "Will submit ${NUM_BATCHES} batches"
echo ""

# Submit batches
for ((offset=0; offset<TOTAL_CHAINS; offset+=BATCH_SIZE)); do
    remaining=$((TOTAL_CHAINS - offset))
    current_batch=$((remaining < BATCH_SIZE ? remaining : BATCH_SIZE))
    batch_num=$((offset / BATCH_SIZE + 1))

    echo "----------------------------------------"
    echo "Batch ${batch_num}/${NUM_BATCHES}: offset=${offset}, size=${current_batch}"

    JOB_ID=$(sbatch --parsable <<EOF
#!/bin/bash
#SBATCH --job-name=hhsearch_${offset}
#SBATCH --output=slurm_logs/hhsearch_${offset}_%A_%a.out
#SBATCH --error=slurm_logs/hhsearch_${offset}_%A_%a.err
#SBATCH --array=0-$((current_batch-1))%${ARRAY_LIMIT}
#SBATCH --nodelist=${STAGED_NODES}
#SBATCH --partition=96GB
#SBATCH --time=4:00:00
#SBATCH --mem=16GB
#SBATCH --cpus-per-task=4

# Get chain ID from targets list
LINE_NUM=\$((${offset} + SLURM_ARRAY_TASK_ID + 1))
CHAIN_ID=\$(sed -n "\${LINE_NUM}p" ${TARGETS_FILE})

if [ -z "\${CHAIN_ID}" ]; then
    echo "ERROR: Could not read chain ID from line \${LINE_NUM}"
    exit 1
fi

echo "=========================================="
echo "HHsearch Job"
echo "=========================================="
echo "Node: \$(hostname)"
echo "Chain ID: \${CHAIN_ID}"
echo "Start time: \$(date)"
echo ""

# Verify UniRef30 is staged on this node
if [ ! -d /tmp/UniRef30_2023_02 ]; then
    echo "ERROR: UniRef30 not found in /tmp on \$(hostname)"
    echo "Please run staging script first"
    exit 1
fi

# Run two-step HHsearch (hhblits + hhsearch)
python run_hhsearch_twostep.py "\${CHAIN_ID}"
EXIT_CODE=\$?

echo ""
echo "End time: \$(date)"
echo "Exit code: \${EXIT_CODE}"
echo "=========================================="

exit \${EXIT_CODE}
EOF
)

    echo "  Job ID: ${JOB_ID}"
    echo "  Chains: ${offset} - $((offset + current_batch - 1))"

    # Brief pause to avoid overwhelming scheduler
    sleep 2
done

echo ""
echo "=========================================="
echo "All batches submitted"
echo "=========================================="
echo ""
echo "Monitor job status:"
echo "  squeue -u \$USER --name=hhsearch*"
echo ""
echo "Check progress:"
echo "  ls profiles/*.a3m | wc -l  # Profiles built"
echo "  ls hhsearch/*.hhr | wc -l  # HHsearch completed"
echo ""
echo "View recent logs:"
echo "  tail -f slurm_logs/hhsearch_*.out"
