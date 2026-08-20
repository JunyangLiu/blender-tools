"""Feature-locked local reconstruction of marked source mesh surfaces.

The visible candidate is only a wire preview of the affected region.  A full
working copy is kept recoverably beside it so confirmation can swap only the
source object's mesh datablock, preserving the source object identity and all
external references.
"""

from __future__ import annotations

from datetime import datetime
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


def _grow_marked_region(bm, source, targets, excludes, hard_angle_radians):
    """Bounded local adjacency growth; never searches other objects or the car."""
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

    record_by_face = {int(record.face_index): record for record in targets}
    scale = _object_scale(source)
    selected = set()
    capped = False
    for seed_index in target_indices:
        seed = bm.faces[seed_index]
        edge_lengths = [edge.calc_length() for edge in seed.edges if edge.calc_length() > 1.0e-9]
        local_edge = sorted(edge_lengths)[len(edge_lengths) // 2] if edge_lengths else 1.0e-4
        marker_radius = float(record_by_face[seed_index].semantic_radius or 0.0) / scale
        radius = max(marker_radius, local_edge * 1.35)
        origin = _face_center(seed)
        queue = [seed]
        visited = {seed.index}
        accepted_for_seed = 0
        while queue:
            face = queue.pop(0)
            if face.index in excluded:
                continue
            if (_face_center(face) - origin).length > radius:
                continue
            selected.add(face.index)
            accepted_for_seed += 1
            if accepted_for_seed >= 384:
                capped = True
                break
            for edge in face.edges:
                if len(edge.link_faces) == 2:
                    try:
                        if edge.calc_face_angle(0.0) > hard_angle_radians:
                            continue
                    except ValueError:
                        continue
                for neighbor in edge.link_faces:
                    if neighbor.index not in visited:
                        visited.add(neighbor.index)
                        queue.append(neighbor)
    selected.difference_update(excluded)
    return selected, {
        "seed_faces": len(target_indices),
        "selected_faces": len(selected),
        "red_locked_faces": len(excluded),
        "per_seed_face_cap": 384,
        "growth_capped": capped,
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


def _best_fit_plane(vertices):
    points = np.asarray([tuple(vertex.co) for vertex in vertices], dtype=float)
    center = np.median(points, axis=0)
    centered = points - center
    covariance = centered.T @ centered / max(1, len(points))
    _values, vectors = np.linalg.eigh(covariance)
    normal = vectors[:, 0]
    normal /= max(float(np.linalg.norm(normal)), 1.0e-12)
    distances = centered @ normal
    return Vector(center), Vector(normal), distances


def _rebuild_working_mesh(
    source, selected_indices, excluded_indices, level, strength, hard_angle, mode="smooth"
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
    locked_edges = boundary_edges | hard_edges | {edge for face in excluded for edge in face.edges}
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

    region_vertices = {vertex for face in region_faces for vertex in face.verts}
    lock_tolerance = max(1.0e-8, local_scale * 1.0e-6)
    locked_vertices = {
        vertex for vertex in region_vertices
        if any(_point_segment_distance(vertex.co, first, second) <= lock_tolerance
               for first, second in locked_segments)
    }
    movable = list(region_vertices - locked_vertices)
    before_coordinates = {vertex: vertex.co.copy() for vertex in movable}
    planarity = None
    if mode == "flatten" and movable:
        plane_center, plane_normal, before_distances = _best_fit_plane(region_vertices)
        for vertex in movable:
            signed_distance = (vertex.co - plane_center).dot(plane_normal)
            vertex.co -= plane_normal * signed_distance
        _center, _normal, after_distances = _best_fit_plane(region_vertices)
        planarity = {
            "method": "local_region_robust_center_pca",
            "before_rms": float(np.sqrt(np.mean(np.square(before_distances)))),
            "after_rms": float(np.sqrt(np.mean(np.square(after_distances)))),
            "plane_center_local": list(plane_center),
            "plane_normal_local": list(plane_normal),
        }
        max_allowed = max(
            ((vertex.co - before_coordinates[vertex]).length for vertex in movable),
            default=0.0,
        )
    elif strength > 0.0 and movable:
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
        topology_passed = topology_passed and planarity["after_rms"] <= planarity["before_rms"] + 1.0e-9

    preview_vertices = []
    preview_faces = []
    preview_map = {}
    for face in region_faces:
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
        "region_faces_after": len(preview_faces),
        "local_vertices_after": len(preview_vertices),
        "subdivision_level": int(level),
        "subdivision_cuts": cuts,
        "smoothing_strength": float(strength),
        "mode": mode,
        "planarity_qa": planarity,
        "local_edge_scale": local_scale,
        "max_allowed_displacement": max_allowed,
        "max_actual_displacement": max(moved) if moved else 0.0,
        "locked_boundary_or_feature_vertices": len(locked_vertices),
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
    obj.display_type = "WIRE"
    obj.show_in_front = True
    obj.show_wire = True
    obj.show_all_edges = True
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


def build_scene_candidate(scene, mode="smooth"):
    if mode not in {"smooth", "flatten"}:
        raise ValueError("不支持的局部网面重构模式")
    source, targets, excludes, before_snapshot = _source_and_records(scene)
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
        )
        if not topology["passed"]:
            raise ValueError("候选使非流形边或高百分位折角变差，已拒绝生成")
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
                "method": "exact_mark_anchors_plus_bounded_local_adjacency",
                "source_objects_scanned": 1,
                "whole_vehicle_search": False,
            },
            "working_object": working.name,
            "preview_object": preview.name,
            "mode": mode,
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
        keep_model_visible(scene, (source,))
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
