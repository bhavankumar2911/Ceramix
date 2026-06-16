import bpy
import bmesh
import math
import random
import sys
import os
from mathutils import Vector

OUTPUT_DIRECTORY = "output/ewer_models"
BASE_RANDOM_SEED = 42
REVOLUTION_SEGMENT_COUNT = 96
WALL_VERTICAL_SEGMENT_COUNT = 48
NECK_TAPER_START_FRACTION = 0.78
SUBDIVISION_VIEWPORT_LEVEL = 1
SUBDIVISION_RENDER_LEVEL = 2

SPOUT_TYPE_OPTIONS = ["pinched_pour_lip", "protruding_tube_spout"]
BODY_PROFILE_SHAPE_OPTIONS = ["straight_cylinder", "convex_outward_barrel", "concave_inward_waist"]


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


def create_cork_placeholder_material():
    cork_material = bpy.data.materials.new("cork_stopper_placeholder")
    cork_material.use_nodes = True
    principled_shader = cork_material.node_tree.nodes.get("Principled BSDF")
    principled_shader.inputs["Base Color"].default_value = (0.74, 0.56, 0.34, 1.0)
    principled_shader.inputs["Roughness"].default_value = 0.85
    return cork_material


def recalculate_outward_face_normals(target_object):
    working_bmesh = bmesh.new()
    working_bmesh.from_mesh(target_object.data)
    bmesh.ops.recalc_face_normals(working_bmesh, faces=working_bmesh.faces)
    working_bmesh.to_mesh(target_object.data)
    working_bmesh.free()


def build_body_outer_profile_vertices(base_radius, body_height, body_profile_shape,
                                      silhouette_deviation_amount, has_neck_taper,
                                      neck_opening_radius):
    profile_vertices = [Vector((0.0, 0.0, 0.0)), Vector((base_radius, 0.0, 0.0))]
    for vertical_index in range(1, WALL_VERTICAL_SEGMENT_COUNT + 1):
        height_fraction = vertical_index / WALL_VERTICAL_SEGMENT_COUNT
        height_position = height_fraction * body_height
        if body_profile_shape == "convex_outward_barrel":
            wall_radius = base_radius + silhouette_deviation_amount * math.sin(math.pi * height_fraction)
        elif body_profile_shape == "concave_inward_waist":
            wall_radius = base_radius - silhouette_deviation_amount * math.sin(math.pi * height_fraction)
        else:
            wall_radius = base_radius
        if has_neck_taper and height_fraction > NECK_TAPER_START_FRACTION:
            taper_progress = (height_fraction - NECK_TAPER_START_FRACTION) / (1.0 - NECK_TAPER_START_FRACTION)
            smooth_taper = taper_progress * taper_progress * (3.0 - 2.0 * taper_progress)
            wall_radius = wall_radius * (1.0 - smooth_taper) + neck_opening_radius * smooth_taper
        profile_vertices.append(Vector((max(wall_radius, 0.002), 0.0, height_position)))
    return profile_vertices


def create_revolved_hollow_body(profile_vertices, wall_thickness):
    body_mesh = bpy.data.meshes.new("ewer_body_mesh")
    profile_edges = [(edge_index, edge_index + 1) for edge_index in range(len(profile_vertices) - 1)]
    body_mesh.from_pydata([tuple(point) for point in profile_vertices], profile_edges, [])
    body_mesh.update()
    body_object = bpy.data.objects.new("ewer_body", body_mesh)
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


def apply_pinched_pour_lip(body_object, lip_azimuth_window, lip_raise_height, lip_radial_extension):
    body_mesh = body_object.data
    highest_vertex_height = max(vertex.co.z for vertex in body_mesh.vertices)
    rim_selection_band = (highest_vertex_height) * 0.06
    deformation_bmesh = bmesh.new()
    deformation_bmesh.from_mesh(body_mesh)
    for vertex in deformation_bmesh.verts:
        if vertex.co.z > highest_vertex_height - rim_selection_band:
            azimuth_angle = math.atan2(vertex.co.y, vertex.co.x)
            if abs(azimuth_angle) < lip_azimuth_window:
                proximity_factor = math.cos((azimuth_angle / lip_azimuth_window) * (math.pi / 2.0))
                vertex.co.z += lip_raise_height * proximity_factor
                radial_length = math.sqrt(vertex.co.x ** 2 + vertex.co.y ** 2)
                if radial_length > 0.0:
                    outward_x = vertex.co.x / radial_length
                    outward_y = vertex.co.y / radial_length
                    vertex.co.x += outward_x * lip_radial_extension * proximity_factor
                    vertex.co.y += outward_y * lip_radial_extension * proximity_factor
    deformation_bmesh.to_mesh(body_mesh)
    deformation_bmesh.free()


