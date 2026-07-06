import bpy
import bmesh
import math
import random
import sys
import os
from mathutils import Vector

OUTPUT_DIRECTORY = "output/bottle/model"
BASE_RANDOM_SEED = 42
REVOLUTION_SEGMENT_COUNT = 96
WALL_VERTICAL_SEGMENT_COUNT = 64
SUBDIVISION_VIEWPORT_LEVEL = 1
SUBDIVISION_RENDER_LEVEL = 2

BODY_PROFILE_SHAPE_OPTIONS = ["bulbous_gourd_rounded", "ovoid_tapering_body", "straight_columnar_body"]
NECK_LIP_STYLE_OPTIONS = ["straight_mouth", "flared_trumpet_lip", "collared_ridge_rim"]


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


def create_bottle_body_ceramic_placeholder_material():
    bottle_body_ceramic_material = bpy.data.materials.new("bottle_body_ceramic_placeholder")
    bottle_body_ceramic_material.use_nodes = True
    bottle_body_principled_shader = bottle_body_ceramic_material.node_tree.nodes.get("Principled BSDF")
    bottle_body_principled_shader.inputs["Base Color"].default_value = (0.92, 0.90, 0.84, 1.0)
    bottle_body_principled_shader.inputs["Roughness"].default_value = 0.55
    return bottle_body_ceramic_material


def create_bottle_neck_ceramic_placeholder_material():
    bottle_neck_ceramic_material = bpy.data.materials.new("bottle_neck_ceramic_placeholder")
    bottle_neck_ceramic_material.use_nodes = True
    bottle_neck_principled_shader = bottle_neck_ceramic_material.node_tree.nodes.get("Principled BSDF")
    bottle_neck_principled_shader.inputs["Base Color"].default_value = (0.92, 0.90, 0.84, 1.0)
    bottle_neck_principled_shader.inputs["Roughness"].default_value = 0.55
    return bottle_neck_ceramic_material


def recalculate_outward_face_normals(target_object):
    working_bmesh = bmesh.new()
    working_bmesh.from_mesh(target_object.data)
    bmesh.ops.recalc_face_normals(working_bmesh, faces=working_bmesh.faces)
    working_bmesh.to_mesh(target_object.data)
    working_bmesh.free()


def compute_body_zone_radius(body_progress, base_radius, body_profile_shape,
                             gourd_bulge_amount, gourd_asymmetry_power, ovoid_bottom_widen_factor):
    if body_profile_shape == "bulbous_gourd_rounded":
        return base_radius + gourd_bulge_amount * math.sin(math.pi * (body_progress ** gourd_asymmetry_power))
    elif body_profile_shape == "ovoid_tapering_body":
        bottom_radius = base_radius * ovoid_bottom_widen_factor
        smooth_progress = body_progress * body_progress * (3.0 - 2.0 * body_progress)
        return bottom_radius - (bottom_radius - base_radius) * smooth_progress
    else:
        return base_radius


def compute_neck_zone_radius(neck_height_fraction, neck_radius, neck_lip_style,
                             lip_flare_start_fraction, lip_flare_full_fraction, lip_radius_factor,
                             ridge_center_fraction, ridge_half_width_fraction, ridge_bulge_factor):
    if neck_lip_style == "flared_trumpet_lip":
        if neck_height_fraction <= lip_flare_start_fraction:
            return neck_radius
        flare_progress = (neck_height_fraction - lip_flare_start_fraction) / (lip_flare_full_fraction - lip_flare_start_fraction)
        smooth_flare_progress = flare_progress * flare_progress * (3.0 - 2.0 * flare_progress)
        return neck_radius + (neck_radius * lip_radius_factor - neck_radius) * smooth_flare_progress
    elif neck_lip_style == "collared_ridge_rim":
        distance_from_ridge_center = abs(neck_height_fraction - ridge_center_fraction)
        if distance_from_ridge_center <= ridge_half_width_fraction:
            ridge_local_progress = distance_from_ridge_center / ridge_half_width_fraction
            ridge_smooth_progress = ridge_local_progress * ridge_local_progress * (3.0 - 2.0 * ridge_local_progress)
            ridge_falloff_amount = 1.0 - ridge_smooth_progress
            return neck_radius + (neck_radius * ridge_bulge_factor - neck_radius) * ridge_falloff_amount
        return neck_radius
    else:
        return neck_radius


