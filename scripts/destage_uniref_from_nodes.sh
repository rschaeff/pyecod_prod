#!/bin/bash
#
# Destage (cleanup) UniRef30 database from compute nodes
#
# This script removes the UniRef30 database from /tmp on nodes after all
# HHsearch jobs have completed. This frees up ~261GB of /tmp space per node.
#
# Prerequisites:
#   1. All HHsearch jobs must be completed
#   2. Verify with: squeue -u $USER --name=hhsearch*
#
# Usage:
#   ./destage_uniref_from_nodes.sh [node_list]
#
# Example:
#   ./destage_uniref_from_nodes.sh leda20,leda21,leda22,leda23
#

# Parse arguments
if [ $# -gt 0 ]; then
    NODE_LIST="$1"
else
    # Default: Use nodes that have staging markers
    STAGING_DIR="staging"
    if [ -d "${STAGING_DIR}" ]; then
        NODE_LIST=$(ls ${STAGING_DIR}/*_staged.txt 2>/dev/null | \
            sed 's/.*\/\(.*\)_staged.txt/\1/' | \
            tr '\n' ',' | \
            sed 's/,$//')
    fi

    if [ -z "${NODE_LIST}" ]; then
        echo "ERROR: No staged nodes found"
        echo "No destaging needed"
        exit 0
    fi

    echo "Using staged nodes: ${NODE_LIST}"
fi

# Convert comma-separated list to array
IFS=',' read -ra NODES <<< "$NODE_LIST"

echo "=========================================="
echo "UniRef30 Database Destaging"
echo "=========================================="
echo "Nodes to destage: ${#NODES[@]}"
echo "Node list: ${NODE_LIST}"
echo ""

# Warning
echo "WARNING: This will remove ~261GB of data from /tmp on each node"
echo "Ensure all HHsearch jobs are complete before proceeding"
echo ""
read -p "Continue with destaging? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Destaging cancelled"
    exit 0
fi

STAGED_MARKER_DIR="staging"

for NODE in "${NODES[@]}"; do
    echo "Submitting destaging job for ${NODE}..."

    JOB_ID=$(sbatch --parsable --nodelist=${NODE} --partition=96GB --time=0:30:00 --mem=2GB \
        --job-name=destage_uniref_${NODE} \
        --output="${STAGED_MARKER_DIR}/destage_${NODE}.log" \
        --error="${STAGED_MARKER_DIR}/destage_${NODE}.err" \
        <<EOF
#!/bin/bash

echo "=========================================="
echo "Destaging UniRef30 from ${NODE}"
echo "=========================================="
echo "Node: \$(hostname)"
echo "Start time: \$(date)"
echo ""

# Show /tmp space before cleanup
echo "/tmp space before cleanup:"
df -h /tmp
echo ""

# Remove UniRef30 files
echo "Removing UniRef30 files from /tmp..."
rm -f /tmp/UniRef30_2023_02_hhsuite.tar.gz
rm -f /tmp/UniRef30_2023_02_*.ff*

# Remove any hhblits temporary files
rm -rf /tmp/hhblits_*

echo "Cleanup complete"
echo ""

# Show /tmp space after cleanup
echo "/tmp space after cleanup:"
df -h /tmp
echo ""

# Remove staging marker
rm -f "${STAGED_MARKER_DIR}/${NODE}_staged.txt"

echo "=========================================="
echo "✓ UniRef30 destaged from ${NODE}"
echo "End time: \$(date)"
echo "=========================================="
EOF
)

    echo "  Job ID: ${JOB_ID}"
    echo "  Log: ${STAGED_MARKER_DIR}/destage_${NODE}.log"
    echo ""
done

echo "=========================================="
echo "All destaging jobs submitted"
echo "=========================================="
echo ""
echo "Monitor destaging progress:"
echo "  squeue -u \$USER --name=destage_uniref*"
echo ""
echo "Verify destaging complete:"
echo "  ls ${STAGED_MARKER_DIR}/*_staged.txt 2>/dev/null || echo 'All nodes destaged'"
echo ""
echo "View destaging logs:"
echo "  tail -f ${STAGED_MARKER_DIR}/destage_*.log"