def build_tapered_closed_solid_mesh(ring_radius_and_height_pairs, ring_vertex_count):
    solid_bmesh = bmesh.new()
    all_ring_vertices = []
    for ring_radius, ring_height in ring_radius_and_height_pairs:
        single_ring_vertices = []
        for ring_index in range(ring_vertex_count):
            ring_angle = 2.0 * math.pi * ring_index / ring_vertex_count
            single_ring_vertices.append(solid_bmesh.verts.new((
                ring_radius * math.cos(ring_angle),
                ring_radius * math.sin(ring_angle),
                ring_height)))
        all_ring_vertices.append(single_ring_vertices)
    for ring_pair_index in range(len(all_ring_vertices) - 1):
        lower_ring = all_ring_vertices[ring_pair_index]
        upper_ring = all_ring_vertices[ring_pair_index + 1]
        for ring_index in range(ring_vertex_count):
            next_index = (ring_index + 1) % ring_vertex_count
            solid_bmesh.faces.new((
                lower_ring[ring_index],
                lower_ring[next_index],
                upper_ring[next_index],
                upper_ring[ring_index]))
    solid_bmesh.faces.new(list(reversed(all_ring_vertices[0])))
    solid_bmesh.faces.new(all_ring_vertices[-1])
    return solid_bmesh


def build_protruding_tube_spout(base_radius, body_height, wall_thickness, body_object_to_blend):
    spout_attachment_height = body_height * random.uniform(0.62, 0.78)
    spout_base_radius = base_radius * random.uniform(0.28, 0.38)
    spout_tip_radius = spout_base_radius * random.uniform(0.55, 0.80)
    spout_length = body_height * random.uniform(0.35, 0.60)
    spout_tilt_angle = math.radians(random.uniform(40.0, 65.0))
    ring_vertex_count = 24

    spout_wall_attachment_offset = base_radius * 0.45
    spout_root_burial_depth = spout_wall_attachment_offset / math.sin(spout_tilt_angle) + base_radius * 0.30

    tube_bmesh = bmesh.new()
    root_ring_vertices = []
    base_ring_vertices = []
    tip_ring_vertices = []
    for ring_index in range(ring_vertex_count):
        ring_angle = 2.0 * math.pi * ring_index / ring_vertex_count
        root_ring_vertices.append(tube_bmesh.verts.new((
            spout_base_radius * math.cos(ring_angle),
            spout_base_radius * math.sin(ring_angle),
            -spout_root_burial_depth)))
        base_ring_vertices.append(tube_bmesh.verts.new((
            spout_base_radius * math.cos(ring_angle),
            spout_base_radius * math.sin(ring_angle),
            0.0)))
        tip_ring_vertices.append(tube_bmesh.verts.new((
            spout_tip_radius * math.cos(ring_angle),
            spout_tip_radius * math.sin(ring_angle),
            spout_length)))
    for ring_index in range(ring_vertex_count):
        next_index = (ring_index + 1) % ring_vertex_count
        tube_bmesh.faces.new((
            root_ring_vertices[ring_index],
            root_ring_vertices[next_index],
            base_ring_vertices[next_index],
            base_ring_vertices[ring_index]))
        tube_bmesh.faces.new((
            base_ring_vertices[ring_index],
            base_ring_vertices[next_index],
            tip_ring_vertices[next_index],
            tip_ring_vertices[ring_index]))

    spout_mesh = bpy.data.meshes.new("ewer_spout_mesh")
    tube_bmesh.to_mesh(spout_mesh)
    tube_bmesh.free()
    spout_object = bpy.data.objects.new("ewer_spout", spout_mesh)
    bpy.context.scene.collection.objects.link(spout_object)
    make_object_the_only_active_selection(spout_object)

    spout_wall_modifier = spout_object.modifiers.new("SpoutWall", "SOLIDIFY")
    spout_wall_modifier.thickness = wall_thickness
    spout_wall_modifier.offset = 0.0
    bpy.ops.object.modifier_apply(modifier="SpoutWall")

    spout_object.rotation_euler = (0.0, spout_tilt_angle, 0.0)
    spout_object.location = Vector((spout_wall_attachment_offset, 0.0, spout_attachment_height))
    make_object_the_only_active_selection(spout_object)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    shrinkwrap_modifier = spout_object.modifiers.new("BaseBlend", "SHRINKWRAP")
    shrinkwrap_modifier.target = body_object_to_blend
    shrinkwrap_modifier.wrap_method = 'PROJECT'
    shrinkwrap_modifier.use_project_x = False
    shrinkwrap_modifier.use_project_y = False
    shrinkwrap_modifier.use_project_z = False
    shrinkwrap_modifier.use_negative_direction = True
    shrinkwrap_modifier.use_positive_direction = True
    shrinkwrap_modifier.wrap_mode = 'ON_SURFACE'
    shrinkwrap_modifier.vertex_group = ""

    vertex_group = spout_object.vertex_groups.new(name="base_blend_influence")
    spout_mesh_after_transform = spout_object.data
    lowest_z = min(vertex.co.z for vertex in spout_mesh_after_transform.vertices)
    highest_z = max(vertex.co.z for vertex in spout_mesh_after_transform.vertices)
    blend_band_height = (highest_z - lowest_z) * 0.22
    blend_band_bottom = lowest_z
    blend_band_top = lowest_z + blend_band_height
    for vertex in spout_mesh_after_transform.vertices:
        if vertex.co.z <= blend_band_top:
            blend_fraction = 1.0 - max(0.0, (vertex.co.z - blend_band_bottom) / (blend_band_top - blend_band_bottom))
            vertex_group.add([vertex.index], blend_fraction, 'REPLACE')
        else:
            vertex_group.add([vertex.index], 0.0, 'REPLACE')
    shrinkwrap_modifier.vertex_group = vertex_group.name
    bpy.ops.object.modifier_apply(modifier="BaseBlend")

    recalculate_outward_face_normals(spout_object)
    return spout_object


