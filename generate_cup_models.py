import bpy
import bmesh
import math
import random
import sys
import os
from mathutils import Vector

OUTPUT_DIRECTORY = "output/cup/model"
BASE_RANDOM_SEED = 42
REVOLUTION_SEGMENT_COUNT = 96
WALL_VERTICAL_SEGMENT_COUNT = 48
SUBDIVISION_VIEWPORT_LEVEL = 1
SUBDIVISION_RENDER_LEVEL = 2

BODY_PROFILE_SHAPE_OPTIONS = [
    "straight_cylinder",
    "tapered_wide_top_narrow_base",
    "tapered_narrow_top_wide_base",
    "convex_barrel_bulge",
    "tapered_cone_with_pulled_foot"]


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
    ceramic_material = bpy.data.materials.new("ceramic_base_placeholder")
    ceramic_material.use_nodes = True
    principled_shader = ceramic_material.node_tree.nodes.get("Principled BSDF")
    principled_shader.inputs["Base Color"].default_value = (0.92, 0.90, 0.84, 1.0)
    principled_shader.inputs["Roughness"].default_value = 0.55
    return ceramic_material


def recalculate_outward_face_normals(target_object):
    working_bmesh = bmesh.new()
    working_bmesh.from_mesh(target_object.data)
    bmesh.ops.recalc_face_normals(working_bmesh, faces=working_bmesh.faces)
    working_bmesh.to_mesh(target_object.data)
    working_bmesh.free()


def compute_wall_radius_at_height_fraction(height_fraction, base_radius, body_profile_shape,
                                           silhouette_deviation_amount, foot_radius_fraction,
                                           foot_height_fraction):
    if body_profile_shape == "tapered_wide_top_narrow_base":
        return base_radius + silhouette_deviation_amount * height_fraction
    elif body_profile_shape == "tapered_narrow_top_wide_base":
        return base_radius - silhouette_deviation_amount * height_fraction
    elif body_profile_shape == "convex_barrel_bulge":
        return base_radius + silhouette_deviation_amount * math.sin(math.pi * height_fraction)
    elif body_profile_shape == "tapered_cone_with_pulled_foot":
        foot_constant_radius = base_radius * foot_radius_fraction
        rim_radius = base_radius + silhouette_deviation_amount
        if height_fraction <= foot_height_fraction:
            return foot_constant_radius
        upper_taper_progress = (height_fraction - foot_height_fraction) / (1.0 - foot_height_fraction)
        return foot_constant_radius + (rim_radius - foot_constant_radius) * upper_taper_progress
    else:
        return base_radius


def build_body_outer_profile_vertices(base_radius, cup_height, body_profile_shape,
                                      silhouette_deviation_amount, foot_radius_fraction,
                                      foot_height_fraction):
    bottom_wall_radius = compute_wall_radius_at_height_fraction(
        0.0, base_radius, body_profile_shape, silhouette_deviation_amount,
        foot_radius_fraction, foot_height_fraction)
    profile_vertices = [Vector((0.0, 0.0, 0.0)), Vector((max(bottom_wall_radius, 0.002), 0.0, 0.0))]
    for vertical_index in range(1, WALL_VERTICAL_SEGMENT_COUNT + 1):
        height_fraction = vertical_index / WALL_VERTICAL_SEGMENT_COUNT
        height_position = height_fraction * cup_height
        wall_radius = compute_wall_radius_at_height_fraction(
            height_fraction, base_radius, body_profile_shape, silhouette_deviation_amount,
            foot_radius_fraction, foot_height_fraction)
        profile_vertices.append(Vector((max(wall_radius, 0.002), 0.0, height_position)))
    return profile_vertices


def create_revolved_hollow_body(profile_vertices, wall_thickness):
    body_mesh = bpy.data.meshes.new("cup_body_mesh")
    profile_edges = [(edge_index, edge_index + 1) for edge_index in range(len(profile_vertices) - 1)]
    body_mesh.from_pydata([tuple(point) for point in profile_vertices], profile_edges, [])
    body_mesh.update()
    body_object = bpy.data.objects.new("cup_body", body_mesh)
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


def finalize_ceramic_object(cup_object, model_index, ceramic_material):
    recalculate_outward_face_normals(cup_object)
    make_object_the_only_active_selection(cup_object)
    bpy.ops.object.shade_smooth()
    subdivision_modifier = cup_object.modifiers.new("Subdivision", "SUBSURF")
    subdivision_modifier.levels = SUBDIVISION_VIEWPORT_LEVEL
    subdivision_modifier.render_levels = SUBDIVISION_RENDER_LEVEL
    cup_object.data.materials.clear()
    cup_object.data.materials.append(ceramic_material)
    for polygon in cup_object.data.polygons:
        polygon.material_index = 0
    cup_object.name = "cup_{:03d}".format(model_index)
    cup_object.data.name = "cup_{:03d}_mesh".format(model_index)


def build_single_unique_cup(model_index):
    chosen_body_profile_shape = random.choice(BODY_PROFILE_SHAPE_OPTIONS)

    overall_uniform_scale = random.uniform(0.80, 1.30)
    base_radius = random.uniform(0.040, 0.065) * overall_uniform_scale
    cup_height = random.uniform(0.075, 0.130) * overall_uniform_scale
    wall_thickness = random.uniform(0.0040, 0.0060) * overall_uniform_scale

    foot_radius_fraction = 0.0
    foot_height_fraction = 0.0

    if chosen_body_profile_shape == "tapered_wide_top_narrow_base":
        silhouette_deviation_amount = base_radius * random.uniform(0.25, 0.45)
    elif chosen_body_profile_shape == "tapered_narrow_top_wide_base":
        silhouette_deviation_amount = base_radius * random.uniform(0.20, 0.35)
    elif chosen_body_profile_shape == "convex_barrel_bulge":
        silhouette_deviation_amount = base_radius * random.uniform(0.12, 0.30)
    elif chosen_body_profile_shape == "tapered_cone_with_pulled_foot":
        silhouette_deviation_amount = base_radius * random.uniform(0.35, 0.65)
        foot_radius_fraction = random.uniform(0.55, 0.70)
        foot_height_fraction = random.uniform(0.05, 0.09)
    else:
        silhouette_deviation_amount = 0.0

    profile_vertices = build_body_outer_profile_vertices(
        base_radius, cup_height, chosen_body_profile_shape, silhouette_deviation_amount,
        foot_radius_fraction, foot_height_fraction)
    body_object = create_revolved_hollow_body(profile_vertices, wall_thickness)

    ceramic_material = create_ceramic_placeholder_material()
    finalize_ceramic_object(body_object, model_index, ceramic_material)


def save_current_scene_as_blend_file(model_index):
    absolute_output_directory = os.path.abspath(OUTPUT_DIRECTORY)
    os.makedirs(absolute_output_directory, exist_ok=True)
    blend_file_path = os.path.join(absolute_output_directory, "cup_{:03d}.blend".format(model_index))
    bpy.ops.wm.save_as_mainfile(filepath=blend_file_path)


def generate_requested_cup_models():
    requested_model_count = read_requested_model_count_from_command_arguments()
    for model_index in range(requested_model_count):
        remove_all_scene_objects()
        random.seed(BASE_RANDOM_SEED + model_index)
        build_single_unique_cup(model_index)
        save_current_scene_as_blend_file(model_index)


generate_requested_cup_models()