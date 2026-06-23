import bpy
import math
import os
from pathlib import Path
from mathutils import Vector

VESSEL_TYPES = ["ewer", "mug", "cup", "bottle"]
INPUT_BASE_DIRECTORY = "output"
OUTPUT_RENDER_DIRECTORY = "output/renders"
RENDER_RESOLUTION_X = 512
RENDER_RESOLUTION_Y = 512
RENDER_SAMPLES = 128
CAMERA_DISTANCE_FROM_CENTER = 2.5
CAMERA_HEIGHT_FRACTION = 0.55
CAMERA_ROTATION_X_DEGREES = 65.0
CAMERA_ROTATION_Z_DEGREES = 45.0


def remove_all_scene_objects_except_lights():
    for obj in list(bpy.context.scene.objects):
        if obj.type != 'LIGHT':
            bpy.data.objects.remove(obj, do_unlink=True)
    for orphan_mesh in list(bpy.data.meshes):
        if orphan_mesh.users == 0:
            bpy.data.meshes.remove(orphan_mesh)


def setup_render_settings(output_file_path):
    render_settings = bpy.context.scene.render
    render_settings.engine = 'CYCLES'
    render_settings.filepath = output_file_path
    render_settings.resolution_x = RENDER_RESOLUTION_X
    render_settings.resolution_y = RENDER_RESOLUTION_Y
    render_settings.image_settings.file_format = 'PNG'
    bpy.context.scene.cycles.samples = RENDER_SAMPLES
    bpy.context.scene.cycles.device = 'GPU'


def enable_gpu_rendering():
    try:
        cycles_preferences = bpy.context.preferences.addons['cycles'].preferences
        cycles_preferences.compute_device_type = 'METAL'
        cycles_preferences.get_devices()
        for compute_device in cycles_preferences.devices:
            compute_device.use = True
    except Exception as error:
        print(f"Metal GPU unavailable ({error}), will render on CPU.")
        return False
    return True


def position_camera(vessel_object):
    bpy.ops.object.camera_add(location=(0.0, 0.0, 0.0))
    camera_object = bpy.context.active_object
    camera_object.name = "RenderCamera"

    bounding_box_corners = [Vector(corner) for corner in vessel_object.bound_box]
    bounding_box_center = sum(bounding_box_corners, Vector((0, 0, 0))) / len(bounding_box_corners)
    bounding_box_size_z = max(corner.z for corner in bounding_box_corners) - min(corner.z for corner in bounding_box_corners)

    camera_height = bounding_box_center.z + bounding_box_size_z * CAMERA_HEIGHT_FRACTION
    camera_x = CAMERA_DISTANCE_FROM_CENTER * math.cos(math.radians(CAMERA_ROTATION_Z_DEGREES))
    camera_y = CAMERA_DISTANCE_FROM_CENTER * math.sin(math.radians(CAMERA_ROTATION_Z_DEGREES))
    camera_object.location = (camera_x, camera_y, camera_height)

    direction_to_target = (bounding_box_center - camera_object.location).normalized()
    camera_object.rotation_euler = direction_to_target.to_track_quat('-Z', 'Y').to_euler()

    bpy.context.scene.camera = camera_object


def render_and_save_vessel(blend_file_path, output_png_path):
    remove_all_scene_objects_except_lights()
    bpy.ops.wm.open_mainfile(filepath=blend_file_path)

    vessel_objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not vessel_objects:
        print(f"  No mesh objects found in {blend_file_path}, skipping.")
        return False

    primary_vessel_object = vessel_objects[0]
    position_camera(primary_vessel_object)
    setup_render_settings(output_png_path)
    bpy.ops.render.render(write_still=True)
    return True


def find_all_blend_files_for_vessel_type(vessel_type):
    vessel_directory = os.path.join(INPUT_BASE_DIRECTORY, f"{vessel_type}_models")
    if not os.path.isdir(vessel_directory):
        return []
    blend_files = sorted([
        os.path.join(vessel_directory, filename)
        for filename in os.listdir(vessel_directory)
        if filename.endswith('.blend')])
    return blend_files


def batch_render_all_vessels():
    absolute_output_directory = os.path.abspath(OUTPUT_RENDER_DIRECTORY)
    os.makedirs(absolute_output_directory, exist_ok=True)

    try:
        enable_gpu_rendering()
        print("GPU rendering enabled.")
    except Exception as error:
        print(f"Warning: GPU setup failed ({error}), will use CPU fallback.")

    total_rendered_count = 0
    for vessel_type in VESSEL_TYPES:
        blend_files = find_all_blend_files_for_vessel_type(vessel_type)
        if not blend_files:
            print(f"No .blend files found for vessel type '{vessel_type}'")
            continue

        print(f"Rendering {len(blend_files)} {vessel_type} models...")
        for blend_file_index, blend_file_path in enumerate(blend_files):
            model_filename = os.path.basename(blend_file_path)
            model_base_name = os.path.splitext(model_filename)[0]
            output_png_filename = f"{model_base_name}.png"
            output_png_path = os.path.join(absolute_output_directory, output_png_filename)

            try:
                absolute_blend_file_path = os.path.abspath(blend_file_path)
                success = render_and_save_vessel(absolute_blend_file_path, output_png_path)
                if success:
                    print(f"  [{blend_file_index + 1}/{len(blend_files)}] Rendered {model_base_name} → {output_png_filename}")
                    total_rendered_count += 1
            except Exception as error:
                print(f"  Error rendering {blend_file_path}: {error}")

    print(f"\nBatch render complete. Total rendered: {total_rendered_count}")


batch_render_all_vessels()