def build_side_handle(base_radius, body_height):
    handle_thickness = base_radius * 0.13
    handle_curve_data = bpy.data.curves.new("ewer_handle_curve", type='CURVE')
    handle_curve_data.dimensions = '3D'
    handle_spline = handle_curve_data.splines.new('BEZIER')
    handle_spline.bezier_points.add(3)
    handle_control_positions = [
        Vector((-base_radius * 0.90, 0.0, body_height * 0.72)),
        Vector((-base_radius * 1.90, 0.0, body_height * 0.60)),
        Vector((-base_radius * 2.00, 0.0, body_height * 0.38)),
        Vector((-base_radius * 0.95, 0.0, body_height * 0.24))]
    for bezier_point, control_position in zip(handle_spline.bezier_points, handle_control_positions):
        bezier_point.co = control_position
        bezier_point.handle_left_type = 'AUTO'
        bezier_point.handle_right_type = 'AUTO'
    handle_curve_data.bevel_depth = handle_thickness
    handle_curve_data.bevel_resolution = 6
    handle_curve_data.fill_mode = 'FULL'

    handle_object = bpy.data.objects.new("ewer_handle", handle_curve_data)
    bpy.context.scene.collection.objects.link(handle_object)
    make_object_the_only_active_selection(handle_object)
    bpy.ops.object.convert(target='MESH')
    return bpy.context.active_object


def build_cork_stopper(base_radius, body_height, neck_opening_radius):
    cork_bottom_radius = neck_opening_radius * 0.92
    cork_top_radius = neck_opening_radius * 1.15
    cork_height = base_radius * 0.50
    ring_vertex_count = 24

    cork_bmesh = bmesh.new()
    bottom_ring_vertices = []
    top_ring_vertices = []
    for ring_index in range(ring_vertex_count):
        ring_angle = 2.0 * math.pi * ring_index / ring_vertex_count
        bottom_ring_vertices.append(cork_bmesh.verts.new((
            cork_bottom_radius * math.cos(ring_angle),
            cork_bottom_radius * math.sin(ring_angle),
            0.0)))
        top_ring_vertices.append(cork_bmesh.verts.new((
            cork_top_radius * math.cos(ring_angle),
            cork_top_radius * math.sin(ring_angle),
            cork_height)))
    for ring_index in range(ring_vertex_count):
        next_index = (ring_index + 1) % ring_vertex_count
        cork_bmesh.faces.new((
            bottom_ring_vertices[ring_index],
            bottom_ring_vertices[next_index],
            top_ring_vertices[next_index],
            top_ring_vertices[ring_index]))
    cork_bmesh.faces.new(list(reversed(bottom_ring_vertices)))
    cork_bmesh.faces.new(top_ring_vertices)

    cork_mesh = bpy.data.meshes.new("ewer_cork_mesh")
    cork_bmesh.to_mesh(cork_mesh)
    cork_bmesh.free()
    cork_object = bpy.data.objects.new("ewer_cork", cork_mesh)
    bpy.context.scene.collection.objects.link(cork_object)
    cork_object.location = Vector((0.0, 0.0, body_height - cork_height * 0.35))
    make_object_the_only_active_selection(cork_object)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    recalculate_outward_face_normals(cork_object)
    return cork_object


