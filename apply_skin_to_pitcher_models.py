import bpy
import bmesh
import math
import sys
import os
import glob

INPUT_DIRECTORY = "output/pitcher/model"
OUTPUT_DIRECTORY = "output/pitcher/design/scribble/5"
TEXTURE_REPEAT_AROUND_CIRCUMFERENCE = 1.0
PITCHER_BODY_MATERIAL_NAME = "pitcher_body_ceramic_placeholder"
PITCHER_HANDLE_MATERIAL_NAME = "pitcher_handle_ceramic_placeholder"


def read_command_line_arguments():
    if "--" in sys.argv:
        arguments_after_separator = sys.argv[sys.argv.index("--") + 1:]
        if len(arguments_after_separator) >= 1:
            return arguments_after_separator[0]
    return None


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


def find_material_slot_index_by_name(mesh_data, material_name):
    for material_slot_index, material_slot in enumerate(mesh_data.materials):
        if material_slot is not None and material_slot.name.startswith(material_name):
            return material_slot_index
    return None


def collect_body_vertex_indices(mesh_data, body_material_slot_index):
    body_vertex_index_set = set()
    for polygon in mesh_data.polygons:
        if polygon.material_index == body_material_slot_index:
            for vertex_index in polygon.vertices:
                body_vertex_index_set.add(vertex_index)
    return body_vertex_index_set


def compute_undeformed_rim_height(mesh_data, body_vertex_index_set):
    azimuth_bucket_count = 72
    highest_radius_bearing_height_per_bucket = {}
    for vertex_index in body_vertex_index_set:
        vertex = mesh_data.vertices[vertex_index]
        vertex_radius = math.sqrt(vertex.co.x ** 2 + vertex.co.y ** 2)
        if vertex_radius < 1e-6:
            continue
        vertex_azimuth = math.atan2(vertex.co.y, vertex.co.x)
        azimuth_bucket_index = int((vertex_azimuth + math.pi) / (2.0 * math.pi) * azimuth_bucket_count) % azimuth_bucket_count
        if azimuth_bucket_index not in highest_radius_bearing_height_per_bucket or vertex.co.z > highest_radius_bearing_height_per_bucket[azimuth_bucket_index]:
            highest_radius_bearing_height_per_bucket[azimuth_bucket_index] = vertex.co.z

    per_bucket_top_heights = sorted(highest_radius_bearing_height_per_bucket.values())
    median_index = len(per_bucket_top_heights) // 2
    return per_bucket_top_heights[median_index] if per_bucket_top_heights else 0.0


def compute_arc_length_corrected_height_rings(mesh_data, body_vertex_index_set):
    undeformed_rim_height = compute_undeformed_rim_height(mesh_data, body_vertex_index_set)

    outer_radius_at_height = {}
    for vertex_index in body_vertex_index_set:
        vertex = mesh_data.vertices[vertex_index]
        if vertex.co.z > undeformed_rim_height:
            continue
        vertex_radius = math.sqrt(vertex.co.x ** 2 + vertex.co.y ** 2)
        rounded_height = round(vertex.co.z, 5)
        if rounded_height not in outer_radius_at_height or vertex_radius > outer_radius_at_height[rounded_height]:
            outer_radius_at_height[rounded_height] = vertex_radius

    sorted_height_values = sorted(outer_radius_at_height.keys())

    cumulative_arc_length_at_height = {}
    accumulated_arc_length = 0.0
    previous_height_value = None
    previous_ring_radius = None
    for height_value in sorted_height_values:
        current_ring_radius = outer_radius_at_height[height_value]
        if previous_height_value is not None:
            height_step = height_value - previous_height_value
            radius_step = current_ring_radius - previous_ring_radius
            accumulated_arc_length += math.sqrt(height_step ** 2 + radius_step ** 2)
        cumulative_arc_length_at_height[height_value] = accumulated_arc_length
        previous_height_value = height_value
        previous_ring_radius = current_ring_radius

    total_arc_length = accumulated_arc_length if accumulated_arc_length > 0.0 else 1.0
    normalized_arc_length_at_height = {
        height_value: arc_length / total_arc_length
        for height_value, arc_length in cumulative_arc_length_at_height.items()}

    return normalized_arc_length_at_height


