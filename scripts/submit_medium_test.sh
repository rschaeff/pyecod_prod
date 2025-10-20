#!/bin/bash
#SBATCH --job-name=pyecod_medium_test
#SBATCH --partition=96GB
#SBATCH --time=4:00:00
#SBATCH --mem=4G
#SBATCH --cpus-per-task=1
#SBATCH --output=/data/ecod/test_batches/medium_test_%j.out
#SBATCH --error=/data/ecod/test_batches/medium_test_%j.err

# Medium-scale production test (100 chains)
# This script runs the orchestration workflow on SLURM
# The workflow itself will submit additional SLURM jobs for BLAST and HHsearch

echo "========================================================================"
echo "pyECOD Medium-Scale Production Test"
echo "========================================================================"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "Start time: $(date)"
echo ""

# Set up environment
source /sw/apps/Anaconda3-2023.09-0/etc/profile.d/conda.sh
conda activate dpam
export PYTHONPATH=/home/rschaeff/dev/pyecod_prod/src:$PYTHONPATH
export PATH=/sw/apps/ncbi-blast-2.15.0+/bin:/sw/apps/hh-suite/bin:$PATH

# Verify environment
echo "Verifying environment..."
python -c "from pyecod_prod.batch.weekly_batch import WeeklyBatch; print('✓ Python imports OK')"
which blastp || echo "⚠ blastp not in PATH"
which hhsearch || echo "⚠ hhsearch not in PATH"
ls -lh /home/rschaeff/.local/bin/pyecod-mini || echo "⚠ pyecod-mini not found"
echo ""

# Run the test
cd /home/rschaeff/dev/pyecod_prod
python -u scripts/run_medium_test.py

exit_code=$?

echo ""
echo "========================================================================"
echo "Job completed with exit code: $exit_code"
echo "End time: $(date)"
echo "========================================================================"

exit $exit_code
