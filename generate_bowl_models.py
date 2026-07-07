import bpy
import bmesh
import math
import random
import sys
import os
from mathutils import Vector

OUTPUT_DIRECTORY = "output/bowl/model"
BASE_RANDOM_SEED = 42
REVOLUTION_SEGMENT_COUNT = 96
WALL_VERTICAL_SEGMENT_COUNT = 64
SUBDIVISION_VIEWPORT_LEVEL = 1
SUBDIVISION_RENDER_LEVEL = 2

BODY_PROFILE_SHAPE_OPTIONS = [
    "straight_flared_sides",
    "rounded_hemispherical_curve",
    "bulbous_flared_rim"]


def read_requested_model_count_from_command_arguments():
    if "--" in sys.argv:
        arguments_after_separator = sys.argv[sys.argv.index("--") + 1:]
        if len(arguments_after_separator) >= 1:
            return int(arguments_after_separator[0])
    return 1


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


def create_ceramic_placeholder_material():
    ceramic_placeholder_material = bpy.data.materials.new("bowl_body_ceramic_placeholder")
    ceramic_placeholder_material.use_nodes = True
    ceramic_placeholder_principled_shader = ceramic_placeholder_material.node_tree.nodes.get("Principled BSDF")
    ceramic_placeholder_principled_shader.inputs["Base Color"].default_value = (0.92, 0.90, 0.84, 1.0)
    ceramic_placeholder_principled_shader.inputs["Roughness"].default_value = 0.55
    return ceramic_placeholder_material


def recalculate_outward_face_normals(target_object):
    working_bmesh = bmesh.new()
    working_bmesh.from_mesh(target_object.data)
    bmesh.ops.recalc_face_normals(working_bmesh, faces=working_bmesh.faces)
    working_bmesh.to_mesh(target_object.data)
    working_bmesh.free()


def compute_smoothstep_progress(linear_progress):
    return linear_progress * linear_progress * (3.0 - 2.0 * linear_progress)


def compute_wall_radius_at_height_fraction(height_fraction, base_radius, body_profile_shape, flare_amount):
    if body_profile_shape == "straight_flared_sides":
        return base_radius + flare_amount * height_fraction
    elif body_profile_shape == "rounded_hemispherical_curve":
        curved_progress = height_fraction ** 0.62
        return base_radius + flare_amount * curved_progress
    elif body_profile_shape == "bulbous_flared_rim":
        mid_bulge_component = math.sin(math.pi * height_fraction)
        rim_flare_component = compute_smoothstep_progress(height_fraction)
        return base_radius + flare_amount * (0.32 * mid_bulge_component + 0.68 * rim_flare_component)
    else:
        return base_radius


def build_body_outer_profile_vertices(base_radius, bowl_height, body_profile_shape, flare_amount):
    bottom_wall_radius = compute_wall_radius_at_height_fraction(0.0, base_radius, body_profile_shape, flare_amount)
    profile_vertices = [Vector((0.0, 0.0, 0.0)), Vector((max(bottom_wall_radius, 0.002), 0.0, 0.0))]
    for vertical_index in range(1, WALL_VERTICAL_SEGMENT_COUNT + 1):
        height_fraction = vertical_index / WALL_VERTICAL_SEGMENT_COUNT
        height_position = height_fraction * bowl_height
        wall_radius = compute_wall_radius_at_height_fraction(height_fraction, base_radius, body_profile_shape, flare_amount)
        profile_vertices.append(Vector((max(wall_radius, 0.002), 0.0, height_position)))
    return profile_vertices


def create_revolved_hollow_body(profile_vertices, wall_thickness):
    body_mesh = bpy.data.meshes.new("bowl_body_mesh")
    profile_edges = [(edge_index, edge_index + 1) for edge_index in range(len(profile_vertices) - 1)]
    body_mesh.from_pydata([tuple(point) for point in profile_vertices], profile_edges, [])
    body_mesh.update()
    body_object = bpy.data.objects.new("bowl_body", body_mesh)
    bpy.context.scene.collection.objects.link(body_object)
    make_object_the_only_active_selection(body_object)

    revolution_modifier = body_object.modifiers.new("Revolution", "SCREW")
    revolution_modifier.angle = 2.0 * math.pi
    revolution_modifier.screw_offset = 0.0
    revolution_modifier.steps = REVOLUTION_SEGMENT_COUNT
    revolution_modifier.render_steps = REVOLUTION_SEGMENT_COUNT
    revolution_modifier.axis = 'Z'
    revolution_modifier.use_merge_vertices = True
    revolution_modifier.merge_threshold = 0.00001
    revolution_modifier.use_normal_calculate = True
    bpy.ops.object.modifier_apply(modifier="Revolution")

    wall_thickness_modifier = body_object.modifiers.new("WallThickness", "SOLIDIFY")
    wall_thickness_modifier.thickness = wall_thickness
    wall_thickness_modifier.offset = -1.0
    wall_thickness_modifier.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier="WallThickness")

    recalculate_outward_face_normals(body_object)
    return body_object


