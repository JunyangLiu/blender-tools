import math
import hashlib

import bpy
from mathutils import Vector

from .constants import EXCLUDE_COLOR, TARGET_COLOR
from .scene_state import link_helper_object


def _material(name, color):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = color
    return material


def shared_surface_overlay_name(task_id, role):
    digest = hashlib.sha1(str(task_id).encode("utf-8")).hexdigest()[:10]
    return f"SMRN_MARK_BATCH_{str(role).upper()}_{digest}"


def surface_overlay_metrics(hit, marker_size):
    """Return the depth-tested face offset and stable display normal."""
    hit_obj = bpy.data.objects.get(hit["hit_object_name"])
    raycast_obj = bpy.data.objects.get(hit.get("raycast_object_name", ""))
    geometry_obj = raycast_obj if raycast_obj is not None and raycast_obj.type == "MESH" else hit_obj
    if geometry_obj is None or geometry_obj.type != "MESH":
        raise RuntimeError("命中的网格对象已不存在")
    face_index = int(hit["face_index"])
    if face_index < 0 or face_index >= len(geometry_obj.data.polygons):
        raise RuntimeError("命中面编号已失效；请先应用会改变拓扑的修改器")
    polygon = geometry_obj.data.polygons[face_index]
    world_vertices = [
        geometry_obj.matrix_world @ geometry_obj.data.vertices[index].co
        for index in polygon.vertices
    ]
    if len(world_vertices) < 3:
        raise RuntimeError("命中面无法建立覆盖标记")
    normal = Vector(hit["world_normal"])
    if normal.length_squared < 1.0e-12:
        normal = geometry_obj.matrix_world.to_3x3().inverted().transposed() @ polygon.normal
    normal.normalize()
    toward_viewer = Vector(hit.get("toward_viewer", normal))
    if toward_viewer.length_squared and normal.dot(toward_viewer.normalized()) < 0.0:
        normal.negate()
    edge_lengths = [
        (world_vertices[(index + 1) % len(world_vertices)] - vertex).length
        for index, vertex in enumerate(world_vertices)
    ]
    face_scale = sum(edge_lengths) / len(edge_lengths)
    size = max(1.0e-4, float(marker_size))
    surface_offset = max(1.0e-4, min(0.02, size * 0.012, face_scale * 0.01))
    return surface_offset, normal


def _record_geometry_object(context, record):
    working = bpy.data.objects.get(str(context.scene.get("smrn_surface_working_name", "")))
    if (
        working is not None
        and working.type == "MESH"
        and bool(working.get("smrn_mark_proxy_face_indices", False))
        and str(working.get("smrn_mark_proxy_source", "")) == record.hit_object_name
        and int(record.face_index) < len(working.data.polygons)
    ):
        return working
    return bpy.data.objects.get(record.hit_object_name)


