import bpy
import math
import os
import glob
from mathutils import Vector

INPUT_DIRECTORY = "output/bottle_models_textured"
OUTPUT_RENDER_DIRECTORY = "output/bottle_renders"
RENDER_RESOLUTION_X = 512
RENDER_RESOLUTION_Y = 512
RENDER_SAMPLES = 128
CAMERA_DISTANCE_MULTIPLIER = 2.4
CAMERA_AZIMUTH_DEGREES = 35.0
CAMERA_ELEVATION_DEGREES = 8.0
SUN_LIGHT_ENERGY = 3.5
WHITE_BACKGROUND_STRENGTH = 1.4


def remove_all_scene_objects():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for orphan_mesh in list(bpy.data.meshes):
        if orphan_mesh.users == 0:
            bpy.data.meshes.remove(orphan_mesh)


def make_object_the_only_active_selection(target_object):
    bpy.ops.object.select_all(action='DESELECT')
    target_object.select_set(True)
    bpy.context.view_layer.objects.active = target_object


def find_primary_vessel_mesh_object():
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not mesh_objects:
        return None
    return max(mesh_objects, key=lambda obj: len(obj.data.vertices))


def compute_vessel_bounding_dimensions(vessel_object):
    world_space_corners = [vessel_object.matrix_world @ Vector(corner) for corner in vessel_object.bound_box]
    minimum_x = min(corner.x for corner in world_space_corners)
    maximum_x = max(corner.x for corner in world_space_corners)
    minimum_y = min(corner.y for corner in world_space_corners)
    maximum_y = max(corner.y for corner in world_space_corners)
    minimum_z = min(corner.z for corner in world_space_corners)
    maximum_z = max(corner.z for corner in world_space_corners)
    bounding_center = Vector((
        (minimum_x + maximum_x) / 2.0,
        (minimum_y + maximum_y) / 2.0,
        (minimum_z + maximum_z) / 2.0))
    bounding_height = maximum_z - minimum_z
    bounding_width = max(maximum_x - minimum_x, maximum_y - minimum_y)
    return bounding_center, bounding_height, bounding_width


def setup_white_world_background():
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("VesselWorld")
        bpy.context.scene.world = world
    world.use_nodes = True
    background_node = world.node_tree.nodes.get("Background")
    if background_node is not None:
        background_node.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        background_node.inputs["Strength"].default_value = WHITE_BACKGROUND_STRENGTH


def add_portrait_camera(bounding_center, bounding_height, bounding_width):
    framing_dimension = max(bounding_height, bounding_width)
    camera_distance = framing_dimension * CAMERA_DISTANCE_MULTIPLIER

    azimuth_radians = math.radians(CAMERA_AZIMUTH_DEGREES)
    elevation_radians = math.radians(CAMERA_ELEVATION_DEGREES)

    camera_offset_x = camera_distance * math.cos(elevation_radians) * math.sin(azimuth_radians)
    camera_offset_y = -camera_distance * math.cos(elevation_radians) * math.cos(azimuth_radians)
    camera_offset_z = camera_distance * math.sin(elevation_radians)

    bpy.ops.object.camera_add(location=(
        bounding_center.x + camera_offset_x,
        bounding_center.y + camera_offset_y,
        bounding_center.z + camera_offset_z))
    camera_object = bpy.context.active_object
    camera_object.name = "PortraitCamera"

    look_at_target = Vector((bounding_center.x, bounding_center.y, bounding_center.z))
    direction_to_target = (look_at_target - camera_object.location).normalized()
    camera_object.rotation_euler = direction_to_target.to_track_quat('-Z', 'Y').to_euler()

    camera_object.data.lens = 80.0
    camera_object.data.clip_start = 0.001
    camera_object.data.clip_end = 1000.0

    bpy.context.scene.camera = camera_object
    return camera_object