def finalize_ceramic_object(bowl_object, model_index, ceramic_placeholder_material):
    recalculate_outward_face_normals(bowl_object)
    make_object_the_only_active_selection(bowl_object)
    bpy.ops.object.shade_smooth()
    subdivision_modifier = bowl_object.modifiers.new("Subdivision", "SUBSURF")
    subdivision_modifier.levels = SUBDIVISION_VIEWPORT_LEVEL
    subdivision_modifier.render_levels = SUBDIVISION_RENDER_LEVEL
    bowl_object.data.materials.clear()
    bowl_object.data.materials.append(ceramic_placeholder_material)
    for polygon in bowl_object.data.polygons:
        polygon.material_index = 0
    bowl_object.name = "bowl_{:03d}".format(model_index)
    bowl_object.data.name = "bowl_{:03d}_mesh".format(model_index)


def build_single_unique_bowl(model_index):
    chosen_body_profile_shape = random.choice(BODY_PROFILE_SHAPE_OPTIONS)

    overall_uniform_scale = random.uniform(0.85, 1.30)
    base_radius = random.uniform(0.045, 0.062) * overall_uniform_scale
    bowl_height = random.uniform(0.038, 0.062) * overall_uniform_scale
    wall_thickness = random.uniform(0.0038, 0.0055) * overall_uniform_scale

    if chosen_body_profile_shape == "straight_flared_sides":
        flare_amount = base_radius * random.uniform(0.10, 0.20)
    elif chosen_body_profile_shape == "rounded_hemispherical_curve":
        flare_amount = base_radius * random.uniform(0.45, 0.70)
    elif chosen_body_profile_shape == "bulbous_flared_rim":
        flare_amount = base_radius * random.uniform(0.38, 0.58)
    else:
        flare_amount = 0.0

    profile_vertices = build_body_outer_profile_vertices(base_radius, bowl_height, chosen_body_profile_shape, flare_amount)
    body_object = create_revolved_hollow_body(profile_vertices, wall_thickness)

    ceramic_placeholder_material = create_ceramic_placeholder_material()
    finalize_ceramic_object(body_object, model_index, ceramic_placeholder_material)


def determine_expected_blend_file_path(model_index):
    absolute_output_directory = os.path.abspath(OUTPUT_DIRECTORY)
    return os.path.join(absolute_output_directory, "bowl_{:03d}.blend".format(model_index))


def save_current_scene_as_blend_file(model_index):
    absolute_output_directory = os.path.abspath(OUTPUT_DIRECTORY)
    os.makedirs(absolute_output_directory, exist_ok=True)
    blend_file_path = determine_expected_blend_file_path(model_index)
    bpy.ops.wm.save_as_mainfile(filepath=blend_file_path)


def generate_requested_bowl_models():
    requested_model_count = read_requested_model_count_from_command_arguments()
    already_generated_count = 0
    newly_generated_count = 0
    for model_index in range(requested_model_count):
        expected_blend_file_path = determine_expected_blend_file_path(model_index)
        if os.path.isfile(expected_blend_file_path):
            print(f"  [{model_index + 1}/{requested_model_count}] Skipping bowl_{model_index:03d}.blend, already generated")
            already_generated_count += 1
            continue
        remove_all_scene_objects()
        random.seed(BASE_RANDOM_SEED + model_index)
        build_single_unique_bowl(model_index)
        save_current_scene_as_blend_file(model_index)
        print(f"  [{model_index + 1}/{requested_model_count}] Generated bowl_{model_index:03d}.blend")
        newly_generated_count += 1
    print(f"\nGeneration complete. Newly generated: {newly_generated_count}, skipped as already present: {already_generated_count}")


generate_requested_bowl_models()