#!/bin/bash -l
#
#SBATCH --gres=gpu:rtx3080:1
#SBATCH --partition=rtx3080
#SBATCH --time=00:30:00
#SBATCH --export=NONE
#SBATCH --job-name=btcv_batch-job

unset SLURM_EXPORT_ENV

module load blender
blender -b --python render_textured_cups_to_png.py