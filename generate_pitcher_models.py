import bpy
import bmesh
import math
import random
import sys
import os
from mathutils import Vector

OUTPUT_DIRECTORY = "output/pitcher/model"
BASE_RANDOM_SEED = 42
REVOLUTION_SEGMENT_COUNT = 96
WALL_VERTICAL_SEGMENT_COUNT = 64
SUBDIVISION_VIEWPORT_LEVEL = 1
SUBDIVISION_RENDER_LEVEL = 2

BODY_PROFILE_SHAPE_OPTIONS = [
    "straight_cylinder",
    "flower_vase_low_bulge_flared_top",
    "tapered_narrow_base",
    "tapered_wide_base"]

HANDLE_HEIGHT_SPAN_OPTIONS = [
    "top_to_bottom",
    "top_to_middle",
    "below_top_to_above_bottom"]

HANDLE_SHAPE_OPTIONS = [
    "true_semicircle",
    "rounded_rectangle"]

PITCHER_BODY_MATERIAL_NAME = "pitcher_body_ceramic_placeholder"
PITCHER_HANDLE_MATERIAL_NAME = "pitcher_handle_ceramic_placeholder"

SPOUT_ANGULAR_HALF_WIDTH_RADIANS = math.radians(26.0)
SPOUT_CENTER_AZIMUTH_RADIANS = math.pi
HANDLE_CENTER_AZIMUTH_RADIANS = 0.0


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


def create_pitcher_body_ceramic_placeholder_material():
    pitcher_body_ceramic_material = bpy.data.materials.new(PITCHER_BODY_MATERIAL_NAME)
    pitcher_body_ceramic_material.use_nodes = True
    pitcher_body_principled_shader = pitcher_body_ceramic_material.node_tree.nodes.get("Principled BSDF")
    pitcher_body_principled_shader.inputs["Base Color"].default_value = (0.92, 0.90, 0.84, 1.0)
    pitcher_body_principled_shader.inputs["Roughness"].default_value = 0.55
    return pitcher_body_ceramic_material


def create_pitcher_handle_ceramic_placeholder_material():
    pitcher_handle_ceramic_material = bpy.data.materials.new(PITCHER_HANDLE_MATERIAL_NAME)
    pitcher_handle_ceramic_material.use_nodes = True
    pitcher_handle_principled_shader = pitcher_handle_ceramic_material.node_tree.nodes.get("Principled BSDF")
    pitcher_handle_principled_shader.inputs["Base Color"].default_value = (0.92, 0.90, 0.84, 1.0)
    pitcher_handle_principled_shader.inputs["Roughness"].default_value = 0.55
    return pitcher_handle_ceramic_material


def recalculate_outward_face_normals(target_object):
    working_bmesh = bmesh.new()
    working_bmesh.from_mesh(target_object.data)
    bmesh.ops.recalc_face_normals(working_bmesh, faces=working_bmesh.faces)
    working_bmesh.to_mesh(target_object.data)
    working_bmesh.free()


def compute_flower_vase_low_bulge_radius(height_fraction, base_radius, silhouette_deviation_amount):
    bulge_peak_height_fraction = 0.28
    neck_pinch_height_fraction = 0.72
    flared_rim_radius_gain = silhouette_deviation_amount * 0.55

    if height_fraction <= bulge_peak_height_fraction:
        rise_progress = height_fraction / bulge_peak_height_fraction
        smooth_rise = rise_progress * rise_progress * (3.0 - 2.0 * rise_progress)
        return base_radius + silhouette_deviation_amount * smooth_rise
    elif height_fraction <= neck_pinch_height_fraction:
        descent_progress = (height_fraction - bulge_peak_height_fraction) / (neck_pinch_height_fraction - bulge_peak_height_fraction)
        smooth_descent = descent_progress * descent_progress * (3.0 - 2.0 * descent_progress)
        return base_radius + silhouette_deviation_amount * (1.0 - smooth_descent)
    else:
        flare_progress = (height_fraction - neck_pinch_height_fraction) / (1.0 - neck_pinch_height_fraction)
        smooth_flare = flare_progress * flare_progress * (3.0 - 2.0 * flare_progress)
        return base_radius + flared_rim_radius_gain * smooth_flare