def compute_wall_radius_at_height_fraction(height_fraction, base_radius, neck_radius,
                                           shoulder_start_fraction, neck_start_fraction,
                                           body_profile_shape, gourd_bulge_amount, gourd_asymmetry_power,
                                           ovoid_bottom_widen_factor, neck_lip_style,
                                           lip_flare_start_fraction, lip_flare_full_fraction, lip_radius_factor,
                                           ridge_center_fraction, ridge_half_width_fraction, ridge_bulge_factor):
    if height_fraction <= shoulder_start_fraction:
        body_progress = height_fraction / shoulder_start_fraction
        return compute_body_zone_radius(
            body_progress, base_radius, body_profile_shape,
            gourd_bulge_amount, gourd_asymmetry_power, ovoid_bottom_widen_factor)
    elif height_fraction <= neck_start_fraction:
        shoulder_progress = (height_fraction - shoulder_start_fraction) / (neck_start_fraction - shoulder_start_fraction)
        smooth_shoulder_progress = shoulder_progress * shoulder_progress * (3.0 - 2.0 * shoulder_progress)
        return base_radius + (neck_radius - base_radius) * smooth_shoulder_progress
    else:
        neck_height_fraction = (height_fraction - neck_start_fraction) / (1.0 - neck_start_fraction)
        return compute_neck_zone_radius(
            neck_height_fraction, neck_radius, neck_lip_style,
            lip_flare_start_fraction, lip_flare_full_fraction, lip_radius_factor,
            ridge_center_fraction, ridge_half_width_fraction, ridge_bulge_factor)


def build_body_outer_profile_vertices(bottle_height, profile_radius_function):
    profile_vertices = [Vector((0.0, 0.0, 0.0)), Vector((max(profile_radius_function(0.0), 0.002), 0.0, 0.0))]
    for vertical_index in range(1, WALL_VERTICAL_SEGMENT_COUNT + 1):
        height_fraction = vertical_index / WALL_VERTICAL_SEGMENT_COUNT
        height_position = height_fraction * bottle_height
        wall_radius = profile_radius_function(height_fraction)
        profile_vertices.append(Vector((max(wall_radius, 0.002), 0.0, height_position)))
    return profile_vertices


def create_revolved_hollow_body(profile_vertices, wall_thickness):
    body_mesh = bpy.data.meshes.new("bottle_body_mesh")
    profile_edges = [(edge_index, edge_index + 1) for edge_index in range(len(profile_vertices) - 1)]
    body_mesh.from_pydata([tuple(point) for point in profile_vertices], profile_edges, [])
    body_mesh.update()
    body_object = bpy.data.objects.new("bottle_body", body_mesh)
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


def finalize_ceramic_object(bottle_object, model_index, bottle_body_ceramic_material,
                            bottle_neck_ceramic_material, absolute_neck_start_height):
    recalculate_outward_face_normals(bottle_object)
    make_object_the_only_active_selection(bottle_object)
    bpy.ops.object.shade_smooth()
    subdivision_modifier = bottle_object.modifiers.new("Subdivision", "SUBSURF")
    subdivision_modifier.levels = SUBDIVISION_VIEWPORT_LEVEL
    subdivision_modifier.render_levels = SUBDIVISION_RENDER_LEVEL

    bottle_object.data.materials.clear()
    bottle_object.data.materials.append(bottle_body_ceramic_material)
    bottle_object.data.materials.append(bottle_neck_ceramic_material)

    mesh_data = bottle_object.data
    for polygon in mesh_data.polygons:
        polygon_center_z = sum(mesh_data.vertices[vertex_index].co.z for vertex_index in polygon.vertices) / len(polygon.vertices)
        polygon.material_index = 1 if polygon_center_z >= absolute_neck_start_height else 0

    bottle_object["absolute_neck_start_height"] = absolute_neck_start_height
    bottle_object.name = "bottle_{:03d}".format(model_index)
    bottle_object.data.name = "bottle_{:03d}_mesh".format(model_index)