def join_ceramic_parts_into_single_mesh(body_object, additional_ceramic_parts):
    bpy.ops.object.select_all(action='DESELECT')
    body_object.select_set(True)
    for ceramic_part in additional_ceramic_parts:
        ceramic_part.select_set(True)
    bpy.context.view_layer.objects.active = body_object
    bpy.ops.object.join()
    return body_object


def finalize_ceramic_object(body_object, model_index, ceramic_material):
    recalculate_outward_face_normals(body_object)
    make_object_the_only_active_selection(body_object)
    bpy.ops.object.shade_smooth()
    subdivision_modifier = body_object.modifiers.new("Subdivision", "SUBSURF")
    subdivision_modifier.levels = SUBDIVISION_VIEWPORT_LEVEL
    subdivision_modifier.render_levels = SUBDIVISION_RENDER_LEVEL
    body_object.data.materials.clear()
    body_object.data.materials.append(ceramic_material)
    for polygon in body_object.data.polygons:
        polygon.material_index = 0
    body_object.name = "ewer_{:03d}".format(model_index)
    body_object.data.name = "ewer_{:03d}_mesh".format(model_index)


def build_single_unique_ewer(model_index):
    chosen_spout_type = random.choice(SPOUT_TYPE_OPTIONS)
    chosen_body_profile_shape = random.choice(BODY_PROFILE_SHAPE_OPTIONS)
    has_cork_stopper = random.choice([True, False])
    has_side_handle = random.choice([True, False])

    overall_uniform_scale = random.uniform(0.85, 1.25)
    base_radius = random.uniform(0.050, 0.085) * overall_uniform_scale
    body_height = random.uniform(0.180, 0.300) * overall_uniform_scale
    wall_thickness = random.uniform(0.0045, 0.0065) * overall_uniform_scale
    neck_opening_radius = base_radius * random.uniform(0.40, 0.55)

    if chosen_body_profile_shape == "convex_outward_barrel":
        silhouette_deviation_amount = base_radius * random.uniform(0.15, 0.35)
    elif chosen_body_profile_shape == "concave_inward_waist":
        silhouette_deviation_amount = base_radius * random.uniform(0.12, 0.25)
    else:
        silhouette_deviation_amount = 0.0

    profile_vertices = build_body_outer_profile_vertices(
        base_radius, body_height, chosen_body_profile_shape,
        silhouette_deviation_amount, has_cork_stopper, neck_opening_radius)
    body_object = create_revolved_hollow_body(profile_vertices, wall_thickness)

    additional_ceramic_parts = []

    if chosen_spout_type == "pinched_pour_lip":
        apply_pinched_pour_lip(
            body_object,
            lip_azimuth_window=math.radians(38.0),
            lip_raise_height=body_height * random.uniform(0.06, 0.11),
            lip_radial_extension=base_radius * random.uniform(0.18, 0.32))
    else:
        spout_object = build_protruding_tube_spout(base_radius, body_height, wall_thickness, body_object)
        additional_ceramic_parts.append(spout_object)

    if has_side_handle:
        handle_object = build_side_handle(base_radius, body_height)
        additional_ceramic_parts.append(handle_object)

    body_object = join_ceramic_parts_into_single_mesh(body_object, additional_ceramic_parts)

    ceramic_material = create_ceramic_placeholder_material()
    finalize_ceramic_object(body_object, model_index, ceramic_material)

    if has_cork_stopper:
        cork_object = build_cork_stopper(base_radius, body_height, neck_opening_radius)
        cork_material = create_cork_placeholder_material()
        cork_object.data.materials.append(cork_material)
        make_object_the_only_active_selection(cork_object)
        bpy.ops.object.shade_smooth()
        cork_object.name = "ewer_{:03d}_cork".format(model_index)
        cork_object.data.name = "ewer_{:03d}_cork_mesh".format(model_index)


def save_current_scene_as_blend_file(model_index):
    absolute_output_directory = os.path.abspath(OUTPUT_DIRECTORY)
    os.makedirs(absolute_output_directory, exist_ok=True)
    blend_file_path = os.path.join(absolute_output_directory, "ewer_{:03d}.blend".format(model_index))
    bpy.ops.wm.save_as_mainfile(filepath=blend_file_path)


def generate_requested_ewer_models():
    requested_model_count = read_requested_model_count_from_command_arguments()
    for model_index in range(requested_model_count):
        remove_all_scene_objects()
        random.seed(BASE_RANDOM_SEED + model_index)
        build_single_unique_ewer(model_index)
        save_current_scene_as_blend_file(model_index)


generate_requested_ewer_models()