def compute_wall_radius_at_height_fraction(height_fraction, base_radius, body_profile_shape,
                                           silhouette_deviation_amount):
    if body_profile_shape == "flower_vase_low_bulge_flared_top":
        return compute_flower_vase_low_bulge_radius(height_fraction, base_radius, silhouette_deviation_amount)
    elif body_profile_shape == "tapered_narrow_base":
        return base_radius + silhouette_deviation_amount * height_fraction
    elif body_profile_shape == "tapered_wide_base":
        return base_radius - silhouette_deviation_amount * height_fraction
    else:
        return base_radius


def build_body_outer_profile_vertices(base_radius, pitcher_height, body_profile_shape,
                                      silhouette_deviation_amount):
    bottom_wall_radius = compute_wall_radius_at_height_fraction(
        0.0, base_radius, body_profile_shape, silhouette_deviation_amount)
    profile_vertices = [Vector((0.0, 0.0, 0.0)), Vector((max(bottom_wall_radius, 0.002), 0.0, 0.0))]
    for vertical_index in range(1, WALL_VERTICAL_SEGMENT_COUNT + 1):
        height_fraction = vertical_index / WALL_VERTICAL_SEGMENT_COUNT
        height_position = height_fraction * pitcher_height
        wall_radius = compute_wall_radius_at_height_fraction(
            height_fraction, base_radius, body_profile_shape, silhouette_deviation_amount)
        profile_vertices.append(Vector((max(wall_radius, 0.002), 0.0, height_position)))
    return profile_vertices


def create_revolved_hollow_body(profile_vertices, wall_thickness):
    body_mesh = bpy.data.meshes.new("pitcher_body_mesh")
    profile_edges = [(edge_index, edge_index + 1) for edge_index in range(len(profile_vertices) - 1)]
    body_mesh.from_pydata([tuple(point) for point in profile_vertices], profile_edges, [])
    body_mesh.update()
    body_object = bpy.data.objects.new("pitcher_body", body_mesh)
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


def compute_shortest_angular_difference(first_angle, second_angle):
    angular_difference = first_angle - second_angle
    while angular_difference > math.pi:
        angular_difference -= 2.0 * math.pi
    while angular_difference < -math.pi:
        angular_difference += 2.0 * math.pi
    return angular_difference


def deform_rim_into_pinched_pour_spout(body_object, pitcher_height, base_radius):
    mesh_data = body_object.data
    maximum_height = max(vertex.co.z for vertex in mesh_data.vertices)
    rim_height_threshold = maximum_height - pitcher_height * 0.16
    spout_lift_amount = pitcher_height * 0.075
    spout_outward_push_amount = base_radius * 0.16

    for vertex in mesh_data.vertices:
        if vertex.co.z < rim_height_threshold:
            continue
        vertex_azimuth = math.atan2(vertex.co.y, vertex.co.x)
        angular_distance_from_spout_center = abs(compute_shortest_angular_difference(vertex_azimuth, SPOUT_CENTER_AZIMUTH_RADIANS))
        if angular_distance_from_spout_center > SPOUT_ANGULAR_HALF_WIDTH_RADIANS:
            continue

        angular_falloff = 0.5 * (1.0 + math.cos(math.pi * angular_distance_from_spout_center / SPOUT_ANGULAR_HALF_WIDTH_RADIANS))
        height_progress_above_threshold = (vertex.co.z - rim_height_threshold) / (maximum_height - rim_height_threshold)
        height_progress_above_threshold = max(0.0, min(1.0, height_progress_above_threshold))

        vertex.co.z += spout_lift_amount * angular_falloff * height_progress_above_threshold

        current_radius = math.sqrt(vertex.co.x ** 2 + vertex.co.y ** 2)
        if current_radius > 1e-6:
            radial_unit_x = vertex.co.x / current_radius
            radial_unit_y = vertex.co.y / current_radius
            outward_shift = spout_outward_push_amount * angular_falloff * height_progress_above_threshold
            vertex.co.x += radial_unit_x * outward_shift
            vertex.co.y += radial_unit_y * outward_shift

    mesh_data.update()
    recalculate_outward_face_normals(body_object)


