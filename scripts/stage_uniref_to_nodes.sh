#!/bin/bash
#
# Stage UniRef30 database to specific nodes with large /tmp
#
# This script copies the UniRef30 database from shared storage to /tmp on selected
# compute nodes. This is necessary because hhblits requires fast local disk access
# to the large UniRef30 database (~261GB uncompressed).
#
# Usage:
#   ./stage_uniref_to_nodes.sh [node1,node2,node3,...]
#
# Example:
#   ./stage_uniref_to_nodes.sh leda20,leda21,leda22,leda23
#
# If no nodes specified, uses default list (must have ≥300GB /tmp)
#

# Parse arguments
if [ $# -gt 0 ]; then
    NODE_LIST="$1"
else
    # Default nodes (update after checking /tmp capacity with check_node_tmp.sh)
    # These nodes should have ≥300GB /tmp space
    NODE_LIST="leda20,leda21,leda22,leda23"
    echo "Using default node list: $NODE_LIST"
fi

SOURCE="/home/rschaeff/search_libs/UniRef30_2023_02_hhsuite.tar.gz"
STAGED_MARKER_DIR="/data/ecod/pdb_updates/backfill_2023_2025/blast/staging"

# Create staging marker directory
mkdir -p "${STAGED_MARKER_DIR}"

# Convert comma-separated list to array
IFS=',' read -ra NODES <<< "$NODE_LIST"

echo "=========================================="
echo "UniRef30 Database Staging"
echo "=========================================="
echo "Source: ${SOURCE}"
echo "Target nodes: ${NODE_LIST}"
echo "Nodes to stage: ${#NODES[@]}"
echo ""

for NODE in "${NODES[@]}"; do
    echo "Submitting staging job for ${NODE}..."

    JOB_ID=$(sbatch --parsable --nodelist=${NODE} --partition=96GB --time=2:00:00 --mem=8GB \
        --job-name=stage_uniref_${NODE} \
        --output="${STAGED_MARKER_DIR}/stage_${NODE}.log" \
        --error="${STAGED_MARKER_DIR}/stage_${NODE}.err" \
        <<EOF
#!/bin/bash

echo "=========================================="
echo "Staging UniRef30 to ${NODE}"
echo "=========================================="
echo "Node: \$(hostname)"
echo "Start time: \$(date)"
echo ""

# Check current /tmp space
echo "Current /tmp space:"
df -h /tmp
echo ""

# Copy compressed tarball to /tmp (66GB, ~15 minutes)
echo "[1/2] Copying compressed database to /tmp..."
if [ -f "/tmp/UniRef30_2023_02_hhsuite.tar.gz" ]; then
    echo "  Database already exists in /tmp, skipping copy"
else
    cp -v "${SOURCE}" /tmp/UniRef30_2023_02_hhsuite.tar.gz
    if [ \$? -ne 0 ]; then
        echo "ERROR: Failed to copy database to /tmp"
        exit 1
    fi
    echo "  ✓ Copy complete"
fi
echo ""

# Extract (~261GB uncompressed, ~30-60 minutes)
echo "[2/2] Extracting database..."
cd /tmp
if [ -d "/tmp/UniRef30_2023_02" ] || [ -f "/tmp/UniRef30_2023_02_a3m.ffdata" ]; then
    echo "  Database already extracted, skipping extraction"
else
    tar -xzf UniRef30_2023_02_hhsuite.tar.gz
    if [ \$? -ne 0 ]; then
        echo "ERROR: Failed to extract database"
        exit 1
    fi
    echo "  ✓ Extraction complete"
fi
echo ""

# Verify extraction
echo "Verifying staged files:"
ls -lh /tmp/UniRef30_2023_02_*.ff* 2>/dev/null || {
    echo "ERROR: Database files not found after extraction"
    exit 1
}
echo ""

# Write staging completion marker
echo "\$(hostname)" > "${STAGED_MARKER_DIR}/${NODE}_staged.txt"
echo "\$(date)" >> "${STAGED_MARKER_DIR}/${NODE}_staged.txt"

echo "/tmp space after staging:"
df -h /tmp
echo ""

echo "=========================================="
echo "✓ UniRef30 staged successfully on ${NODE}"
echo "End time: \$(date)"
echo "=========================================="
EOF
)

    echo "  Job ID: ${JOB_ID}"
    echo "  Log: ${STAGED_MARKER_DIR}/stage_${NODE}.log"
    echo ""
done

echo "=========================================="
echo "All staging jobs submitted"
echo "=========================================="
echo ""
echo "Monitor staging progress:"
echo "  squeue -u \$USER --name=stage_uniref*"
echo ""
echo "Check staging status:"
echo "  ls -lh ${STAGED_MARKER_DIR}/*_staged.txt"
echo ""
echo "View staging logs:"
echo "  tail -f ${STAGED_MARKER_DIR}/stage_*.log"