def build_single_unique_bottle(model_index):
    chosen_body_profile_shape = random.choice(BODY_PROFILE_SHAPE_OPTIONS)
    chosen_neck_lip_style = random.choice(NECK_LIP_STYLE_OPTIONS)

    overall_uniform_scale = random.uniform(0.80, 1.30)
    base_radius = random.uniform(0.045, 0.075) * overall_uniform_scale
    bottle_height = random.uniform(0.140, 0.260) * overall_uniform_scale
    wall_thickness = random.uniform(0.0040, 0.0060) * overall_uniform_scale
    neck_radius = base_radius * random.uniform(0.18, 0.32)

    shoulder_start_fraction = random.uniform(0.45, 0.65)
    shoulder_transition_width = random.uniform(0.08, 0.18)
    neck_start_fraction = min(shoulder_start_fraction + shoulder_transition_width, 0.86)

    gourd_bulge_amount = 0.0
    gourd_asymmetry_power = 1.0
    ovoid_bottom_widen_factor = 1.0
    if chosen_body_profile_shape == "bulbous_gourd_rounded":
        gourd_bulge_amount = base_radius * random.uniform(0.25, 0.55)
        gourd_asymmetry_power = random.uniform(0.55, 0.85)
    elif chosen_body_profile_shape == "ovoid_tapering_body":
        ovoid_bottom_widen_factor = random.uniform(1.15, 1.40)

    lip_flare_start_fraction = 1.0
    lip_flare_full_fraction = 1.0
    lip_radius_factor = 1.0
    ridge_center_fraction = 0.0
    ridge_half_width_fraction = 0.01
    ridge_bulge_factor = 1.0
    if chosen_neck_lip_style == "flared_trumpet_lip":
        lip_flare_full_fraction = 1.0
        lip_flare_start_fraction = 1.0 - random.uniform(0.06, 0.12)
        lip_radius_factor = random.uniform(1.25, 1.70)
    elif chosen_neck_lip_style == "collared_ridge_rim":
        ridge_center_fraction = random.uniform(0.88, 0.94)
        ridge_half_width_fraction = random.uniform(0.025, 0.045)
        ridge_bulge_factor = random.uniform(1.30, 1.65)

    profile_radius_function = lambda height_fraction: compute_wall_radius_at_height_fraction(
        height_fraction, base_radius, neck_radius,
        shoulder_start_fraction, neck_start_fraction,
        chosen_body_profile_shape, gourd_bulge_amount, gourd_asymmetry_power, ovoid_bottom_widen_factor,
        chosen_neck_lip_style, lip_flare_start_fraction, lip_flare_full_fraction, lip_radius_factor,
        ridge_center_fraction, ridge_half_width_fraction, ridge_bulge_factor)

    profile_vertices = build_body_outer_profile_vertices(bottle_height, profile_radius_function)
    body_object = create_revolved_hollow_body(profile_vertices, wall_thickness)

    absolute_neck_start_height = neck_start_fraction * bottle_height
    bottle_body_ceramic_material = create_bottle_body_ceramic_placeholder_material()
    bottle_neck_ceramic_material = create_bottle_neck_ceramic_placeholder_material()
    finalize_ceramic_object(body_object, model_index, bottle_body_ceramic_material,
                            bottle_neck_ceramic_material, absolute_neck_start_height)


def determine_expected_blend_file_path(model_index):
    absolute_output_directory = os.path.abspath(OUTPUT_DIRECTORY)
    return os.path.join(absolute_output_directory, "bottle_{:03d}.blend".format(model_index))


def save_current_scene_as_blend_file(model_index):
    absolute_output_directory = os.path.abspath(OUTPUT_DIRECTORY)
    os.makedirs(absolute_output_directory, exist_ok=True)
    blend_file_path = determine_expected_blend_file_path(model_index)
    bpy.ops.wm.save_as_mainfile(filepath=blend_file_path)


def generate_requested_bottle_models():
    requested_model_count = read_requested_model_count_from_command_arguments()
    already_generated_count = 0
    newly_generated_count = 0
    for model_index in range(requested_model_count):
        expected_blend_file_path = determine_expected_blend_file_path(model_index)
        if os.path.isfile(expected_blend_file_path):
            print(f"  [{model_index + 1}/{requested_model_count}] Skipping bottle_{model_index:03d}.blend, already generated")
            already_generated_count += 1
            continue
        remove_all_scene_objects()
        random.seed(BASE_RANDOM_SEED + model_index)
        build_single_unique_bottle(model_index)
        save_current_scene_as_blend_file(model_index)
        print(f"  [{model_index + 1}/{requested_model_count}] Generated bottle_{model_index:03d}.blend")
        newly_generated_count += 1
    print(f"\nGeneration complete. Newly generated: {newly_generated_count}, skipped as already present: {already_generated_count}")


generate_requested_bottle_models()