def build_swept_pipe_handle_geometry(centerline_path_points, pipe_radius, ring_vertex_count):
    handle_bmesh = bmesh.new()
    ring_vertex_rings = []
    previously_propagated_right_axis = None

    for point_index, path_point in enumerate(centerline_path_points):
        if point_index == 0:
            path_tangent_direction = (centerline_path_points[1] - centerline_path_points[0]).normalized()
        elif point_index == len(centerline_path_points) - 1:
            path_tangent_direction = (centerline_path_points[-1] - centerline_path_points[-2]).normalized()
        else:
            path_tangent_direction = (centerline_path_points[point_index + 1] - centerline_path_points[point_index - 1]).normalized()

        if previously_propagated_right_axis is None:
            world_z_axis_reference = Vector((0.0, 0.0, 1.0))
            if abs(path_tangent_direction.dot(world_z_axis_reference)) > 0.99:
                world_z_axis_reference = Vector((1.0, 0.0, 0.0))
            ring_right_axis = path_tangent_direction.cross(world_z_axis_reference).normalized()
        else:
            right_axis_component_along_new_tangent = previously_propagated_right_axis.dot(path_tangent_direction)
            ring_right_axis = (previously_propagated_right_axis - path_tangent_direction * right_axis_component_along_new_tangent).normalized()

        ring_up_axis = ring_right_axis.cross(path_tangent_direction).normalized()
        previously_propagated_right_axis = ring_right_axis

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

    lower_cap_face_vertices = list(reversed(ring_vertex_rings[0]))
    handle_bmesh.faces.new(lower_cap_face_vertices)
    upper_cap_face_vertices = list(ring_vertex_rings[-1])
    handle_bmesh.faces.new(upper_cap_face_vertices)

    return handle_bmesh


def finalise_handle_object(handle_bmesh, wall_thickness):
    handle_mesh = bpy.data.meshes.new("pitcher_handle_mesh")
    handle_bmesh.to_mesh(handle_mesh)
    handle_bmesh.free()
    handle_object = bpy.data.objects.new("pitcher_handle", handle_mesh)
    bpy.context.scene.collection.objects.link(handle_object)
    make_object_the_only_active_selection(handle_object)
    handle_solidify = handle_object.modifiers.new("HandleWall", "SOLIDIFY")
    handle_solidify.thickness = wall_thickness
    handle_solidify.offset = 0.0
    bpy.ops.object.modifier_apply(modifier="HandleWall")
    return handle_object


def resolve_handle_attachment_height_fractions(handle_height_span_option):
    if handle_height_span_option == "top_to_bottom":
        return 0.90, 0.10
    elif handle_height_span_option == "top_to_middle":
        return 0.90, 0.50
    else:
        return 0.78, 0.22


def build_true_semicircle_side_handle(base_radius, pitcher_height, wall_thickness,
                                      body_radius_at_upper_attachment, body_radius_at_lower_attachment,
                                      upper_attachment_height_fraction, lower_attachment_height_fraction):
    handle_center_x = math.cos(HANDLE_CENTER_AZIMUTH_RADIANS)
    handle_center_y = math.sin(HANDLE_CENTER_AZIMUTH_RADIANS)

    upper_attachment_height = pitcher_height * upper_attachment_height_fraction
    lower_attachment_height = pitcher_height * lower_attachment_height_fraction
    height_span = upper_attachment_height - lower_attachment_height
    mid_height = (upper_attachment_height + lower_attachment_height) / 2.0
    burial_depth = base_radius * 0.30
    pipe_radius = base_radius * 0.10
    ring_vertex_count = 18
    path_segment_count = 72

    average_body_radius_at_attachment = (body_radius_at_upper_attachment + body_radius_at_lower_attachment) / 2.0
    attachment_radial_distance = average_body_radius_at_attachment - burial_depth
    circle_radius = height_span / 2.0

    centerline_path_points = []
    for segment_index in range(path_segment_count + 1):
        arc_progress = segment_index / path_segment_count
        arc_angle = -math.pi / 2.0 + arc_progress * math.pi
        radial_distance = attachment_radial_distance + circle_radius * math.cos(arc_angle)
        height_position = mid_height + circle_radius * math.sin(arc_angle)
        point_x = handle_center_x * radial_distance
        point_y = handle_center_y * radial_distance
        centerline_path_points.append(Vector((point_x, point_y, height_position)))

    return finalise_handle_object(
        build_swept_pipe_handle_geometry(centerline_path_points, pipe_radius, ring_vertex_count),
        wall_thickness)