def rebuild_task_surface_overlays(context, records, marker_size):
    """Collapse per-face helpers into one depth-tested mesh per role.

    The semantic records stay face-granular. Only their display is batched, so
    hundreds of marks no longer create hundreds of draw calls or marker disks.
    """
    records = list(records)
    old_names = {record.overlay_object_name for record in records if record.overlay_object_name}
    role_names = {
        role: shared_surface_overlay_name(records[0].task_id, role)
        for role in {record.role for record in records}
    } if records else {}
    old_names.update(role_names.values())
    for name in old_names:
        remove_overlay(name)

    grouped = {}
    for record in records:
        grouped.setdefault(record.role, []).append(record)
    colors = {"target": TARGET_COLOR, "exclude": EXCLUDE_COLOR}
    created = {}
    for role, role_records in grouped.items():
        vertices = []
        faces = []
        for record in role_records:
            geometry_obj = _record_geometry_object(context, record)
            face_index = int(record.face_index)
            if (
                geometry_obj is None
                or geometry_obj.type != "MESH"
                or face_index < 0
                or face_index >= len(geometry_obj.data.polygons)
            ):
                continue
            polygon = geometry_obj.data.polygons[face_index]
            normal = Vector(record.world_normal)
            if normal.length_squared < 1.0e-12:
                normal = geometry_obj.matrix_world.to_3x3().inverted().transposed() @ polygon.normal
            normal.normalize()
            world_vertices = [
                geometry_obj.matrix_world @ geometry_obj.data.vertices[index].co
                for index in polygon.vertices
            ]
            if len(world_vertices) < 3:
                continue
            start = len(vertices)
            offset = max(1.0e-4, float(record.surface_offset))
            vertices.extend(vertex + normal * offset for vertex in world_vertices)
            faces.append(list(range(start, start + len(world_vertices))))
        if not faces:
            continue
        name = role_names[role]
        mesh = bpy.data.meshes.new(name + "_Mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        overlay = bpy.data.objects.new(name, mesh)
        link_helper_object(overlay, context.scene)
        color = colors.get(role, (0.1, 0.8, 0.1, 0.72))
        overlay.data.materials.append(_material("SMRN_Target" if role == "target" else "SMRN_Exclude", color))
        overlay.show_in_front = False
        overlay.display_type = "TEXTURED"
        overlay.color = color
        overlay["smrn_annotation_only"] = True
        overlay["smrn_depth_tested"] = True
        overlay["smrn_surface_anchored"] = True
        overlay["smrn_batched_overlay"] = True
        overlay["smrn_role"] = "marker_do_not_export"
        overlay["smrn_mark_count"] = len(faces)
        created[role] = name
    return created


def create_surface_overlay(context, name, hit, color, marker_size):
    hit_obj = bpy.data.objects.get(hit["hit_object_name"])
    if hit_obj is None or hit_obj.type != "MESH":
        raise RuntimeError("命中的网格对象已不存在")
    # Keep semantic records attached to the untouched source, but draw the
    # overlay from the mesh that was actually ray-cast. A topology-identical
    # working candidate can have different vertex positions after flattening.
    raycast_obj = bpy.data.objects.get(hit.get("raycast_object_name", ""))
    geometry_obj = raycast_obj if raycast_obj is not None and raycast_obj.type == "MESH" else hit_obj
    if hit["face_index"] >= len(geometry_obj.data.polygons):
        raise RuntimeError("命中面编号已失效；请先应用会改变拓扑的修改器")
    polygon = geometry_obj.data.polygons[hit["face_index"]]
    world_vertices = [
        geometry_obj.matrix_world @ geometry_obj.data.vertices[index].co
        for index in polygon.vertices
    ]
    if len(world_vertices) < 3:
        raise RuntimeError("命中面无法建立覆盖标记")
    normal = Vector(hit["world_normal"])
    if normal.length_squared < 1.0e-12:
        normal = geometry_obj.matrix_world.to_3x3().inverted().transposed() @ polygon.normal
    normal.normalize()
    toward_viewer = Vector(hit.get("toward_viewer", normal))
    if toward_viewer.length_squared and normal.dot(toward_viewer.normalized()) < 0.0:
        normal.negate()
    edge_lengths = [
        (world_vertices[(index + 1) % len(world_vertices)] - vertex).length
        for index, vertex in enumerate(world_vertices)
    ]
    face_scale = sum(edge_lengths) / len(edge_lengths)
    size = max(1.0e-4, float(marker_size))
    surface_offset = max(1.0e-4, min(0.02, size * 0.012, face_scale * 0.01))
    vertices = [vertex + normal * surface_offset for vertex in world_vertices]
    faces = [list(range(len(vertices)))]
    center = Vector(hit["world_location"]) + normal * (surface_offset * 1.1)
    helper = Vector((0.0, 0.0, 1.0)) if abs(normal.z) <= 0.92 else Vector((1.0, 0.0, 0.0))
    axis_u = normal.cross(helper).normalized()
    axis_v = normal.cross(axis_u).normalized()
    center_index = len(vertices)
    vertices.append(center)
    ring_start = len(vertices)
    segments = 20
    for index in range(segments):
        angle = math.tau * index / segments
        vertices.append(center + axis_u * (math.cos(angle) * size) + axis_v * (math.sin(angle) * size))
    for index in range(segments):
        faces.append([center_index, ring_start + index, ring_start + ((index + 1) % segments)])
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    overlay = bpy.data.objects.new(name, mesh)
    link_helper_object(overlay, context.scene)
    overlay.data.materials.append(_material("SMRN_Target" if color[1] > color[0] else "SMRN_Exclude", color))
    overlay.show_in_front = False
    overlay.display_type = "TEXTURED"
    overlay.color = color
    overlay["smrn_annotation_only"] = True
    overlay["smrn_depth_tested"] = True
    overlay["smrn_surface_anchored"] = True
    overlay["smrn_surface_offset"] = surface_offset
    overlay["smrn_role"] = "marker_do_not_export"
    overlay["smrn_hit_object_name"] = hit["hit_object_name"]
    overlay["smrn_source_object_name"] = hit["source_object_name"]
    overlay["smrn_raycast_object_name"] = geometry_obj.name
    overlay["smrn_face_index"] = hit["face_index"]
    overlay["smrn_world_location"] = list(hit["world_location"])
    overlay["smrn_world_normal"] = list(normal)
    return overlay, surface_offset, normal


def remove_overlay(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        return
    mesh = obj.data if obj.type == "MESH" else None
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)