def apply_arc_length_corrected_cylindrical_unwrap_to_body(vessel_object, body_vertex_index_set, body_material_slot_index):
    mesh_data = vessel_object.data
    normalized_arc_length_at_height = compute_arc_length_corrected_height_rings(mesh_data, body_vertex_index_set)

    if not mesh_data.uv_layers:
        mesh_data.uv_layers.new(name="vessel_skin_uv")
    active_uv_layer = mesh_data.uv_layers.active

    for polygon in mesh_data.polygons:
        if polygon.material_index != body_material_slot_index:
            continue
        for loop_index in polygon.loop_indices:
            loop = mesh_data.loops[loop_index]
            vertex = mesh_data.vertices[loop.vertex_index]
            vertex_x, vertex_y, vertex_z = vertex.co.x, vertex.co.y, vertex.co.z

            azimuth_angle = math.atan2(vertex_y, vertex_x)
            normalized_azimuth = (azimuth_angle + math.pi) / (2.0 * math.pi)

            rounded_height = round(vertex_z, 5)
            if rounded_height in normalized_arc_length_at_height:
                normalized_height = normalized_arc_length_at_height[rounded_height]
            else:
                closest_height = min(normalized_arc_length_at_height.keys(), key=lambda h: abs(h - rounded_height))
                normalized_height = normalized_arc_length_at_height[closest_height]

            uv_u = normalized_azimuth * TEXTURE_REPEAT_AROUND_CIRCUMFERENCE
            uv_v = normalized_height

            active_uv_layer.data[loop_index].uv = (uv_u, uv_v)


def correct_seam_uv_discontinuity_on_body(vessel_object, body_material_slot_index):
    mesh_data = vessel_object.data
    active_uv_layer = mesh_data.uv_layers.active
    for polygon in mesh_data.polygons:
        if polygon.material_index != body_material_slot_index:
            continue
        loop_uv_values = [active_uv_layer.data[loop_index].uv[0] for loop_index in polygon.loop_indices]
        maximum_u_difference = max(loop_uv_values) - min(loop_uv_values)
        if maximum_u_difference > 0.5:
            for loop_index in polygon.loop_indices:
                current_uv = active_uv_layer.data[loop_index].uv
                if current_uv[0] < 0.5:
                    active_uv_layer.data[loop_index].uv = (current_uv[0] + 1.0, current_uv[1])


def build_image_skin_material(image_file_path):
    skin_material = bpy.data.materials.new("vessel_skin_material")
    skin_material.use_nodes = True
    node_tree = skin_material.node_tree
    node_tree.nodes.clear()

    texture_coordinate_node = node_tree.nodes.new('ShaderNodeTexCoord')
    image_texture_node = node_tree.nodes.new('ShaderNodeTexImage')
    principled_bsdf_node = node_tree.nodes.new('ShaderNodeBsdfPrincipled')
    material_output_node = node_tree.nodes.new('ShaderNodeOutputMaterial')

    loaded_image = bpy.data.images.load(image_file_path)
    image_texture_node.image = loaded_image
    image_texture_node.extension = 'EXTEND'

    node_tree.links.new(texture_coordinate_node.outputs['UV'], image_texture_node.inputs['Vector'])
    node_tree.links.new(image_texture_node.outputs['Color'], principled_bsdf_node.inputs['Base Color'])
    node_tree.links.new(principled_bsdf_node.outputs['BSDF'], material_output_node.inputs['Surface'])

    principled_bsdf_node.inputs['Roughness'].default_value = 0.35
    return skin_material


def build_light_ceramic_material(material_name):
    light_ceramic_material = bpy.data.materials.new(material_name)
    light_ceramic_material.use_nodes = True
    light_ceramic_principled_shader = light_ceramic_material.node_tree.nodes.get("Principled BSDF")
    light_ceramic_principled_shader.inputs["Base Color"].default_value = (0.92, 0.90, 0.84, 1.0)
    light_ceramic_principled_shader.inputs["Roughness"].default_value = 0.55
    return light_ceramic_material


def assign_polygons_to_skin_inner_body_or_handle_material(vessel_object, original_material_index_per_polygon,
                                                          original_body_material_slot_index,
                                                          original_handle_material_slot_index,
                                                          skin_material, inner_body_ceramic_material,
                                                          handle_ceramic_material):
    mesh_data = vessel_object.data
    mesh_data.materials.clear()
    mesh_data.materials.append(skin_material)
    mesh_data.materials.append(inner_body_ceramic_material)
    mesh_data.materials.append(handle_ceramic_material)

    for polygon, original_material_index in zip(mesh_data.polygons, original_material_index_per_polygon):
        if original_material_index == original_handle_material_slot_index:
            polygon.material_index = 2
            continue

        polygon_vertex_indices = polygon.vertices
        polygon_center_x = sum(mesh_data.vertices[vertex_index].co.x for vertex_index in polygon_vertex_indices) / len(polygon_vertex_indices)
        polygon_center_y = sum(mesh_data.vertices[vertex_index].co.y for vertex_index in polygon_vertex_indices) / len(polygon_vertex_indices)
        polygon_radius = math.sqrt(polygon_center_x ** 2 + polygon_center_y ** 2)

        if polygon_radius < 1e-6:
            polygon.material_index = 1
            continue

        radial_unit_x = polygon_center_x / polygon_radius
        radial_unit_y = polygon_center_y / polygon_radius
        outward_alignment = polygon.normal.x * radial_unit_x + polygon.normal.y * radial_unit_y
        polygon.material_index = 0 if outward_alignment > 0.0 else 1