def build_rounded_rectangle_side_handle(base_radius, pitcher_height, wall_thickness,
                                        body_radius_at_upper_attachment, body_radius_at_lower_attachment,
                                        upper_attachment_height_fraction, lower_attachment_height_fraction):
    handle_center_x = math.cos(HANDLE_CENTER_AZIMUTH_RADIANS)
    handle_center_y = math.sin(HANDLE_CENTER_AZIMUTH_RADIANS)

    upper_attachment_height = pitcher_height * upper_attachment_height_fraction
    lower_attachment_height = pitcher_height * lower_attachment_height_fraction
    height_span = upper_attachment_height - lower_attachment_height
    burial_depth = base_radius * 0.30
    pipe_radius = base_radius * 0.10
    ring_vertex_count = 18
    segments_per_straight = 10
    segments_per_corner = 14

    average_body_radius_at_attachment = (body_radius_at_upper_attachment + body_radius_at_lower_attachment) / 2.0
    attachment_radial_distance = average_body_radius_at_attachment - burial_depth
    handle_outward_reach = height_span * 0.55
    corner_radius = min(handle_outward_reach * 0.35, height_span * 0.22)

    outward_radial_distance = attachment_radial_distance + handle_outward_reach
    bottom_corner_center_radial_distance = outward_radial_distance - corner_radius
    bottom_corner_center_height = lower_attachment_height + corner_radius
    top_corner_center_radial_distance = outward_radial_distance - corner_radius
    top_corner_center_height = upper_attachment_height - corner_radius

    centerline_radial_height_pairs = []

    for segment_index in range(segments_per_straight + 1):
        t = segment_index / segments_per_straight
        radial_distance = attachment_radial_distance + t * (handle_outward_reach - corner_radius)
        centerline_radial_height_pairs.append((radial_distance, lower_attachment_height))

    for segment_index in range(1, segments_per_corner + 1):
        t = segment_index / segments_per_corner
        corner_angle = -math.pi / 2.0 + t * (math.pi / 2.0)
        radial_distance = bottom_corner_center_radial_distance + corner_radius * math.cos(corner_angle)
        height_position = bottom_corner_center_height + corner_radius * math.sin(corner_angle)
        centerline_radial_height_pairs.append((radial_distance, height_position))

    for segment_index in range(1, segments_per_straight + 1):
        t = segment_index / segments_per_straight
        height_position = (lower_attachment_height + corner_radius) + t * (height_span - 2.0 * corner_radius)
        centerline_radial_height_pairs.append((outward_radial_distance, height_position))

    for segment_index in range(1, segments_per_corner + 1):
        t = segment_index / segments_per_corner
        corner_angle = 0.0 + t * (math.pi / 2.0)
        radial_distance = top_corner_center_radial_distance + corner_radius * math.cos(corner_angle)
        height_position = top_corner_center_height + corner_radius * math.sin(corner_angle)
        centerline_radial_height_pairs.append((radial_distance, height_position))

    for segment_index in range(1, segments_per_straight + 1):
        t = segment_index / segments_per_straight
        radial_distance = (outward_radial_distance - corner_radius) - t * (handle_outward_reach - corner_radius)
        centerline_radial_height_pairs.append((radial_distance, upper_attachment_height))

    centerline_path_points = []
    for radial_distance, height_position in centerline_radial_height_pairs:
        point_x = handle_center_x * radial_distance
        point_y = handle_center_y * radial_distance
        centerline_path_points.append(Vector((point_x, point_y, height_position)))

    return finalise_handle_object(
        build_swept_pipe_handle_geometry(centerline_path_points, pipe_radius, ring_vertex_count),
        wall_thickness)


def assign_single_material_to_object(target_object, material):
    target_object.data.materials.clear()
    target_object.data.materials.append(material)
    for polygon in target_object.data.polygons:
        polygon.material_index = 0


def join_pitcher_body_and_handle(body_object, handle_object):
    bpy.ops.object.select_all(action='DESELECT')
    body_object.select_set(True)
    handle_object.select_set(True)
    bpy.context.view_layer.objects.active = body_object
    bpy.ops.object.join()
    return body_object


def finalize_pitcher_object(pitcher_object, model_index):
    recalculate_outward_face_normals(pitcher_object)
    make_object_the_only_active_selection(pitcher_object)
    bpy.ops.object.shade_smooth()
    subdivision_modifier = pitcher_object.modifiers.new("Subdivision", "SUBSURF")
    subdivision_modifier.levels = SUBDIVISION_VIEWPORT_LEVEL
    subdivision_modifier.render_levels = SUBDIVISION_RENDER_LEVEL
    pitcher_object.name = "pitcher_{:03d}".format(model_index)
    pitcher_object.data.name = "pitcher_{:03d}_mesh".format(model_index)


