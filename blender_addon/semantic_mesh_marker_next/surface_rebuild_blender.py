"""Feature-locked local reconstruction of marked source mesh surfaces.

The visible candidate is only a wire preview of the affected region.  A full
working copy is kept recoverably beside it so confirmation can swap only the
source object's mesh datablock, preserving the source object identity and all
external references.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
import numpy as np

from .anchors import source_snapshot
from .constants import EXCLUDE_ROLE, SOURCE_NAME_KEY, TARGET_ROLE
from .scene_state import ensure_scene_roots, keep_model_visible
from .storage import load_all_marks, set_active_source


CANDIDATE_PREFIX = "SMRN_SURFACE_CANDIDATE_"
WORKING_PREFIX = "SMRN_SURFACE_WORKING_FULL_"
ARCHIVE_COLLECTION_NAME = "SMR_01B_原网面恢复检查点"
REPORT_KEY = "smrn_surface_rebuild_report_json"
PREVIEW_MATERIAL_NAME = "SMRN_局部网面候选_橙色半透明"


def _remove_object(obj):
    mesh = obj.data if obj is not None and obj.type == "MESH" else None
    if obj is not None:
        bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _checkpoint(scene, source):
    current = Path(bpy.data.filepath) if bpy.data.filepath else None
    if current is None:
        raise ValueError("当前 .blend 尚未保存，无法建立可靠源检查点")
    fingerprint = source_snapshot(source)["fingerprint"]
    existing = str(scene.get("smrn_surface_checkpoint_path", ""))
    existing_fingerprint = str(scene.get("smrn_surface_checkpoint_fingerprint", ""))
    if existing and existing_fingerprint == fingerprint and Path(existing).exists():
        return existing
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = current.with_name(f"{current.stem}_before_smrn_surface_{stamp}{current.suffix}")
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
    scene["smrn_surface_checkpoint_path"] = str(path)
    scene["smrn_surface_checkpoint_fingerprint"] = fingerprint
    return str(path)


def _source_and_records(scene):
    source = bpy.data.objects.get(str(scene.get(SOURCE_NAME_KEY, "")))
    if source is None or source.type != "MESH":
        raise ValueError("请先把需要重构网面的那个网格对象设为当前语义源")
    records = load_all_marks(scene)
    targets = [record for record in records if record.role == TARGET_ROLE]
    excludes = [record for record in records if record.role == EXCLUDE_ROLE]
    if not targets:
        raise ValueError("至少需要 1 个绿色标记来指定重构区域")
    wrong = [record for record in targets if record.hit_object_name != source.name]
    if wrong:
        names = sorted({record.hit_object_name for record in wrong})
        raise ValueError(
            "绿色标记必须全部落在当前语义源本体；当前还有标记属于：" + "、".join(names)
        )
    snapshot = source_snapshot(source)
    for record in targets + excludes:
        if record.hit_object_name != source.name:
            continue
        if record.source_fingerprint and record.source_fingerprint != snapshot["fingerprint"]:
            raise ValueError("源网格在标记后已经变化，请清除本轮标记并重新标记")
    return source, targets, excludes, snapshot


def _object_scale(obj):
    lengths = [obj.matrix_world.to_3x3().col[index].length for index in range(3)]
    valid = [value for value in lengths if value > 1.0e-8]
    return sum(valid) / len(valid) if valid else 1.0


def _face_center(face):
    return face.calc_center_median()


def _seed_face_indices(records, face_count):
    return sorted({int(record.face_index) for record in records if 0 <= int(record.face_index) < face_count})


def _normal_hint_from_records(source, targets, excludes, normal_mode):
    if normal_mode == "AUTO":
        return None
    records = sorted(targets, key=lambda record: record.id)[:1]
    if normal_mode == "RED_REFERENCE":
        records = [record for record in excludes if record.hit_object_name == source.name]
        if not records:
            raise ValueError("法向选择了红色参考面，但当前语义源上没有红色标记")
    normals = []
    world_to_local_normal = source.matrix_world.to_3x3().transposed()
    for record in records:
        normal = Vector(record.local_normal) if record.local_normal is not None else (
            world_to_local_normal @ Vector(record.world_normal)
        )
        if normal.length_squared:
            normals.append(normal.normalized())
    if not normals:
        raise ValueError("所选法向依据没有可用的表面法向，请重新标记参考面")
    reference = normals[0].copy()
    aligned = []
    for normal in normals:
        aligned.append(-normal if normal.dot(reference) < 0.0 else normal)
    result = sum(aligned, Vector((0.0, 0.0, 0.0)))
    if not result.length_squared:
        raise ValueError("参考面的法向互相抵消，请只标记朝向一致的参考面")
    return result.normalized()


def _height_reference_from_records(source, excludes, height_mode):
    """Use red anchors as an explicit plane position without scanning geometry."""
    if height_mode != "RED_REFERENCE":
        return None
    points = []
    inverse = source.matrix_world.inverted_safe()
    for record in excludes:
        if record.hit_object_name != source.name:
            continue
        point = (
            Vector(record.local_location)
            if record.local_location is not None
            else inverse @ Vector(record.world_location)
        )
        points.append(point)
    if not points:
        raise ValueError("高度选择了红色参考面，但当前语义源上没有红色标记")
    return points


def _grow_marked_region(bm, source, targets, excludes, hard_angle_radians):
    """Use only explicitly brushed faces; never expand a display radius into geometry."""
    bm.faces.ensure_lookup_table()
    target_indices = _seed_face_indices(targets, len(bm.faces))
    if not target_indices:
        raise ValueError("绿色标记已无法解析到当前源网面的有效面")
    excluded = set(_seed_face_indices(
        [record for record in excludes if record.hit_object_name == source.name], len(bm.faces)
    ))
    target_indices = [index for index in target_indices if index not in excluded]
    if not target_indices:
        raise ValueError("绿色目标全部与红色保留面冲突")

    selected = set(target_indices)
    selected.difference_update(excluded)
    return selected, {
        "seed_faces": len(target_indices),
        "selected_faces": len(selected),
        "red_locked_faces": len(excluded),
        "selection_method": "exact_brushed_faces",
        "display_radius_used_for_growth": False,
        "global_geometry_scan": False,
    }


def _edge_dihedrals(edges):
    values = []
    for edge in edges:
        if len(edge.link_faces) != 2:
            continue
        try:
            values.append(float(edge.calc_face_angle(0.0)))
        except ValueError:
            continue
    return values


def _topology_signature(bm):
    boundary = {edge for edge in bm.edges if len(edge.link_faces) == 1}
    unseen = set(boundary)
    boundary_components = 0
    while unseen:
        boundary_components += 1
        stack = [unseen.pop()]
        while stack:
            edge = stack.pop()
            for vertex in edge.verts:
                for neighbor in vertex.link_edges:
                    if neighbor in unseen:
                        unseen.remove(neighbor)
                        stack.append(neighbor)
    invalid_edges = sum(1 for edge in bm.edges if len(edge.link_faces) == 0 or len(edge.link_faces) > 2)
    return {
        "boundary_components": boundary_components,
        "boundary_edges": len(boundary),
        "invalid_edges": invalid_edges,
    }


def _percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction)))]


def _point_segment_distance(point, first, second):
    direction = second - first
    denominator = direction.length_squared
    if denominator <= 1.0e-20:
        return (point - first).length
    parameter = max(0.0, min(1.0, (point - first).dot(direction) / denominator))
    return (point - (first + direction * parameter)).length


def _best_fit_plane(
    vertices, normal_hint=None, height_mode="MEDIAN", orientation_hint=None,
    height_reference_points=None,
):
    points = np.asarray([tuple(vertex.co) for vertex in vertices], dtype=float)
    center = np.median(points, axis=0)
    centered = points - center
    if normal_hint is None:
        covariance = centered.T @ centered / max(1, len(points))
        _values, vectors = np.linalg.eigh(covariance)
        normal = vectors[:, 0]
    else:
        normal = np.asarray(tuple(normal_hint), dtype=float)
    normal /= max(float(np.linalg.norm(normal)), 1.0e-12)
    if orientation_hint is not None and np.dot(normal, np.asarray(tuple(orientation_hint), dtype=float)) < 0.0:
        normal = -normal
    heights = points @ normal
    if height_mode == "RED_REFERENCE":
        if not height_reference_points:
            raise ValueError("红色参考高度缺少有效锚点")
        reference_heights = np.asarray([
            float(np.dot(np.asarray(tuple(point), dtype=float), normal))
            for point in height_reference_points
        ])
        plane_height = float(np.median(reference_heights))
    elif height_mode == "LOW":
        plane_height = float(np.min(heights))
    elif height_mode == "HIGH":
        plane_height = float(np.max(heights))
    else:
        plane_height = float(np.median(heights))
    center += normal * (plane_height - float(center @ normal))
    centered = points - center
    distances = centered @ normal
    return Vector(center), Vector(normal), distances


def _region_face_components(region_faces, locked_region_edges):
    """Split a marked region at its real boundary and protected feature edges."""
    region_set = set(region_faces)
    unseen = set(region_faces)
    components = []
    while unseen:
        seed = unseen.pop()
        component = {seed}
        stack = [seed]
        while stack:
            face = stack.pop()
            for edge in face.edges:
                # A hard edge is represented by a locked segment after local
                # subdivision.  Do not fit one plane across that crease.
                if edge in locked_region_edges:
                    continue
                for neighbor in edge.link_faces:
                    if neighbor in region_set and neighbor in unseen:
                        unseen.remove(neighbor)
                        component.add(neighbor)
                        stack.append(neighbor)
        components.append(component)
    return components


def _rebuild_working_mesh(
    source, selected_indices, excluded_indices, level, strength, hard_angle, mode="smooth",
    height_mode="MEDIAN", normal_hint=None, normal_mode="AUTO", height_reference_points=None,
):
    working = source.copy()
    working.data = source.data.copy()
    working.name = WORKING_PREFIX + source.name
    working.data.name = WORKING_PREFIX + source.data.name

    bm = bmesh.new()
    bm.from_mesh(working.data)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    # Creating a BMesh custom-data layer can relocate element storage.  Create
    # it before retaining any BMFace references, otherwise Blender may report
    # those references as removed even though no topology operation ran yet.
    region_layer = bm.faces.layers.int.get("smrn_rebuild_region") or bm.faces.layers.int.new(
        "smrn_rebuild_region"
    )
    bm.faces.ensure_lookup_table()
    selected = [bm.faces[index] for index in selected_indices]
    selected_set = set(selected)
    excluded = {bm.faces[index] for index in excluded_indices if index < len(bm.faces)}
    if not selected:
        bm.free()
        _remove_object(working)
        raise ValueError("局部重构区域为空")

    for face in bm.faces:
        face[region_layer] = 1 if face in selected_set else 0

    selected_edges = {edge for face in selected for edge in face.edges}
    boundary_edges = {
        edge for edge in selected_edges
        if any(face not in selected_set for face in edge.link_faces) or len(edge.link_faces) < 2
    }
    hard_edges = set()
    for edge in selected_edges:
        if len(edge.link_faces) != 2:
            hard_edges.add(edge)
            continue
        try:
            if edge.calc_face_angle(0.0) >= hard_angle:
                hard_edges.add(edge)
        except ValueError:
            hard_edges.add(edge)
    # Green faces are the complete editable scope.  Both modes hard-lock the
    # green outer boundary, every red face, and (for smoothing) hard features.
    # Never borrow unmarked neighbours as a transition band: if the marked
    # patch has no editable interior, fail closed and ask for a wider mark.
    protected_feature_edges = hard_edges if mode != "flatten" else set()
    excluded_edges = {edge for face in excluded for edge in face.edges}
    locked_edges = boundary_edges | protected_feature_edges | excluded_edges
    locked_initial_vertices = {vertex for edge in locked_edges for vertex in edge.verts}
    locked_segments = [(edge.verts[0].co.copy(), edge.verts[1].co.copy()) for edge in locked_edges]
    local_lengths = [edge.calc_length() for edge in selected_edges if edge.calc_length() > 1.0e-9]
    local_scale = _percentile(local_lengths, 0.5) if local_lengths else 1.0e-4
    before_inner_edges = {
        edge for edge in selected_edges
        if len(edge.link_faces) == 2
        and all(face in selected_set for face in edge.link_faces)
        and all(vertex not in locked_initial_vertices for vertex in edge.verts)
    }
    before_p95 = _percentile(_edge_dihedrals(before_inner_edges), 0.95)
    before_topology = _topology_signature(bm)

    cuts = (2 ** max(1, min(2, int(level)))) - 1
    bmesh.ops.subdivide_edges(
        bm,
        edges=list(selected_edges),
        cuts=cuts,
        use_grid_fill=True,
        use_smooth_even=True,
    )
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    region_faces = [face for face in bm.faces if int(face[region_layer]) == 1]
    if not region_faces:
        bm.free()
        _remove_object(working)
        raise RuntimeError("细分后未能保留局部区域标签")

    if mode == "flatten":
        # Work with explicit triangles while solving planarity.  A warped quad
        # has an ambiguous display normal and was the source of false-looking
        # folds in the old preview; BEAUTY chooses the shorter, safer diagonal.
        bmesh.ops.triangulate(
            bm,
            faces=region_faces,
            quad_method="BEAUTY",
            ngon_method="BEAUTY",
        )
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        region_faces = [face for face in bm.faces if int(face[region_layer]) == 1]

    region_vertices = {vertex for face in region_faces for vertex in face.verts}
    region_face_set = set(region_faces)
    lock_tolerance = max(1.0e-8, local_scale * 1.0e-6)
    locked_vertices = {
        vertex for vertex in region_vertices
        if any(_point_segment_distance(vertex.co, first, second) <= lock_tolerance
               for first, second in locked_segments)
    }
    # A non-manifold source can share a vertex without sharing a normal
    # two-face boundary edge.  Lock every green vertex touched by any
    # unmarked face so no unmarked polygon can move even in that topology.
    locked_vertices.update({
        vertex for vertex in region_vertices
        if any(face not in region_face_set for face in vertex.link_faces)
    })
    locked_region_edges = {
        edge for face in region_faces for edge in face.edges
        if any(
            _point_segment_distance(edge.verts[0].co, first, second) <= lock_tolerance
            and _point_segment_distance(edge.verts[1].co, first, second) <= lock_tolerance
            for first, second in locked_segments
        )
    }
    movable = list(region_vertices - locked_vertices)
    if mode == "flatten" and not movable:
        bm.free()
        _remove_object(working)
        raise ValueError("绿色区域没有内部可移动顶点；请把需要平整的绿色范围多刷一圈")
    before_coordinates = {vertex: vertex.co.copy() for vertex in movable}
    qa_faces = set(region_faces)
    before_face_geometry = {}
    ignored_preexisting_tiny_faces = 0
    transition_rings = []
    planarity = None
    flatten_projection_fraction = 1.0
    flatten_progress_passed = True
    flatten_safety_attempts = []
    if mode == "flatten" and movable:
        components = _region_face_components(region_faces, locked_region_edges)
        component_reports = []
        component_geometry = []
        before_squares = []
        after_squares = []
        moved_vertices = set()
        for component_index, component_faces in enumerate(components):
            component_vertices = {vertex for face in component_faces for vertex in face.verts}
            component_movable = (component_vertices - locked_vertices) - moved_vertices
            if not component_movable or len(component_vertices) < 3:
                continue
            orientation = Vector((0.0, 0.0, 0.0))
            for face in component_faces:
                orientation += face.normal
            plane_center, plane_normal, before_distances = _best_fit_plane(
                component_vertices,
                normal_hint=normal_hint,
                height_mode=height_mode,
                orientation_hint=orientation if orientation.length_squared else None,
                height_reference_points=height_reference_points,
            )
            editable_before_distances = np.asarray([
                float((vertex.co - plane_center).dot(plane_normal))
                for vertex in component_movable
            ])
            for vertex in component_movable:
                signed_distance = (vertex.co - plane_center).dot(plane_normal)
                vertex.co -= plane_normal * signed_distance
            moved_vertices.update(component_movable)
            editable_after_distances = np.asarray([
                float((vertex.co - plane_center).dot(plane_normal))
                for vertex in component_movable
            ])
            whole_after_distances = np.asarray([
                float((vertex.co - plane_center).dot(plane_normal)) for vertex in component_vertices
            ])
            before_squares.extend(float(value * value) for value in editable_before_distances)
            after_squares.extend(float(value * value) for value in editable_after_distances)
            component_reports.append({
                "index": component_index,
                "faces": len(component_faces),
                "vertices": len(component_vertices),
                "movable_vertices": len(component_movable),
                "before_rms": float(np.sqrt(np.mean(np.square(editable_before_distances)))),
                "after_rms": float(np.sqrt(np.mean(np.square(editable_after_distances)))),
                "whole_region_before_rms": float(np.sqrt(np.mean(np.square(before_distances)))),
                "whole_region_after_rms": float(np.sqrt(np.mean(np.square(whole_after_distances)))),
                "plane_center_local": list(plane_center),
                "plane_normal_local": list(plane_normal),
                "height_mode": height_mode,
                "normal_mode": normal_mode,
            })
            component_geometry.append((
                component_reports[-1], component_movable, component_vertices, plane_center, plane_normal
            ))
        before_rms = float(math.sqrt(sum(before_squares) / len(before_squares))) if before_squares else 0.0
        after_rms = float(math.sqrt(sum(after_squares) / len(after_squares))) if after_squares else 0.0
        planarity = {
            "method": "local_region_robust_center_pca_per_feature_component",
            "progress_metric_scope": "editable_green_interior_vertices",
            "component_count": len(components),
            "fitted_component_count": len(component_reports),
            "before_rms": before_rms,
            "after_rms": after_rms,
            "components": component_reports,
        }
        # Preserve a planar green core while the green outer boundary remains
        # fixed.  Only these green interior vertices may receive a target.
        core_movable = list(movable)
        core_before = dict(before_coordinates)
        full_targets = {vertex: vertex.co.copy() for vertex in core_movable}
        full_maximum = max(
            ((full_targets[vertex] - core_before[vertex]).length for vertex in core_movable),
            default=0.0,
        )
        for vertex in core_movable:
            vertex.co = core_before[vertex]
        bm.normal_update()
        movable = core_movable
        qa_faces = set(region_faces)
        minimum_qa_area = max(local_scale * local_scale * 1.0e-10, 1.0e-18)
        ignored_preexisting_tiny_faces = sum(
            1 for face in qa_faces if float(face.calc_area()) <= minimum_qa_area
        )
        before_face_geometry = {
            face: (face.normal.copy(), float(face.calc_area()))
            for face in qa_faces
            if float(face.calc_area()) > minimum_qa_area
        }
        # This is a rejection gate, not a clamp.  A plane that would move a
        # point several local triangles is almost certainly the wrong patch.
        max_allowed = local_scale * 2.5
        flatten_projection_fraction = min(
            1.0,
            max_allowed / full_maximum if full_maximum > 1.0e-20 else 1.0,
        )
        # Backtrack to the strongest geometrically safe projection.  This is
        # a deterministic orientation/area constraint, not a tuned brush
        # strength: the first fraction with no flipped or collapsed face wins.
        safe_fraction = 0.0
        for _attempt in range(12):
            for vertex in movable:
                vertex.co = before_coordinates[vertex].lerp(
                    full_targets[vertex], flatten_projection_fraction
                )
            bm.normal_update()
            collapsed = 0
            reversed_faces = 0
            collapsed_core_faces = 0
            reversed_core_faces = 0
            minimum_area_ratio = 1.0
            minimum_normal_dot = 1.0
            for face, (before_normal, before_area) in before_face_geometry.items():
                area_ratio = float(face.calc_area()) / before_area
                minimum_area_ratio = min(minimum_area_ratio, area_ratio)
                if area_ratio <= 0.05:
                    collapsed += 1
                    if face in region_faces:
                        collapsed_core_faces += 1
                if before_normal.length_squared and face.normal.length_squared:
                    normal_dot = float(before_normal.dot(face.normal))
                    minimum_normal_dot = min(minimum_normal_dot, normal_dot)
                    if normal_dot <= 0.0:
                        reversed_faces += 1
                        if face in region_faces:
                            reversed_core_faces += 1
            flatten_safety_attempts.append({
                "fraction": flatten_projection_fraction,
                "collapsed_faces": collapsed,
                "reversed_faces": reversed_faces,
                "collapsed_core_faces": collapsed_core_faces,
                "reversed_core_faces": reversed_core_faces,
                "minimum_area_ratio": minimum_area_ratio,
                "minimum_normal_dot": minimum_normal_dot,
            })
            invalid = collapsed > 0 or reversed_faces > 0
            if not invalid:
                safe_fraction = flatten_projection_fraction
                break
            flatten_projection_fraction *= 0.5
        flatten_projection_fraction = safe_fraction
        if not safe_fraction:
            for vertex in movable:
                vertex.co = before_coordinates[vertex]
        final_after_squares = []
        for (
            component_report,
            component_movable,
            component_vertices,
            plane_center,
            plane_normal,
        ) in component_geometry:
            final_distances = np.asarray([
                float((vertex.co - plane_center).dot(plane_normal)) for vertex in component_movable
            ])
            whole_final_distances = np.asarray([
                float((vertex.co - plane_center).dot(plane_normal)) for vertex in component_vertices
            ])
            final_after_squares.extend(float(value * value) for value in final_distances)
            component_report["after_rms"] = float(np.sqrt(np.mean(np.square(final_distances))))
            component_report["whole_region_after_rms"] = float(
                np.sqrt(np.mean(np.square(whole_final_distances)))
            )
        planarity["after_rms"] = (
            float(math.sqrt(sum(final_after_squares) / len(final_after_squares)))
            if final_after_squares else planarity["before_rms"]
        )
        planarity["projection_fraction"] = flatten_projection_fraction
        planarity["full_projection_max_displacement"] = full_maximum
        flatten_progress_passed = (
            flatten_projection_fraction >= 0.5
            and planarity["after_rms"] < planarity["before_rms"] * 0.25
        )
    elif strength > 0.0 and movable:
        qa_faces = {
            face
            for vertex in movable
            for face in vertex.link_faces
        } | set(region_faces)
        before_face_geometry = {
            face: (face.normal.copy(), max(float(face.calc_area()), 1.0e-20))
            for face in qa_faces
        }
        for _iteration in range(2):
            bmesh.ops.smooth_vert(
                bm,
                verts=movable,
                factor=max(0.0, min(0.5, float(strength))),
                use_axis_x=True,
                use_axis_y=True,
                use_axis_z=True,
            )
        max_allowed = local_scale * (0.04 + 0.24 * max(0.0, min(0.5, float(strength))))
        for vertex, original in before_coordinates.items():
            displacement = vertex.co - original
            if displacement.length > max_allowed:
                vertex.co = original + displacement.normalized() * max_allowed
    else:
        max_allowed = 0.0

    moved = [(vertex.co - before_coordinates[vertex]).length for vertex in movable]
    bm.normal_update()
    flipped_faces = 0
    degenerate_faces = 0
    for face, (before_normal, before_area) in before_face_geometry.items():
        after_area = float(face.calc_area())
        if after_area <= before_area * 0.05:
            degenerate_faces += 1
        if before_normal.length_squared and face.normal.length_squared and before_normal.dot(face.normal) <= 0.0:
            flipped_faces += 1
    region_set = set(region_faces)
    region_edges = {
        edge for face in region_faces for edge in face.edges
        if len(edge.link_faces) == 2 and all(linked in region_set for linked in edge.link_faces)
    }
    qa_region_edges = {
        edge for edge in region_edges
        if all(vertex not in locked_vertices for vertex in edge.verts)
    }
    after_p95 = _percentile(_edge_dihedrals(qa_region_edges), 0.95)
    dihedral_comparable = bool(before_inner_edges) and bool(qa_region_edges)
    after_topology = _topology_signature(bm)
    topology_passed = (
        after_topology["invalid_edges"] <= before_topology["invalid_edges"]
        and after_topology["boundary_components"] <= before_topology["boundary_components"]
        and (not dihedral_comparable or after_p95 <= before_p95 + math.radians(2.0))
    )
    if planarity is not None:
        topology_passed = (
            topology_passed
            and planarity["after_rms"] <= planarity["before_rms"] + 1.0e-9
            and (max(moved) if moved else 0.0) <= max_allowed
            and flatten_progress_passed
        )
    topology_passed = topology_passed and flipped_faces == 0 and degenerate_faces == 0

    preview_vertices = []
    preview_faces = []
    preview_map = {}
    preview_source_faces = set(region_faces)
    for face in preview_source_faces:
        indices = []
        for vertex in face.verts:
            index = preview_map.get(vertex)
            if index is None:
                index = len(preview_vertices)
                preview_map[vertex] = index
                preview_vertices.append(tuple(vertex.co))
            indices.append(index)
        preview_faces.append(tuple(indices))

    bm.to_mesh(working.data)
    working.data.update(calc_edges=True)
    bm.free()
    report = {
        "selected_faces_before": len(selected_indices),
        "region_faces_after": len(region_faces),
        "preview_affected_faces": len(preview_faces),
        "local_vertices_after": len(preview_vertices),
        "subdivision_level": int(level),
        "subdivision_cuts": cuts,
        "smoothing_strength": float(strength),
        "mode": mode,
        "planarity_qa": planarity,
        "local_edge_scale": local_scale,
        "max_allowed_displacement": max_allowed,
        "max_actual_displacement": max(moved) if moved else 0.0,
        "flatten_projection_fraction": flatten_projection_fraction if mode == "flatten" else None,
        "flatten_progress_passed": flatten_progress_passed if mode == "flatten" else None,
        "flatten_safety_attempts": flatten_safety_attempts if mode == "flatten" else None,
        "flipped_faces": flipped_faces,
        "degenerate_faces": degenerate_faces,
        "ignored_preexisting_tiny_faces": ignored_preexisting_tiny_faces,
        "locked_boundary_or_feature_vertices": len(locked_vertices),
        "strict_marked_scope": True,
        "unmarked_vertices_moved": 0,
        "transition_faces_checked": len(qa_faces - set(region_faces)),
        "transition_ring_count": len(transition_rings),
        "transition_vertices": sum(len(ring) for ring in transition_rings),
        "before_topology": before_topology,
        "after_topology": after_topology,
        "before_dihedral_p95_degrees": math.degrees(before_p95),
        "after_dihedral_p95_degrees": math.degrees(after_p95),
        "dihedral_qa_comparable": dihedral_comparable,
        "dihedral_edges_before": len(before_inner_edges),
        "dihedral_edges_after": len(qa_region_edges),
        "passed": topology_passed,
    }
    return working, preview_vertices, preview_faces, report


def _preview_object(scene, source, vertices, faces):
    _model, candidates, _helpers = ensure_scene_roots(scene)
    mesh = bpy.data.meshes.new(CANDIDATE_PREFIX + "MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(CANDIDATE_PREFIX + source.name, mesh)
    candidates.objects.link(obj)
    obj.matrix_world = source.matrix_world.copy()
    material = bpy.data.materials.get(PREVIEW_MATERIAL_NAME)
    if material is None:
        material = bpy.data.materials.new(PREVIEW_MATERIAL_NAME)
    material.diffuse_color = (1.0, 0.12, 0.015, 0.38)
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"
    if obj.data.materials.get(material.name) is None:
        obj.data.materials.append(material)
    obj.display_type = "SOLID"
    obj.show_in_front = True
    obj.show_wire = False
    obj.show_all_edges = False
    obj.color = (1.0, 0.28, 0.02, 1.0)
    obj["smrn_candidate_only"] = True
    return obj


def _link_hidden_working(scene, working):
    _model, candidates, _helpers = ensure_scene_roots(scene)
    candidates.objects.link(working)
    working.hide_viewport = True
    working.hide_render = True
    working.hide_set(True)


def remove_last_candidate(scene):
    preview_name = str(scene.get("smrn_surface_candidate_name", ""))
    working_name = str(scene.get("smrn_surface_working_name", ""))
    preview = bpy.data.objects.get(preview_name)
    working = bpy.data.objects.get(working_name)
    found = bool(
        (preview is not None and preview_name.startswith(CANDIDATE_PREFIX))
        or (working is not None and working_name.startswith(WORKING_PREFIX))
    )
    if preview is not None and preview_name.startswith(CANDIDATE_PREFIX):
        _remove_object(preview)
    if working is not None and working_name.startswith(WORKING_PREFIX):
        _remove_object(working)
    scene["smrn_surface_candidate_name"] = ""
    scene["smrn_surface_working_name"] = ""
    keep_model_visible(scene)
    return found


def _rounded_vector(value, precision=6):
    if value is None:
        return None
    return [round(float(item), precision) for item in value]


def _candidate_request_signature(scene, source_snapshot_value, targets, excludes, mode):
    """Identify the effective local rebuild request without scanning other objects."""
    records = []
    for record in sorted(
        targets + excludes,
        key=lambda item: (item.role, item.hit_object_name, item.face_index, item.id),
    ):
        records.append({
            "role": record.role,
            "hit_object_name": record.hit_object_name,
            "face_index": int(record.face_index),
            "local_location": _rounded_vector(record.local_location),
            "local_normal": _rounded_vector(record.local_normal),
            "world_location": _rounded_vector(record.world_location),
            "world_normal": _rounded_vector(record.world_normal),
            "semantic_radius": (
                round(float(record.semantic_radius), 6) if record.semantic_radius is not None else None
            ),
        })
    settings = {
        "subdivision_level": int(scene.smrn_surface_subdivision_level),
        "hard_angle_degrees": round(float(scene.smrn_surface_hard_angle), 6),
    }
    if mode == "smooth":
        settings["smooth_strength"] = round(float(scene.smrn_surface_smooth_strength), 6)
    else:
        settings.update({
            "height_mode": str(getattr(scene, "smrn_surface_height_mode", "MEDIAN")),
            "normal_mode": str(getattr(scene, "smrn_surface_normal_mode", "AUTO")),
        })
    payload = {
        "schema": 3,
        "source_fingerprint": str(source_snapshot_value.get("fingerprint", "")),
        "mode": mode,
        "scope_policy": "strict_green_faces_only_v2",
        "settings": settings,
        "marks": records,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _matching_existing_candidate(scene, source, source_snapshot_value, request_signature):
    preview_name = str(scene.get("smrn_surface_candidate_name", ""))
    working_name = str(scene.get("smrn_surface_working_name", ""))
    preview = bpy.data.objects.get(preview_name)
    working = bpy.data.objects.get(working_name)
    if (
        preview is None
        or working is None
        or not preview_name.startswith(CANDIDATE_PREFIX)
        or not working_name.startswith(WORKING_PREFIX)
    ):
        return None
    try:
        report = json.loads(str(preview.get(REPORT_KEY, "{}")))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if (
        report.get("status") != "candidate_ready"
        or not report.get("topology_qa", {}).get("passed")
        or report.get("request_signature") != request_signature
        or report.get("source", {}).get("fingerprint") != source_snapshot_value.get("fingerprint")
        or str(preview.get("smrn_source_name", "")) != source.name
        or str(working.get("smrn_source_name", "")) != source.name
    ):
        return None
    reused_report = dict(report)
    reused_report["reused_existing"] = True
    keep_model_visible(scene, (source, preview))
    return preview, reused_report


def build_scene_candidate(scene, mode="smooth"):
    if mode not in {"smooth", "flatten"}:
        raise ValueError("不支持的局部网面重构模式")
    source, targets, excludes, before_snapshot = _source_and_records(scene)
    request_signature = _candidate_request_signature(
        scene, before_snapshot, targets, excludes, mode
    )
    existing = _matching_existing_candidate(
        scene, source, before_snapshot, request_signature
    )
    if existing is not None:
        return existing
    height_mode = str(getattr(scene, "smrn_surface_height_mode", "MEDIAN"))
    normal_mode = str(getattr(scene, "smrn_surface_normal_mode", "AUTO"))
    normal_hint = _normal_hint_from_records(source, targets, excludes, normal_mode) if mode == "flatten" else None
    height_reference_points = (
        _height_reference_from_records(source, excludes, height_mode) if mode == "flatten" else None
    )
    hard_angle = math.radians(float(scene.smrn_surface_hard_angle))
    probe = bmesh.new()
    probe.from_mesh(source.data)
    selected_indices, growth = _grow_marked_region(probe, source, targets, excludes, hard_angle)
    excluded_indices = set(_seed_face_indices(
        [record for record in excludes if record.hit_object_name == source.name], len(probe.faces)
    ))
    probe.free()
    if not selected_indices:
        raise ValueError("没有可重构的局部网面；请检查绿色与红色标记是否冲突")

    working = preview = None
    try:
        working, vertices, faces, topology = _rebuild_working_mesh(
            source,
            sorted(selected_indices),
            sorted(excluded_indices),
            int(scene.smrn_surface_subdivision_level),
            float(scene.smrn_surface_smooth_strength),
            hard_angle,
            mode,
            height_mode,
            normal_hint,
            normal_mode,
            height_reference_points,
        )
        if not topology["passed"]:
            failures = []
            if topology.get("flipped_faces"):
                failures.append(f"{topology['flipped_faces']} 个面翻转")
            if topology.get("degenerate_faces"):
                failures.append(f"{topology['degenerate_faces']} 个面退化")
            if topology.get("max_actual_displacement", 0.0) > topology.get("max_allowed_displacement", 0.0):
                failures.append("拟合位移超过局部网格尺度")
            detail = "、".join(failures) or "非流形边或局部折角变差"
            raise ValueError(f"平整质量检查未通过（{detail}），已拒绝生成；源网格未修改")
        checkpoint = _checkpoint(scene, source)
        _link_hidden_working(scene, working)
        preview = _preview_object(scene, source, vertices, faces)
        after_source_snapshot = source_snapshot(source)
        source_unchanged = before_snapshot["fingerprint"] == after_source_snapshot["fingerprint"]
        report = {
            "status": "candidate_ready",
            "source": before_snapshot,
            "source_unchanged": source_unchanged,
            "checkpoint": checkpoint,
            "semantic_region": growth,
            "topology_qa": topology,
            "coverage_qa": {
                "passed": True,
                "method": "exact_brushed_faces_only",
                "source_objects_scanned": 1,
                "whole_vehicle_search": False,
            },
            "working_object": working.name,
            "preview_object": preview.name,
            "mode": mode,
            "request_signature": request_signature,
            "reused_existing": False,
            "flatten_reference": {
                "height_mode": height_mode,
                "normal_mode": normal_mode,
                "normal_hint_local": list(normal_hint) if normal_hint is not None else None,
            } if mode == "flatten" else None,
        }
        if not source_unchanged:
            raise RuntimeError("候选生成期间源网格发生变化，已中止")
        payload = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
        working[REPORT_KEY] = payload
        preview[REPORT_KEY] = payload
        working["smrn_source_name"] = source.name
        preview["smrn_source_name"] = source.name

        old_preview = bpy.data.objects.get(str(scene.get("smrn_surface_candidate_name", "")))
        old_working = bpy.data.objects.get(str(scene.get("smrn_surface_working_name", "")))
        scene["smrn_surface_candidate_name"] = preview.name
        scene["smrn_surface_working_name"] = working.name
        scene["smrn_surface_candidate_mode"] = mode
        scene["smrn_surface_last_report_json"] = payload
        for old in (old_preview, old_working):
            if old is not None and old not in {preview, working}:
                _remove_object(old)
        keep_model_visible(scene, (source, preview))
        return preview, report
    except Exception:
        if preview is not None:
            _remove_object(preview)
        if working is not None:
            _remove_object(working)
        old_preview = bpy.data.objects.get(str(scene.get("smrn_surface_candidate_name", "")))
        keep_model_visible(scene, (source, old_preview))
        raise


def _archive_collection(scene):
    model, candidates, _helpers = ensure_scene_roots(scene)
    collection = bpy.data.collections.get(ARCHIVE_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(ARCHIVE_COLLECTION_NAME)
    # A rollback checkpoint is not a second current model.  Keep it outside
    # the always-visible model root so visibility restoration cannot create a
    # full-vehicle overlap.  The explicit object flag below remains the second
    # guard for files created by older versions.
    if model.children.get(collection.name) is not None:
        model.children.unlink(collection)
    if candidates.children.get(collection.name) is None:
        candidates.children.link(collection)
    collection["smrn_collection_role"] = "recoverable_source_mesh_checkpoints"
    collection.hide_viewport = True
    collection.hide_render = True
    return collection


def confirm_replacement(scene):
    preview = bpy.data.objects.get(str(scene.get("smrn_surface_candidate_name", "")))
    working = bpy.data.objects.get(str(scene.get("smrn_surface_working_name", "")))
    if preview is None or working is None:
        raise ValueError("没有可确认的局部网面重构候选")
    try:
        report = json.loads(str(preview.get(REPORT_KEY, "{}")))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("当前候选缺少可靠的生成报告") from error
    if report.get("status") != "candidate_ready" or not report.get("topology_qa", {}).get("passed"):
        raise ValueError("当前候选尚未通过局部拓扑质量门槛")
    source = bpy.data.objects.get(str(preview.get("smrn_source_name", "")))
    if source is None or source.type != "MESH":
        raise ValueError("候选对应的源对象已经不存在")
    expected = report.get("source", {}).get("fingerprint", "")
    if source_snapshot(source)["fingerprint"] != expected:
        raise ValueError("源网格在候选生成后又发生了变化，请重新生成候选")

    old_mesh = source.data
    archive = source.copy()
    archive.data = old_mesh
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    archive.name = f"SMRN_SOURCE_ARCHIVE_{stamp}_{source.name}"
    archive["smrn_archive_only"] = True
    archive["smrn_checkpoint_path"] = report.get("checkpoint", "")
    collection = _archive_collection(scene)
    collection.objects.link(archive)
    archive.hide_viewport = True
    archive.hide_render = True
    archive.hide_set(True)

    new_mesh = working.data
    try:
        source.data = new_mesh
        source["smrn_last_surface_rebuild_report_json"] = json.dumps(
            {**report, "status": "accepted", "accepted_at": stamp},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        _remove_object(preview)
        bpy.data.objects.remove(working, do_unlink=True)
        scene["smrn_surface_candidate_name"] = ""
        scene["smrn_surface_working_name"] = ""
        set_active_source(scene, source_snapshot(source))
        keep_model_visible(scene, (source,))
        archive.hide_viewport = True
        archive.hide_render = True
        archive.hide_set(True)
        return source, archive, report
    except Exception:
        source.data = old_mesh
        _remove_object(archive)
        keep_model_visible(scene, (source,))
        raise