def add_top_right_sun_light(bounding_center, bounding_height):
    sun_position = Vector((
        bounding_center.x + bounding_height * 1.5,
        bounding_center.y - bounding_height * 1.0,
        bounding_center.z + bounding_height * 2.0))
    bpy.ops.object.light_add(type='SUN', location=sun_position)
    sun_light_object = bpy.context.active_object
    sun_light_object.name = "TopRightSun"
    sun_light_object.data.energy = SUN_LIGHT_ENERGY
    sun_light_object.data.angle = math.radians(3.0)

    direction_to_center = (bounding_center - sun_position).normalized()
    sun_light_object.rotation_euler = direction_to_center.to_track_quat('-Z', 'Y').to_euler()
    return sun_light_object


def setup_render_settings(output_file_path):
    render_settings = bpy.context.scene.render
    render_settings.engine = 'CYCLES'
    render_settings.filepath = output_file_path
    render_settings.resolution_x = RENDER_RESOLUTION_X
    render_settings.resolution_y = RENDER_RESOLUTION_Y
    render_settings.resolution_percentage = 100
    render_settings.film_transparent = False
    render_settings.image_settings.file_format = 'PNG'
    bpy.context.scene.cycles.samples = RENDER_SAMPLES
    try:
        bpy.context.scene.cycles.device = 'GPU'
    except Exception:
        bpy.context.scene.cycles.device = 'CPU'


def enable_gpu_rendering():
    try:
        cycles_preferences = bpy.context.preferences.addons['cycles'].preferences
        cycles_preferences.compute_device_type = 'METAL'
        cycles_preferences.get_devices()
        for compute_device in cycles_preferences.devices:
            compute_device.use = True
    except Exception as error:
        print(f"Metal GPU unavailable ({error}), rendering on CPU.")


def render_single_textured_model(blend_file_path, output_png_path):
    remove_all_scene_objects()
    bpy.ops.wm.open_mainfile(filepath=blend_file_path)

    vessel_object = find_primary_vessel_mesh_object()
    if vessel_object is None:
        print(f"  No mesh object found in {blend_file_path}, skipping.")
        return False

    bounding_center, bounding_height, bounding_width = compute_vessel_bounding_dimensions(vessel_object)
    setup_white_world_background()
    add_portrait_camera(bounding_center, bounding_height, bounding_width)
    add_top_right_sun_light(bounding_center, bounding_height)
    setup_render_settings(output_png_path)
    bpy.ops.render.render(write_still=True)
    return True


def find_all_blend_files_in_directory(directory_path):
    return sorted(glob.glob(os.path.join(directory_path, "*.blend")))


def render_all_textured_models():
    absolute_output_directory = os.path.abspath(OUTPUT_RENDER_DIRECTORY)
    os.makedirs(absolute_output_directory, exist_ok=True)

    enable_gpu_rendering()

    blend_files = find_all_blend_files_in_directory(INPUT_DIRECTORY)
    if not blend_files:
        print(f"No .blend files found in {INPUT_DIRECTORY}")
        return

    print(f"Rendering {len(blend_files)} textured models to {absolute_output_directory}...")
    successfully_rendered_count = 0
    for blend_file_index, blend_file_path in enumerate(blend_files):
        model_filename = os.path.basename(blend_file_path)
        model_base_name = os.path.splitext(model_filename)[0]
        output_png_path = os.path.join(absolute_output_directory, f"{model_base_name}.png")
        try:
            absolute_blend_file_path = os.path.abspath(blend_file_path)
            success = render_single_textured_model(absolute_blend_file_path, output_png_path)
            if success:
                print(f"  [{blend_file_index + 1}/{len(blend_files)}] Rendered {model_base_name}.png")
                successfully_rendered_count += 1
        except Exception as error:
            print(f"  Error rendering {blend_file_path}: {error}")

    print(f"\nRender complete. Total rendered: {successfully_rendered_count}")


render_all_textured_models()