def apply_skin_to_single_blend_file(blend_file_path, image_file_path, output_blend_file_path):
    remove_all_scene_objects()
    bpy.ops.wm.open_mainfile(filepath=blend_file_path)

    vessel_object = find_primary_vessel_mesh_object()
    if vessel_object is None:
        print(f"  No mesh object found in {blend_file_path}, skipping.")
        return False

    make_object_the_only_active_selection(vessel_object)
    mesh_data = vessel_object.data

    original_body_material_slot_index = find_material_slot_index_by_name(mesh_data, PITCHER_BODY_MATERIAL_NAME)
    original_handle_material_slot_index = find_material_slot_index_by_name(mesh_data, PITCHER_HANDLE_MATERIAL_NAME)

    if original_body_material_slot_index is None:
        print(f"  No body material found in {blend_file_path}, skipping.")
        return False

    original_material_index_per_polygon = [polygon.material_index for polygon in mesh_data.polygons]
    body_vertex_index_set = collect_body_vertex_indices(mesh_data, original_body_material_slot_index)

    apply_arc_length_corrected_cylindrical_unwrap_to_body(vessel_object, body_vertex_index_set, original_body_material_slot_index)
    correct_seam_uv_discontinuity_on_body(vessel_object, original_body_material_slot_index)

    skin_material = build_image_skin_material(image_file_path)
    inner_body_ceramic_material = build_light_ceramic_material("vessel_inner_body_surface_ceramic")
    handle_ceramic_material = build_light_ceramic_material("vessel_handle_surface_ceramic")

    assign_polygons_to_skin_inner_body_or_handle_material(
        vessel_object, original_material_index_per_polygon,
        original_body_material_slot_index, original_handle_material_slot_index,
        skin_material, inner_body_ceramic_material, handle_ceramic_material)

    bpy.ops.wm.save_as_mainfile(filepath=output_blend_file_path)
    return True


def find_all_blend_files_in_directory(directory_path):
    return sorted(glob.glob(os.path.join(directory_path, "*.blend")))


def apply_skin_to_all_models():
    image_file_path = read_command_line_arguments()
    if image_file_path is None:
        print("Usage: blender -b --python apply_skin_to_pitcher_models.py -- /path/to/image.png")
        return

    absolute_image_file_path = os.path.abspath(image_file_path)
    absolute_output_directory = os.path.abspath(OUTPUT_DIRECTORY)
    os.makedirs(absolute_output_directory, exist_ok=True)

    blend_files = find_all_blend_files_in_directory(INPUT_DIRECTORY)
    if not blend_files:
        print(f"No .blend files found in {INPUT_DIRECTORY}")
        return

    print(f"Applying skin from {absolute_image_file_path} to {len(blend_files)} models...")
    successfully_textured_count = 0
    already_textured_skipped_count = 0
    for blend_file_index, blend_file_path in enumerate(blend_files):
        model_filename = os.path.basename(blend_file_path)
        output_blend_file_path = os.path.join(absolute_output_directory, model_filename)

        if os.path.isfile(output_blend_file_path):
            print(f"  [{blend_file_index + 1}/{len(blend_files)}] Skipping {model_filename}, already textured")
            already_textured_skipped_count += 1
            continue

        try:
            absolute_blend_file_path = os.path.abspath(blend_file_path)
            success = apply_skin_to_single_blend_file(absolute_blend_file_path, absolute_image_file_path, output_blend_file_path)
            if success:
                print(f"  [{blend_file_index + 1}/{len(blend_files)}] Textured {model_filename}")
                successfully_textured_count += 1
        except Exception as error:
            print(f"  Error texturing {blend_file_path}: {error}")

    print(f"\nSkin application complete. Newly textured: {successfully_textured_count}, skipped as already present: {already_textured_skipped_count}")


apply_skin_to_all_models()