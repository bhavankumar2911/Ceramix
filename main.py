import subprocess
import re
import os
import glob

BLENDER_EXECUTABLE_PATH = "/Applications/Blender.app/Contents/MacOS/Blender"
INPUT_DESIGN_ROOT_DIRECTORY = "input/design"
REQUESTED_MODEL_COUNT_PER_VESSEL_TYPE = 5

VESSEL_TYPE_NAMES = ["ewer", "mug", "cup", "bottle"]


def derive_script_paths_for_vessel_type(vessel_type_name):
    return {
        "generate": f"generate_{vessel_type_name}_models.py",
        "skin": f"apply_skin_to_{vessel_type_name}_models.py",
        "render": f"render_textured_{vessel_type_name}s_to_png.py"}


def derive_directory_paths_for_vessel_type(vessel_type_name):
    return {
        "model": f"output/{vessel_type_name}/model",
        "design_root": f"output/{vessel_type_name}/design",
        "render_root": f"output/{vessel_type_name}/render"}


def patch_constant_in_script(script_path, constant_name, new_value):
    with open(script_path, "r") as script_file:
        script_contents = script_file.read()

    pattern_for_constant_assignment = re.compile(rf'^{constant_name}\s*=\s*".*?"', re.MULTILINE)
    replacement_assignment = f'{constant_name} = "{new_value}"'

    if not pattern_for_constant_assignment.search(script_contents):
        raise ValueError(f"Constant {constant_name} not found in {script_path}")

    patched_contents = pattern_for_constant_assignment.sub(replacement_assignment, script_contents, count=1)
    with open(script_path, "w") as script_file:
        script_file.write(patched_contents)


def run_blender_script(script_path, extra_arguments):
    full_command = [BLENDER_EXECUTABLE_PATH, "-b", "--python", script_path, "--"] + extra_arguments
    print(f"\nRunning: {' '.join(full_command)}")
    completed_process = subprocess.run(full_command)
    return completed_process.returncode == 0


def find_all_design_image_paths():
    return sorted(glob.glob(os.path.join(INPUT_DESIGN_ROOT_DIRECTORY, "**", "*.png"), recursive=True))


def derive_design_category_and_name(design_image_path):
    relative_path = os.path.relpath(design_image_path, INPUT_DESIGN_ROOT_DIRECTORY)
    path_parts = relative_path.split(os.sep)
    design_category = path_parts[0]
    design_name = os.path.splitext(path_parts[-1])[0]
    return design_category, design_name


def generate_models_for_vessel_type(vessel_type_name, script_paths, directory_paths):
    model_directory = directory_paths["model"]
    if os.path.isdir(model_directory) and len(glob.glob(os.path.join(model_directory, "*.blend"))) > 0:
        print(f"{vessel_type_name} models already exist in {model_directory}, skipping generation.")
        return True

    patch_constant_in_script(script_paths["generate"], "OUTPUT_DIRECTORY", model_directory)
    return run_blender_script(script_paths["generate"], [str(REQUESTED_MODEL_COUNT_PER_VESSEL_TYPE)])


def apply_skin_for_design(script_paths, directory_paths, design_image_path, design_output_directory):
    patch_constant_in_script(script_paths["skin"], "INPUT_DIRECTORY", directory_paths["model"])
    patch_constant_in_script(script_paths["skin"], "OUTPUT_DIRECTORY", design_output_directory)
    return run_blender_script(script_paths["skin"], [design_image_path])


def render_design(script_paths, design_output_directory, render_output_directory):
    patch_constant_in_script(script_paths["render"], "INPUT_DIRECTORY", design_output_directory)
    patch_constant_in_script(script_paths["render"], "OUTPUT_RENDER_DIRECTORY", render_output_directory)
    return run_blender_script(script_paths["render"], [])


def process_single_vessel_type(vessel_type_name, design_image_paths):
    script_paths = derive_script_paths_for_vessel_type(vessel_type_name)
    directory_paths = derive_directory_paths_for_vessel_type(vessel_type_name)

    for required_script_path in script_paths.values():
        if not os.path.isfile(required_script_path):
            print(f"Skipping vessel type '{vessel_type_name}': missing script {required_script_path}")
            return 0, 0

    generation_succeeded = generate_models_for_vessel_type(vessel_type_name, script_paths, directory_paths)
    if not generation_succeeded:
        print(f"Model generation failed for vessel type '{vessel_type_name}', skipping its designs.")
        return 0, len(design_image_paths)

    successfully_processed_count = 0
    for design_image_path in design_image_paths:
        design_category, design_name = derive_design_category_and_name(design_image_path)
        design_output_directory = os.path.join(directory_paths["design_root"], design_category, design_name)
        render_output_directory = os.path.join(directory_paths["render_root"], design_category, design_name)

        print(f"\n=== {vessel_type_name} / {design_category}/{design_name} ===")

        skin_succeeded = apply_skin_for_design(script_paths, directory_paths, os.path.abspath(design_image_path), design_output_directory)
        if not skin_succeeded:
            print(f"Skin application failed for {vessel_type_name} with design {design_category}/{design_name}.")
            continue

        render_succeeded = render_design(script_paths, design_output_directory, render_output_directory)
        if not render_succeeded:
            print(f"Rendering failed for {vessel_type_name} with design {design_category}/{design_name}.")
            continue

        successfully_processed_count += 1

    return successfully_processed_count, len(design_image_paths)


def run_full_pipeline_for_all_vessel_types():
    design_image_paths = find_all_design_image_paths()
    if not design_image_paths:
        print(f"No design images found under {INPUT_DESIGN_ROOT_DIRECTORY}")
        return

    print(f"Found {len(design_image_paths)} design images across {len(VESSEL_TYPE_NAMES)} vessel types.")

    overall_summary = {}
    for vessel_type_name in VESSEL_TYPE_NAMES:
        successfully_processed_count, total_design_count = process_single_vessel_type(vessel_type_name, design_image_paths)
        overall_summary[vessel_type_name] = (successfully_processed_count, total_design_count)

    print("\n=== Pipeline summary ===")
    for vessel_type_name, (successfully_processed_count, total_design_count) in overall_summary.items():
        print(f"{vessel_type_name}: {successfully_processed_count}/{total_design_count} designs processed")


run_full_pipeline_for_all_vessel_types()