def build_single_unique_pitcher(model_index):
    chosen_body_profile_shape = random.choice(BODY_PROFILE_SHAPE_OPTIONS)
    chosen_handle_height_span = random.choice(HANDLE_HEIGHT_SPAN_OPTIONS)
    chosen_handle_shape = random.choice(HANDLE_SHAPE_OPTIONS)

    overall_uniform_scale = random.uniform(0.85, 1.25)
    base_radius = random.uniform(0.048, 0.070) * overall_uniform_scale
    pitcher_height = random.uniform(0.150, 0.220) * overall_uniform_scale
    wall_thickness = random.uniform(0.0045, 0.0065) * overall_uniform_scale

    if chosen_body_profile_shape == "flower_vase_low_bulge_flared_top":
        silhouette_deviation_amount = base_radius * random.uniform(0.22, 0.38)
    elif chosen_body_profile_shape == "tapered_narrow_base":
        silhouette_deviation_amount = base_radius * random.uniform(0.10, 0.22)
    elif chosen_body_profile_shape == "tapered_wide_base":
        silhouette_deviation_amount = base_radius * random.uniform(0.10, 0.22)
    else:
        silhouette_deviation_amount = 0.0

    profile_vertices = build_body_outer_profile_vertices(
        base_radius, pitcher_height, chosen_body_profile_shape, silhouette_deviation_amount)
    body_object = create_revolved_hollow_body(profile_vertices, wall_thickness)
    deform_rim_into_pinched_pour_spout(body_object, pitcher_height, base_radius)
    body_ceramic_material = create_pitcher_body_ceramic_placeholder_material()
    assign_single_material_to_object(body_object, body_ceramic_material)

    upper_attachment_height_fraction, lower_attachment_height_fraction = resolve_handle_attachment_height_fractions(chosen_handle_height_span)
    body_radius_at_upper_attachment = compute_wall_radius_at_height_fraction(
        upper_attachment_height_fraction, base_radius, chosen_body_profile_shape, silhouette_deviation_amount)
    body_radius_at_lower_attachment = compute_wall_radius_at_height_fraction(
        lower_attachment_height_fraction, base_radius, chosen_body_profile_shape, silhouette_deviation_amount)

    if chosen_handle_shape == "true_semicircle":
        handle_object = build_true_semicircle_side_handle(
            base_radius, pitcher_height, wall_thickness,
            body_radius_at_upper_attachment, body_radius_at_lower_attachment,
            upper_attachment_height_fraction, lower_attachment_height_fraction)
    else:
        handle_object = build_rounded_rectangle_side_handle(
            base_radius, pitcher_height, wall_thickness,
            body_radius_at_upper_attachment, body_radius_at_lower_attachment,
            upper_attachment_height_fraction, lower_attachment_height_fraction)
    handle_ceramic_material = create_pitcher_handle_ceramic_placeholder_material()
    assign_single_material_to_object(handle_object, handle_ceramic_material)

    pitcher_object = join_pitcher_body_and_handle(body_object, handle_object)
    finalize_pitcher_object(pitcher_object, model_index)


def determine_expected_blend_file_path(model_index):
    absolute_output_directory = os.path.abspath(OUTPUT_DIRECTORY)
    return os.path.join(absolute_output_directory, "pitcher_{:03d}.blend".format(model_index))


def save_current_scene_as_blend_file(model_index):
    absolute_output_directory = os.path.abspath(OUTPUT_DIRECTORY)
    os.makedirs(absolute_output_directory, exist_ok=True)
    blend_file_path = determine_expected_blend_file_path(model_index)
    bpy.ops.wm.save_as_mainfile(filepath=blend_file_path)


def generate_requested_pitcher_models():
    requested_model_count = read_requested_model_count_from_command_arguments()
    already_generated_count = 0
    newly_generated_count = 0
    for model_index in range(requested_model_count):
        expected_blend_file_path = determine_expected_blend_file_path(model_index)
        if os.path.isfile(expected_blend_file_path):
            print(f"  [{model_index + 1}/{requested_model_count}] Skipping pitcher_{model_index:03d}.blend, already generated")
            already_generated_count += 1
            continue
        remove_all_scene_objects()
        random.seed(BASE_RANDOM_SEED + model_index)
        build_single_unique_pitcher(model_index)
        save_current_scene_as_blend_file(model_index)
        print(f"  [{model_index + 1}/{requested_model_count}] Generated pitcher_{model_index:03d}.blend")
        newly_generated_count += 1
    print(f"\nGeneration complete. Newly generated: {newly_generated_count}, skipped as already present: {already_generated_count}")


generate_requested_pitcher_models()