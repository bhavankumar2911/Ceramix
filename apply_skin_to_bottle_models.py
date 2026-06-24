import bpy
import bmesh
import math
import sys
import os
import glob

INPUT_DIRECTORY = "output/bottle/model"
OUTPUT_DIRECTORY = "output/bottle/design/abstract/5"
TEXTURE_REPEAT_AROUND_CIRCUMFERENCE = 1.0


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


def compute_arc_length_corrected_height_rings(vessel_object):
    mesh_data = vessel_object.data
    outer_radius_at_height = {}
    for vertex in mesh_data.vertices:
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

    return normalized_arc_length_at_height, total_arc_length


def estimate_average_circumference(vessel_object):
    mesh_data = vessel_object.data
    outer_radius_at_height = {}
    for vertex in mesh_data.vertices:
        vertex_radius = math.sqrt(vertex.co.x ** 2 + vertex.co.y ** 2)
        rounded_height = round(vertex.co.z, 5)
        if rounded_height not in outer_radius_at_height or vertex_radius > outer_radius_at_height[rounded_height]:
            outer_radius_at_height[rounded_height] = vertex_radius
    outer_radius_values = list(outer_radius_at_height.values())
    average_radius = sum(outer_radius_values) / len(outer_radius_values) if outer_radius_values else 0.01
    return 2.0 * math.pi * average_radius


def apply_arc_length_corrected_cylindrical_unwrap(vessel_object, total_height):
    normalized_arc_length_at_height, total_arc_length = compute_arc_length_corrected_height_rings(vessel_object)

    if not vessel_object.data.uv_layers:
        vessel_object.data.uv_layers.new(name="vessel_skin_uv")
    active_uv_layer = vessel_object.data.uv_layers.active

    mesh_data = vessel_object.data
    for polygon in mesh_data.polygons:
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


def correct_seam_uv_discontinuity(vessel_object):
    mesh_data = vessel_object.data
    active_uv_layer = mesh_data.uv_layers.active
    for polygon in mesh_data.polygons:
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


def build_plain_inner_surface_material():
    inner_material = bpy.data.materials.new("vessel_inner_surface_plain")
    inner_material.use_nodes = True
    principled_shader = inner_material.node_tree.nodes.get("Principled BSDF")
    principled_shader.inputs["Base Color"].default_value = (0.12, 0.11, 0.10, 1.0)
    principled_shader.inputs["Roughness"].default_value = 0.85
    return inner_material


def assign_polygons_to_outer_or_inner_material(vessel_object, skin_material, inner_material):
    mesh_data = vessel_object.data
    mesh_data.materials.clear()
    mesh_data.materials.append(skin_material)
    mesh_data.materials.append(inner_material)

    for polygon in mesh_data.polygons:
        polygon_center_x = sum(mesh_data.vertices[vertex_index].co.x for vertex_index in polygon.vertices) / len(polygon.vertices)
        polygon_center_y = sum(mesh_data.vertices[vertex_index].co.y for vertex_index in polygon.vertices) / len(polygon.vertices)
        polygon_radius = math.sqrt(polygon_center_x ** 2 + polygon_center_y ** 2)

        if polygon_radius < 1e-6:
            polygon.material_index = 1
            continue

        radial_unit_x = polygon_center_x / polygon_radius
        radial_unit_y = polygon_center_y / polygon_radius
        outward_alignment = polygon.normal.x * radial_unit_x + polygon.normal.y * radial_unit_y
        polygon.material_index = 0 if outward_alignment > 0.0 else 1


def determine_vessel_total_height(vessel_object):
    bounding_box_corners = [vessel_object.matrix_world @ corner.co for corner in vessel_object.data.vertices][:1]
    all_z_values = [vertex.co.z for vertex in vessel_object.data.vertices]
    return max(all_z_values) - min(all_z_values)


def apply_skin_to_single_blend_file(blend_file_path, image_file_path, output_blend_file_path):
    remove_all_scene_objects()
    bpy.ops.wm.open_mainfile(filepath=blend_file_path)

    vessel_object = find_primary_vessel_mesh_object()
    if vessel_object is None:
        print(f"  No mesh object found in {blend_file_path}, skipping.")
        return False

    make_object_the_only_active_selection(vessel_object)
    total_height = determine_vessel_total_height(vessel_object)

    apply_arc_length_corrected_cylindrical_unwrap(vessel_object, total_height)
    correct_seam_uv_discontinuity(vessel_object)

    skin_material = build_image_skin_material(image_file_path)
    inner_material = build_plain_inner_surface_material()
    assign_polygons_to_outer_or_inner_material(vessel_object, skin_material, inner_material)

    bpy.ops.wm.save_as_mainfile(filepath=output_blend_file_path)
    return True


def find_all_blend_files_in_directory(directory_path):
    return sorted(glob.glob(os.path.join(directory_path, "*.blend")))


def apply_skin_to_all_models():
    image_file_path = read_command_line_arguments()
    if image_file_path is None:
        print("Usage: blender -b --python apply_skin_to_bottle_models.py -- /path/to/image.png")
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
    for blend_file_index, blend_file_path in enumerate(blend_files):
        model_filename = os.path.basename(blend_file_path)
        output_blend_file_path = os.path.join(absolute_output_directory, model_filename)
        try:
            absolute_blend_file_path = os.path.abspath(blend_file_path)
            success = apply_skin_to_single_blend_file(absolute_blend_file_path, absolute_image_file_path, output_blend_file_path)
            if success:
                print(f"  [{blend_file_index + 1}/{len(blend_files)}] Textured {model_filename}")
                successfully_textured_count += 1
        except Exception as error:
            print(f"  Error texturing {blend_file_path}: {error}")

    print(f"\nSkin application complete. Total textured: {successfully_textured_count}")


apply_skin_to_all_models()