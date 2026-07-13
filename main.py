import subprocess
import sys

VESSEL_TYPE_PIPELINE_SCRIPT_PATHS = [
    "pipeline_bottle.py",
    "pipeline_mug.py",
    "pipeline_cup.py",
    "pipeline_pitcher.py",
    "pipeline_bowl.py"]

def run_vessel_pipeline_script(pipeline_script_path, forwarded_arguments):
    full_command = ["python3", pipeline_script_path] + forwarded_arguments
    print(f"\n{'=' * 60}\nRunning: {' '.join(full_command)}\n{'=' * 60}")
    completed_process = subprocess.run(full_command)
    return completed_process.returncode == 0

def run_all_vessel_pipelines():
    forwarded_arguments = sys.argv[1:]

    overall_summary = {}
    for pipeline_script_path in VESSEL_TYPE_PIPELINE_SCRIPT_PATHS:
        vessel_type_name = pipeline_script_path.replace("pipeline_", "").replace(".py", "")
        pipeline_succeeded = run_vessel_pipeline_script(pipeline_script_path, forwarded_arguments)
        overall_summary[vessel_type_name] = pipeline_succeeded

    print(f"\n{'=' * 60}\nAll vessel pipelines complete.\n{'=' * 60}")
    for vessel_type_name, pipeline_succeeded in overall_summary.items():
        status_label = "succeeded" if pipeline_succeeded else "failed"
        print(f"{vessel_type_name}: {status_label}")

run_all_vessel_pipelines()