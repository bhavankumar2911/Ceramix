import subprocess
import sys
import os
import re
import glob

BLENDER_EXECUTABLE_PATH = "blender"
INPUT_DESIGN_ROOT_DIRECTORY = "input/design"
MUG_MODEL_OUTPUT_DIRECTORY = "output/mug/model"
MUG_DESIGN_OUTPUT_ROOT_DIRECTORY = "output/mug/design"
MUG_RENDER_OUTPUT_ROOT_DIRECTORY = "output/mug/render"

MUG_GENERATE_SCRIPT_PATH = "generate_mug_models.py"
MUG_SKIN_SCRIPT_PATH = "apply_skin_to_mug_models.py"
MUG_RENDER_SCRIPT_PATH = "render_textured_mugs_to_png.py"

def determine_blender_executable_path():
    """Extracts custom blender path if provided, cleaning up sys.argv."""
    global BLENDER_EXECUTABLE_PATH
    if "--blender-path" in sys.argv:
        path_flag_index = sys.argv.index("--blender-path")
        if path_flag_index + 1 < len(sys.argv):
            BLENDER_EXECUTABLE_PATH = sys.argv[path_flag_index + 1]
            del sys.argv[path_flag_index:path_flag_index + 2]

def read_requested_instance_count_from_command_arguments():
    if "--instances" in sys.argv:
        instances_flag_index = sys.argv.index("--instances")
        if instances_flag_index + 1 < len(sys.argv):
            return int(sys.argv[instances_flag_index + 1])
    return 20


def read_requested_design_category_from_command_arguments():
    if "--design-category" in sys.argv:
        design_category_flag_index = sys.argv.index("--design-category")
        if design_category_flag_index + 1 < len(sys.argv):
            return sys.argv[design_category_flag_index + 1]
    return None


def run_blender_script_with_arguments(script_path, script_arguments):
    full_command = [BLENDER_EXECUTABLE_PATH, "-b", "--python", script_path, "--"] + script_arguments
    print(f"\nRunning: {' '.join(full_command)}")
    completed_process = subprocess.run(full_command)
    return completed_process.returncode == 0


def find_all_design_image_paths(requested_design_category):
    if requested_design_category is None:
        return sorted(glob.glob(os.path.join(INPUT_DESIGN_ROOT_DIRECTORY, "**", "*.png"), recursive=True))
    return sorted(glob.glob(os.path.join(INPUT_DESIGN_ROOT_DIRECTORY, requested_design_category, "*.png")))


def derive_design_category_and_name(design_image_path):
    relative_path = os.path.relpath(design_image_path, INPUT_DESIGN_ROOT_DIRECTORY)
    path_parts = relative_path.split(os.sep)
    design_category = path_parts[0]
    design_name = os.path.splitext(path_parts[-1])[0]
    return design_category, design_name


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


def ensure_mug_models_are_generated(requested_instance_count):
    already_generated_blend_files = glob.glob(os.path.join(MUG_MODEL_OUTPUT_DIRECTORY, "*.blend"))
    if os.path.isdir(MUG_MODEL_OUTPUT_DIRECTORY) and len(already_generated_blend_files) > 0:
        print(f"Mug models already exist in {MUG_MODEL_OUTPUT_DIRECTORY}, skipping generation.")
        return True
    patch_constant_in_script(MUG_GENERATE_SCRIPT_PATH, "OUTPUT_DIRECTORY", MUG_MODEL_OUTPUT_DIRECTORY)
    return run_blender_script_with_arguments(
        MUG_GENERATE_SCRIPT_PATH, [str(requested_instance_count)])


def process_single_design_through_skin_and_render(design_image_path):
    design_category, design_name = derive_design_category_and_name(design_image_path)
    design_output_directory = os.path.join(MUG_DESIGN_OUTPUT_ROOT_DIRECTORY, design_category, design_name)
    render_output_directory = os.path.join(MUG_RENDER_OUTPUT_ROOT_DIRECTORY, design_category, design_name)

    print(f"\n=== mug / {design_category}/{design_name} ===")

    patch_constant_in_script(MUG_SKIN_SCRIPT_PATH, "INPUT_DIRECTORY", MUG_MODEL_OUTPUT_DIRECTORY)
    patch_constant_in_script(MUG_SKIN_SCRIPT_PATH, "OUTPUT_DIRECTORY", design_output_directory)
    skin_succeeded = run_blender_script_with_arguments(
        MUG_SKIN_SCRIPT_PATH, [os.path.abspath(design_image_path)])
    if not skin_succeeded:
        print(f"Skin application failed for design {design_category}/{design_name}.")
        return False

    patch_constant_in_script(MUG_RENDER_SCRIPT_PATH, "INPUT_DIRECTORY", design_output_directory)
    patch_constant_in_script(MUG_RENDER_SCRIPT_PATH, "OUTPUT_RENDER_DIRECTORY", render_output_directory)
    render_succeeded = run_blender_script_with_arguments(MUG_RENDER_SCRIPT_PATH, [])
    if not render_succeeded:
        print(f"Rendering failed for design {design_category}/{design_name}.")
        return False

    return True


def run_full_mug_pipeline():
    determine_blender_executable_path()

    requested_instance_count = read_requested_instance_count_from_command_arguments()
    requested_design_category = read_requested_design_category_from_command_arguments()

    design_image_paths = find_all_design_image_paths(requested_design_category)
    if not design_image_paths:
        if requested_design_category is None:
            print(f"No design images found under {INPUT_DESIGN_ROOT_DIRECTORY}")
        else:
            print(f"No design images found under {os.path.join(INPUT_DESIGN_ROOT_DIRECTORY, requested_design_category)}")
        return

    print(f"Found {len(design_image_paths)} design images.")
    print(f"Generating {requested_instance_count} mug instances.")

    generation_succeeded = ensure_mug_models_are_generated(requested_instance_count)
    if not generation_succeeded:
        print("Mug model generation failed, aborting pipeline.")
        return

    successfully_processed_count = 0
    for design_image_path in design_image_paths:
        design_succeeded = process_single_design_through_skin_and_render(design_image_path)
        if design_succeeded:
            successfully_processed_count += 1

    print(f"\nPipeline complete. Successfully processed {successfully_processed_count}/{len(design_image_paths)} designs.")


run_full_mug_pipeline()