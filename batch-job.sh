#!/bin/bash -l
#
#SBATCH --gres=gpu:rtx3080:1
#SBATCH --partition=rtx3080
#SBATCH --time=01:00:00
#SBATCH --export=NONE
#SBATCH --job-name=cup_scribble.batch-job

unset SLURM_EXPORT_ENV

module load python
python pipeline_cup.py  --instances 20 --design-category scribble