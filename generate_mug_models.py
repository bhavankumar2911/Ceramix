import bpy
import bmesh
import math
import random
import sys
import os
from mathutils import Vector

OUTPUT_DIRECTORY = "output/mug_models"
BASE_RANDOM_SEED = 42
REVOLUTION_SEGMENT_COUNT = 96
WALL_VERTICAL_SEGMENT_COUNT = 48
SUBDIVISION_VIEWPORT_LEVEL = 1
SUBDIVISION_RENDER_LEVEL = 2

BODY_PROFILE_SHAPE_OPTIONS = ["straight_cylinder", "convex_belly_outward", "concave_pinch_inward", "wider_top_narrower_base"]
HANDLE_TYPE_OPTIONS = ["perfect_semicircle", "rectangular_rounded", "question_mark_hook"]


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
    for orphan_curve in list(bpy.data.curves):
        if orphan_curve.users == 0:
            bpy.data.curves.remove(orphan_curve)


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


def build_body_outer_profile_vertices(base_radius, mug_height, body_profile_shape, silhouette_deviation_amount):
    profile_vertices = [Vector((0.0, 0.0, 0.0)), Vector((base_radius, 0.0, 0.0))]
    for vertical_index in range(1, WALL_VERTICAL_SEGMENT_COUNT + 1):
        height_fraction = vertical_index / WALL_VERTICAL_SEGMENT_COUNT
        height_position = height_fraction * mug_height
        
        if body_profile_shape == "convex_belly_outward":
            wall_radius = base_radius + silhouette_deviation_amount * math.sin(math.pi * height_fraction)
        elif body_profile_shape == "concave_pinch_inward":
            wall_radius = base_radius - silhouette_deviation_amount * math.sin(math.pi * height_fraction)
        elif body_profile_shape == "wider_top_narrower_base":
            wall_radius = base_radius + silhouette_deviation_amount * height_fraction
        else:
            wall_radius = base_radius
        
        profile_vertices.append(Vector((max(wall_radius, 0.002), 0.0, height_position)))
    return profile_vertices


def create_revolved_hollow_body(profile_vertices, wall_thickness):
    body_mesh = bpy.data.meshes.new("mug_body_mesh")
    profile_edges = [(edge_index, edge_index + 1) for edge_index in range(len(profile_vertices) - 1)]
    body_mesh.from_pydata([tuple(point) for point in profile_vertices], profile_edges, [])
    body_mesh.update()
    body_object = bpy.data.objects.new("mug_body", body_mesh)
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


def build_swept_pipe_handle_geometry(centerline_path_points, pipe_radius, ring_vertex_count):
    handle_bmesh = bmesh.new()
    ring_vertex_rings = []

    for point_index, path_point in enumerate(centerline_path_points):
        if point_index == 0:
            path_tangent_direction = (centerline_path_points[1] - centerline_path_points[0]).normalized()
        elif point_index == len(centerline_path_points) - 1:
            path_tangent_direction = (centerline_path_points[-1] - centerline_path_points[-2]).normalized()
        else:
            path_tangent_direction = (centerline_path_points[point_index + 1] - centerline_path_points[point_index - 1]).normalized()

        world_y_axis_reference = Vector((0.0, 1.0, 0.0))
        if abs(path_tangent_direction.dot(world_y_axis_reference)) > 0.99:
            world_y_axis_reference = Vector((1.0, 0.0, 0.0))
        ring_right_axis = path_tangent_direction.cross(world_y_axis_reference).normalized()
        ring_up_axis = ring_right_axis.cross(path_tangent_direction).normalized()

        single_ring_vertices = []
        for ring_index in range(ring_vertex_count):
            ring_angle = 2.0 * math.pi * ring_index / ring_vertex_count
            vertex_offset = ring_right_axis * (pipe_radius * math.cos(ring_angle)) + ring_up_axis * (pipe_radius * math.sin(ring_angle))
            single_ring_vertices.append(handle_bmesh.verts.new(path_point + vertex_offset))
        ring_vertex_rings.append(single_ring_vertices)

    for ring_pair_index in range(len(ring_vertex_rings) - 1):
        lower_ring = ring_vertex_rings[ring_pair_index]
        upper_ring = ring_vertex_rings[ring_pair_index + 1]
        for vertex_index in range(ring_vertex_count):
            next_vertex_index = (vertex_index + 1) % ring_vertex_count
            handle_bmesh.faces.new([
                lower_ring[vertex_index],
                lower_ring[next_vertex_index],
                upper_ring[next_vertex_index],
                upper_ring[vertex_index]])

    return handle_bmesh


def finalise_handle_object(handle_bmesh, wall_thickness):
    handle_mesh = bpy.data.meshes.new("mug_handle_mesh")
    handle_bmesh.to_mesh(handle_mesh)
    handle_bmesh.free()
    handle_object = bpy.data.objects.new("mug_handle", handle_mesh)
    bpy.context.scene.collection.objects.link(handle_object)
    make_object_the_only_active_selection(handle_object)
    handle_solidify = handle_object.modifiers.new("HandleWall", "SOLIDIFY")
    handle_solidify.thickness = wall_thickness
    handle_solidify.offset = 0.0
    bpy.ops.object.modifier_apply(modifier="HandleWall")
    return handle_object


def build_semicircle_loop_handle(base_radius, mug_height, wall_thickness):
    upper_attachment_height = mug_height * 0.80
    lower_attachment_height = mug_height * 0.28
    height_span = upper_attachment_height - lower_attachment_height
    mid_height = (upper_attachment_height + lower_attachment_height) / 2.0
    burial_depth = base_radius * 0.12
    pipe_radius = base_radius * 0.065
    ring_vertex_count = 16
    path_segment_count = 56

    circle_radius = height_span / 2.0
    center_x = base_radius - burial_depth

    centerline_path_points = []
    for segment_index in range(path_segment_count + 1):
        arc_progress = segment_index / path_segment_count
        arc_angle = -math.pi / 2.0 + arc_progress * math.pi
        x_position = center_x + circle_radius * math.cos(arc_angle)
        z_position = mid_height + circle_radius * math.sin(arc_angle)
        centerline_path_points.append(Vector((x_position, 0.0, z_position)))

    return finalise_handle_object(
        build_swept_pipe_handle_geometry(centerline_path_points, pipe_radius, ring_vertex_count),
        wall_thickness)


def build_rounded_rectangle_strap_handle(base_radius, mug_height, wall_thickness):
    upper_attachment_height = mug_height * 0.84
    lower_attachment_height = mug_height * 0.26
    height_span = upper_attachment_height - lower_attachment_height
    burial_depth = base_radius * 0.12
    attachment_x = base_radius - burial_depth
    handle_outward_width = base_radius * 0.72
    corner_radius = min(handle_outward_width * 0.30, height_span * 0.20)
    pipe_radius = base_radius * 0.068
    ring_vertex_count = 16
    segments_per_straight = 8
    segments_per_corner = 12

    right_side_x = attachment_x + handle_outward_width
    bottom_corner_center_x = right_side_x - corner_radius
    bottom_corner_center_z = lower_attachment_height + corner_radius
    top_corner_center_x = right_side_x - corner_radius
    top_corner_center_z = upper_attachment_height - corner_radius

    centerline_path_points = []

    for segment_index in range(segments_per_straight + 1):
        t = segment_index / segments_per_straight
        x_position = attachment_x + t * (handle_outward_width - corner_radius)
        centerline_path_points.append(Vector((x_position, 0.0, lower_attachment_height)))

    for segment_index in range(1, segments_per_corner + 1):
        t = segment_index / segments_per_corner
        corner_angle = -math.pi / 2.0 + t * (math.pi / 2.0)
        x_position = bottom_corner_center_x + corner_radius * math.cos(corner_angle)
        z_position = bottom_corner_center_z + corner_radius * math.sin(corner_angle)
        centerline_path_points.append(Vector((x_position, 0.0, z_position)))

    for segment_index in range(1, segments_per_straight + 1):
        t = segment_index / segments_per_straight
        z_position = (lower_attachment_height + corner_radius) + t * (height_span - 2.0 * corner_radius)
        centerline_path_points.append(Vector((right_side_x, 0.0, z_position)))

    for segment_index in range(1, segments_per_corner + 1):
        t = segment_index / segments_per_corner
        corner_angle = 0.0 + t * (math.pi / 2.0)
        x_position = top_corner_center_x + corner_radius * math.cos(corner_angle)
        z_position = top_corner_center_z + corner_radius * math.sin(corner_angle)
        centerline_path_points.append(Vector((x_position, 0.0, z_position)))

    for segment_index in range(1, segments_per_straight + 1):
        t = segment_index / segments_per_straight
        x_position = (right_side_x - corner_radius) - t * (handle_outward_width - corner_radius)
        centerline_path_points.append(Vector((x_position, 0.0, upper_attachment_height)))

    return finalise_handle_object(
        build_swept_pipe_handle_geometry(centerline_path_points, pipe_radius, ring_vertex_count),
        wall_thickness)


def build_question_mark_hook_handle(base_radius, mug_height, wall_thickness):
    upper_attachment_height = mug_height * 0.85
    height_span = upper_attachment_height - mug_height * 0.22
    burial_depth = base_radius * 0.13
    pipe_radius = base_radius * 0.065
    ring_vertex_count = 16
    path_segment_count = 60

    main_arc_radius = height_span * 0.52
    arc_center_x = base_radius - burial_depth
    arc_center_z = upper_attachment_height - main_arc_radius

    start_angle = math.pi / 2.0
    total_sweep_angle = math.radians(185.0)

    centerline_path_points = []
    for segment_index in range(path_segment_count + 1):
        arc_progress = segment_index / path_segment_count
        current_angle = start_angle - arc_progress * total_sweep_angle
        x_position = arc_center_x + main_arc_radius * math.cos(current_angle)
        z_position = arc_center_z + main_arc_radius * math.sin(current_angle)
        centerline_path_points.append(Vector((x_position, 0.0, z_position)))

    return finalise_handle_object(
        build_swept_pipe_handle_geometry(centerline_path_points, pipe_radius, ring_vertex_count),
        wall_thickness)


def join_mug_body_and_handle(body_object, handle_object):
    bpy.ops.object.select_all(action='DESELECT')
    body_object.select_set(True)
    handle_object.select_set(True)
    bpy.context.view_layer.objects.active = body_object
    bpy.ops.object.join()
    return body_object


def finalize_ceramic_object(mug_object, model_index, ceramic_material):
    recalculate_outward_face_normals(mug_object)
    make_object_the_only_active_selection(mug_object)
    bpy.ops.object.shade_smooth()
    subdivision_modifier = mug_object.modifiers.new("Subdivision", "SUBSURF")
    subdivision_modifier.levels = SUBDIVISION_VIEWPORT_LEVEL
    subdivision_modifier.render_levels = SUBDIVISION_RENDER_LEVEL
    mug_object.data.materials.clear()
    mug_object.data.materials.append(ceramic_material)
    for polygon in mug_object.data.polygons:
        polygon.material_index = 0
    mug_object.name = "mug_{:03d}".format(model_index)
    mug_object.data.name = "mug_{:03d}_mesh".format(model_index)


def build_single_unique_mug(model_index):
    chosen_body_profile_shape = random.choice(BODY_PROFILE_SHAPE_OPTIONS)
    chosen_handle_type = random.choice(HANDLE_TYPE_OPTIONS)

    overall_uniform_scale = random.uniform(0.80, 1.30)
    base_radius = random.uniform(0.055, 0.080) * overall_uniform_scale
    mug_height = random.uniform(0.095, 0.155) * overall_uniform_scale
    wall_thickness = random.uniform(0.0045, 0.0065) * overall_uniform_scale

    if chosen_body_profile_shape == "convex_belly_outward":
        silhouette_deviation_amount = base_radius * random.uniform(0.12, 0.28)
    elif chosen_body_profile_shape == "concave_pinch_inward":
        silhouette_deviation_amount = base_radius * random.uniform(0.08, 0.18)
    elif chosen_body_profile_shape == "wider_top_narrower_base":
        silhouette_deviation_amount = base_radius * random.uniform(0.15, 0.32)
    else:
        silhouette_deviation_amount = 0.0

    profile_vertices = build_body_outer_profile_vertices(
        base_radius, mug_height, chosen_body_profile_shape, silhouette_deviation_amount)
    body_object = create_revolved_hollow_body(profile_vertices, wall_thickness)

    if chosen_handle_type == "perfect_semicircle":
        handle_object = build_semicircle_loop_handle(base_radius, mug_height, wall_thickness)
    elif chosen_handle_type == "rectangular_rounded":
        handle_object = build_rounded_rectangle_strap_handle(base_radius, mug_height, wall_thickness)
    else:
        handle_object = build_question_mark_hook_handle(base_radius, mug_height, wall_thickness)

    mug_object = join_mug_body_and_handle(body_object, handle_object)

    ceramic_material = create_ceramic_placeholder_material()
    finalize_ceramic_object(mug_object, model_index, ceramic_material)


def save_current_scene_as_blend_file(model_index):
    absolute_output_directory = os.path.abspath(OUTPUT_DIRECTORY)
    os.makedirs(absolute_output_directory, exist_ok=True)
    blend_file_path = os.path.join(absolute_output_directory, "mug_{:03d}.blend".format(model_index))
    bpy.ops.wm.save_as_mainfile(filepath=blend_file_path)


def generate_requested_mug_models():
    requested_model_count = read_requested_model_count_from_command_arguments()
    for model_index in range(requested_model_count):
        remove_all_scene_objects()
        random.seed(BASE_RANDOM_SEED + model_index)
        build_single_unique_mug(model_index)
        save_current_scene_as_blend_file(model_index)


generate_requested_mug_models()