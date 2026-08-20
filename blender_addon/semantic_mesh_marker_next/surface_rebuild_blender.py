"""Feature-locked local reconstruction of marked source mesh surfaces.

The visible candidate is only a wire preview of the affected region.  A full
working copy is kept recoverably beside it so confirmation can swap only the
source object's mesh datablock, preserving the source object identity and all
external references.
"""

from __future__ import annotations

from collections import deque
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


def _canvas_frame(region_vertices, region_faces, local_scale):
    """Derive a deterministic cloth frame and source wave from marked geometry."""
    points = np.asarray([tuple(vertex.co) for vertex in region_vertices], dtype=float)
    if len(points) < 6:
        raise ValueError("帆布波浪重建至少需要覆盖 6 个网格顶点")
    center = np.median(points, axis=0)
    centered = points - center
    covariance = np.cov(centered, rowvar=False)
    values, vectors = np.linalg.eigh(covariance)
    order = np.argsort(values)[::-1]
    axes = vectors[:, order]
    major = axes[:, 0]
    cross = axes[:, 1]
    normal = axes[:, 2]
    average_normal = np.zeros(3, dtype=float)
    for face in region_faces:
        average_normal += np.asarray(tuple(face.normal), dtype=float) * max(float(face.calc_area()), 1.0e-20)
    if float(np.dot(normal, average_normal)) < 0.0:
        normal = -normal
    coordinates = centered @ np.column_stack((major, cross, normal))
    spans = np.percentile(coordinates, 95.0, axis=0) - np.percentile(coordinates, 5.0, axis=0)
    if spans[1] < max(local_scale * 1.5, 1.0e-8):
        raise ValueError("绿色帆布区域过窄；请沿帆布宽度再多刷一些表面")

    # Remove a low-order drape trend before fitting periodic detail.  This
    # protects the source's large folds instead of misreading them as texture.
    u = coordinates[:, 0] / max(float(spans[0]), 1.0e-12)
    v = coordinates[:, 1] / max(float(spans[1]), 1.0e-12)
    height = coordinates[:, 2]
    trend = np.column_stack((np.ones(len(points)), u, v, u * u, v * v, u * v))
    trend_coefficients, *_ = np.linalg.lstsq(trend, height, rcond=None)
    residual = height - trend @ trend_coefficients
    residual_variance = float(np.mean(np.square(residual)))

    best = None
    for cycles in (1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5):
        phase_coordinate = 2.0 * math.pi * cycles * v
        basis = np.column_stack((
            np.sin(phase_coordinate), np.cos(phase_coordinate),
            np.sin(2.0 * phase_coordinate), np.cos(2.0 * phase_coordinate),
        ))
        coefficients, *_ = np.linalg.lstsq(basis, residual, rcond=None)
        fitted = basis @ coefficients
        explained = 1.0 - float(np.mean(np.square(residual - fitted))) / max(residual_variance, 1.0e-20)
        amplitude = float(math.hypot(coefficients[0], coefficients[1]))
        score = explained * min(1.0, amplitude / max(local_scale * 0.02, 1.0e-12))
        if best is None or score > best[0]:
            best = (score, cycles, coefficients, explained, amplitude)

    _score, cycles, coefficients, explained, fitted_amplitude = best
    cap = local_scale * 0.14
    if fitted_amplitude > local_scale * 0.01 and explained > 0.03:
        amplitude = min(cap, max(local_scale * 0.025, fitted_amplitude * 0.35))
        phase_source = "fitted_source_residual"
        phase = math.atan2(float(coefficients[1]), float(coefficients[0]))
        harmonic_ratio = min(0.28, math.hypot(float(coefficients[2]), float(coefficients[3])) / max(fitted_amplitude, 1.0e-12))
        harmonic_phase = math.atan2(float(coefficients[3]), float(coefficients[2]))
    else:
        amplitude = local_scale * 0.035
        phase_source = "deterministic_marked_roi_anchor"
        phase = 0.0
        harmonic_ratio = 0.18
        harmonic_phase = 0.0
    return {
        "center": Vector(center),
        "major": Vector(major),
        "cross": Vector(cross),
        "normal": Vector(normal),
        "major_span": float(spans[0]),
        "cross_span": float(spans[1]),
        "thickness_span": float(spans[2]),
        "cycles": float(cycles),
        "wavelength": float(spans[1] / cycles),
        "base_amplitude": float(amplitude),
        "phase": float(phase),
        "harmonic_ratio": float(harmonic_ratio),
        "harmonic_phase": float(harmonic_phase),
        "source_fit_explained_fraction": float(max(0.0, explained)),
        "phase_source": phase_source,
    }


def _canvas_boundary_fades(region_vertices, locked_vertices):
    """Topological fade keeps generated waves exactly off marked boundaries."""
    region_set = set(region_vertices)
    distance = {vertex: 0 for vertex in locked_vertices if vertex in region_set}
    frontier = deque(distance)
    while frontier:
        vertex = frontier.popleft()
        next_distance = distance[vertex] + 1
        for edge in vertex.link_edges:
            neighbor = edge.other_vert(vertex)
            if neighbor in region_set and neighbor not in distance:
                distance[neighbor] = next_distance
                frontier.append(neighbor)
    return {
        vertex: min(1.0, max(0.0, float(distance.get(vertex, 3)) / 3.0))
        for vertex in region_vertices
    }


def _canvas_macro_fold_edges(selected_edges, hard_angle, local_scale):
    """Protect only source-supported major folds, not coarse triangulation."""
    threshold = max(math.radians(70.0), float(hard_angle) + math.radians(25.0))
    minimum_length = max(local_scale * 0.35, 1.0e-10)
    folds = set()
    for edge in selected_edges:
        if len(edge.link_faces) != 2 or edge.calc_length() < minimum_length:
            continue
        try:
            if edge.calc_face_angle(0.0) >= threshold:
                folds.add(edge)
        except ValueError:
            continue
    return folds, threshold


def _canvas_subdivision_cuts(selected_face_count):
    """Choose enough density for waves while keeping the local job bounded."""
    count = max(1, int(selected_face_count))
    for cuts in (7, 3, 1):
        if count * ((cuts + 1) ** 2) <= 24000:
            return cuts
    return 1


def _canvas_facet_edge_samples(region_faces, source_facet_segments, tolerance):
    """Find subdivided descendants of unlocked coarse source facet edges."""
    if not source_facet_segments:
        return set()
    candidates = {
        edge for face in region_faces for edge in face.edges
        if len(edge.link_faces) == 2
    }
    matched = set()
    for edge in candidates:
        first, second = edge.verts
        for start, end in source_facet_segments:
            if (
                _point_segment_distance(first.co, start, end) <= tolerance
                and _point_segment_distance(second.co, start, end) <= tolerance
            ):
                matched.add(edge)
                break
    return matched


def _taubin_fair_canvas(
    bm, movable, region_faces, original_coordinates, local_scale, iterations=44,
):
    """Fair the dense cloth base without shrinking its locked silhouette."""
    movable_set = set(movable)
    reference_geometry = {
        face: (face.normal.copy(), max(float(face.calc_area()), 1.0e-20))
        for face in region_faces
    }
    maximum_base_displacement = local_scale * 0.42
    completed = 0
    rollback_count = 0

    def laplacian_targets():
        targets = {}
        for vertex in movable_set:
            neighbors = [edge.other_vert(vertex) for edge in vertex.link_edges]
            if not neighbors:
                continue
            average = sum((neighbor.co for neighbor in neighbors), Vector((0.0, 0.0, 0.0)))
            targets[vertex] = average / len(neighbors) - vertex.co
        return targets

    for _iteration in range(max(0, int(iterations))):
        before_iteration = {vertex: vertex.co.copy() for vertex in movable_set}
        for factor in (0.45, -0.46):
            offsets = laplacian_targets()
            for vertex, offset in offsets.items():
                vertex.co += offset * factor
            for vertex, original in original_coordinates.items():
                displacement = vertex.co - original
                if displacement.length > maximum_base_displacement:
                    vertex.co = original + displacement.normalized() * maximum_base_displacement
        bm.normal_update()
        unsafe = False
        for face, (before_normal, before_area) in reference_geometry.items():
            if float(face.calc_area()) <= before_area * 0.05:
                unsafe = True
                break
            if before_normal.length_squared and face.normal.length_squared:
                if before_normal.dot(face.normal) <= 0.0:
                    unsafe = True
                    break
        if unsafe:
            for vertex, coordinate in before_iteration.items():
                vertex.co = coordinate
            bm.normal_update()
            rollback_count += 1
            break
        completed += 1
    return {
        "method": "bounded_taubin_fairing_before_wave_v1",
        "requested_iterations": int(iterations),
        "completed_iterations": completed,
        "rollback_count": rollback_count,
        "lambda": 0.45,
        "mu": -0.46,
        "maximum_base_displacement": maximum_base_displacement,
    }


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
    local_lengths = [edge.calc_length() for edge in selected_edges if edge.calc_length() > 1.0e-9]
    local_scale = _percentile(local_lengths, 0.5) if local_lengths else 1.0e-4
    canvas_macro_folds = set()
    canvas_fold_threshold = None
    if mode == "canvas":
        canvas_macro_folds, canvas_fold_threshold = _canvas_macro_fold_edges(
            selected_edges, hard_angle, local_scale
        )
    # Green faces are the complete editable scope.  Both modes hard-lock the
    # green outer boundary, every red face, and (for smoothing) hard features.
    # Never borrow unmarked neighbours as a transition band: if the marked
    # patch has no editable interior, fail closed and ask for a wider mark.
    protected_feature_edges = (
        canvas_macro_folds if mode == "canvas"
        else (hard_edges if mode != "flatten" else set())
    )
    excluded_edges = {edge for face in excluded for edge in face.edges}
    locked_edges = boundary_edges | protected_feature_edges | excluded_edges
    locked_initial_vertices = {vertex for edge in locked_edges for vertex in edge.verts}
    locked_segments = [(edge.verts[0].co.copy(), edge.verts[1].co.copy()) for edge in locked_edges]
    canvas_facet_segments = [
        (edge.verts[0].co.copy(), edge.verts[1].co.copy())
        for edge in selected_edges
        if edge not in locked_edges
        and len(edge.link_faces) == 2
        and all(face in selected_set for face in edge.link_faces)
    ] if mode == "canvas" else []
    before_topology = _topology_signature(bm)

    cuts = (
        _canvas_subdivision_cuts(len(selected_indices))
        if mode == "canvas"
        else (2 ** max(1, min(2, int(level)))) - 1
    )
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
    canvas_facet_edges = _canvas_facet_edge_samples(
        region_faces,
        canvas_facet_segments,
        max(1.0e-8, local_scale * 1.0e-5),
    ) if mode == "canvas" else set()
    movable = list(region_vertices - locked_vertices)
    if mode == "flatten" and not movable:
        bm.free()
        _remove_object(working)
        raise ValueError("绿色区域没有内部可移动顶点；请把需要平整的绿色范围多刷一圈")
    if mode == "canvas" and not movable:
        bm.free()
        _remove_object(working)
        raise ValueError("帆布区域没有可重建的内部网面；请沿帆布长度和宽度多刷一圈")
    # Compare the exact same post-subdivision edges before and after fitting.
    # Comparing original coarse edges against new triangulation edges mixes
    # different populations and can falsely reject an otherwise safe result.
    region_set = set(region_faces)
    matched_dihedral_edges = {
        edge for face in region_faces for edge in face.edges
        if len(edge.link_faces) == 2
        and all(linked in region_set for linked in edge.link_faces)
        and all(vertex not in locked_vertices for vertex in edge.verts)
    }
    before_p95 = _percentile(_edge_dihedrals(matched_dihedral_edges), 0.95)
    before_coordinates = {vertex: vertex.co.copy() for vertex in movable}
    qa_faces = set(region_faces)
    before_face_geometry = {}
    ignored_preexisting_tiny_faces = 0
    transition_rings = []
    planarity = None
    flatten_projection_fraction = 1.0
    flatten_progress_passed = True
    flatten_safety_attempts = []
    smoothing_factor = 0.0
    smoothing_iterations = 0
    canvas_wave = None
    canvas_base_fairing = None
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
    elif mode == "canvas" and movable:
        bounded_strength = max(0.0, min(1.0, float(strength)))
        frame = _canvas_frame(region_vertices, region_faces, local_scale)
        fades = _canvas_boundary_fades(region_vertices, locked_vertices)
        qa_faces = {
            face
            for vertex in movable
            for face in vertex.link_faces
        } | set(region_faces)
        before_face_geometry = {
            face: (face.normal.copy(), max(float(face.calc_area()), 1.0e-20))
            for face in qa_faces
        }
        facet_before = _edge_dihedrals(canvas_facet_edges)
        canvas_base_fairing = _taubin_fair_canvas(
            bm, movable, region_faces, before_coordinates, local_scale, iterations=44,
        )
        smoothing_factor = canvas_base_fairing["lambda"]
        smoothing_iterations = canvas_base_fairing["completed_iterations"]
        bm.normal_update()
        facet_after_base = _edge_dihedrals(canvas_facet_edges)
        facet_before_p95 = _percentile(facet_before, 0.95)
        facet_after_p95 = _percentile(facet_after_base, 0.95)
        meaningful_faceting = facet_before_p95 >= math.radians(2.0)
        canvas_base_fairing.update({
            "facet_edges_sampled": len(canvas_facet_edges),
            "before_facet_dihedral_p95_degrees": math.degrees(facet_before_p95),
            "after_fairing_facet_dihedral_p95_degrees": math.degrees(facet_after_p95),
            "faceting_reduction_fraction": (
                1.0 - facet_after_p95 / facet_before_p95
                if facet_before_p95 > 1.0e-20 else 0.0
            ),
            "meaningful_source_faceting": meaningful_faceting,
            "passed": (
                not meaningful_faceting
                or (
                    facet_after_p95 <= facet_before_p95 * 0.65
                    and facet_after_p95 <= math.radians(18.0)
                )
            ),
        })
        wave_amplitude = frame["base_amplitude"] * bounded_strength
        maximum_wave = 0.0
        for vertex in movable:
            relative = vertex.co - frame["center"]
            v = float(relative.dot(frame["cross"])) / max(frame["cross_span"], 1.0e-12)
            theta = 2.0 * math.pi * frame["cycles"] * v
            wave = math.sin(theta + frame["phase"])
            wave += frame["harmonic_ratio"] * math.sin(2.0 * theta + frame["harmonic_phase"])
            displacement = wave_amplitude * fades.get(vertex, 0.0) * wave
            direction = vertex.normal.copy()
            if not direction.length_squared:
                direction = frame["normal"].copy()
            else:
                direction.normalize()
                if direction.dot(frame["normal"]) < 0.0:
                    direction.negate()
            vertex.co += direction * displacement
            maximum_wave = max(maximum_wave, abs(displacement))
        # Includes both gentle facet smoothing and generated wave displacement.
        max_allowed = local_scale * (0.44 + 0.10 * bounded_strength)
        for vertex, original in before_coordinates.items():
            displacement = vertex.co - original
            if displacement.length > max_allowed:
                vertex.co = original + displacement.normalized() * max_allowed
        canvas_wave = {
            "method": "fair_base_then_source_aligned_wave_v2",
            "semantic_class": "marked_draped_or_folded_canvas_surface",
            "coordinate_frame": {
                "center_local": list(frame["center"]),
                "major_axis_local": list(frame["major"]),
                "cross_axis_local": list(frame["cross"]),
                "surface_normal_local": list(frame["normal"]),
            },
            "major_span": frame["major_span"],
            "cross_span": frame["cross_span"],
            "thickness_span": frame["thickness_span"],
            "wavelength": frame["wavelength"],
            "cycles_across_cross_axis": frame["cycles"],
            "source_fit_explained_fraction": frame["source_fit_explained_fraction"],
            "phase_source": frame["phase_source"],
            "wave_strength": bounded_strength,
            "wave_amplitude": wave_amplitude,
            "wave_amplitude_cap": local_scale * 0.14,
            "maximum_generated_wave_displacement": maximum_wave,
            "boundary_fade_rings": 3,
            "random_displacement": False,
            "whole_vehicle_search": False,
            "source_objects_scanned": 1,
            "automatic_subdivision": True,
            "automatic_subdivision_cuts": cuts,
            "large_fold_threshold_degrees": math.degrees(canvas_fold_threshold),
            "protected_large_fold_edges": len(canvas_macro_folds),
            "base_surface_fairing": canvas_base_fairing,
            "large_fold_policy": "lock_only_major_folds_then_fair_coarse_facet_edges",
        }
    elif strength > 0.0 and movable:
        bounded_strength = max(0.0, min(1.0, float(strength)))
        # Keep 0.00-0.50 exactly compatible with the old two-pass control.
        # The new upper half adds bounded passes instead of raising the
        # per-pass factor, which is much less likely to fold thin triangles.
        smoothing_factor = min(0.5, bounded_strength)
        smoothing_iterations = 2 + int(math.ceil(max(0.0, bounded_strength - 0.5) * 8.0))
        qa_faces = {
            face
            for vertex in movable
            for face in vertex.link_faces
        } | set(region_faces)
        before_face_geometry = {
            face: (face.normal.copy(), max(float(face.calc_area()), 1.0e-20))
            for face in qa_faces
        }
        for _iteration in range(smoothing_iterations):
            bmesh.ops.smooth_vert(
                bm,
                verts=movable,
                factor=smoothing_factor,
                use_axis_x=True,
                use_axis_y=True,
                use_axis_z=True,
            )
        # At 0.50 this is the old 0.16 * local scale limit.  The stronger
        # range grows only to 0.24, so extra passes cannot run away.
        max_allowed = local_scale * (
            0.04
            + 0.24 * min(0.5, bounded_strength)
            + 0.16 * max(0.0, bounded_strength - 0.5)
        )
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
    after_p95 = _percentile(_edge_dihedrals(matched_dihedral_edges), 0.95)
    dihedral_comparable = bool(matched_dihedral_edges)
    after_topology = _topology_signature(bm)
    quality_gates = {
        "non_manifold_not_worse": (
            after_topology["invalid_edges"] <= before_topology["invalid_edges"]
        ),
        "boundary_components_not_worse": (
            after_topology["boundary_components"] <= before_topology["boundary_components"]
        ),
        "matched_dihedral_within_limit": (
            not dihedral_comparable
            or after_p95 <= before_p95 + math.radians(8.0 if mode == "canvas" else 2.0)
        ),
        "planarity_improved": True,
        "displacement_within_limit": True,
        "flatten_progress_sufficient": True,
        "no_flipped_faces": flipped_faces == 0,
        "no_degenerate_faces": degenerate_faces == 0,
    }
    if planarity is not None:
        quality_gates["planarity_improved"] = (
            planarity["after_rms"] <= planarity["before_rms"] + 1.0e-9
        )
        quality_gates["displacement_within_limit"] = (
            (max(moved) if moved else 0.0) <= max_allowed
        )
        quality_gates["flatten_progress_sufficient"] = flatten_progress_passed
    if canvas_wave is not None:
        quality_gates["canvas_source_proximity"] = (
            (max(moved) if moved else 0.0) <= max_allowed + 1.0e-12
        )
        canvas_wave["dense_source_proximity_qa"] = {
            "passed": quality_gates["canvas_source_proximity"],
            "sampled_vertices": len(movable),
            "maximum_source_displacement": max(moved) if moved else 0.0,
            "maximum_allowed_displacement": max_allowed,
            "scope": "strict_green_interior_only",
        }
        quality_gates["canvas_base_faceting_reduced"] = bool(
            canvas_base_fairing and canvas_base_fairing.get("passed")
        )
    topology_passed = all(quality_gates.values())

    if mode == "canvas":
        for face in region_faces:
            face.smooth = True

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
        "automatic_canvas_subdivision": mode == "canvas",
        "smoothing_strength": float(strength),
        "smoothing_factor": smoothing_factor,
        "smoothing_iterations": smoothing_iterations,
        "mode": mode,
        "planarity_qa": planarity,
        "canvas_wave_qa": canvas_wave,
        "canvas_base_fairing_qa": canvas_base_fairing,
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
        "dihedral_sample_matched": True,
        "dihedral_edges_before": len(matched_dihedral_edges),
        "dihedral_edges_after": len(matched_dihedral_edges),
        "quality_gates": quality_gates,
        "passed": topology_passed,
    }
    return working, preview_vertices, preview_faces, report


def _preview_object(scene, source, vertices, faces):
    _model, candidates, _helpers = ensure_scene_roots(scene)
    mesh = bpy.data.meshes.new(CANDIDATE_PREFIX + "MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
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
    # A reconstruction preview must obey normal viewport depth.  Drawing it
    # through foreground armor or equipment makes the candidate look larger
    # than its actual visible region and prevents a reliable visual review.
    obj.show_in_front = False
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
    elif mode == "canvas":
        settings["canvas_wave_strength"] = round(float(scene.smrn_canvas_wave_strength), 6)
    else:
        settings.update({
            "height_mode": str(getattr(scene, "smrn_surface_height_mode", "MEDIAN")),
            "normal_mode": str(getattr(scene, "smrn_surface_normal_mode", "AUTO")),
        })
    payload = {
        "schema": 7,
        "canvas_pipeline": "fair_base_then_source_aligned_wave_v2" if mode == "canvas" else None,
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
    # Normalize previews created by older add-on versions as soon as they are
    # reused; this is display-only and leaves both meshes untouched.
    preview.show_in_front = False
    keep_model_visible(scene, (source, preview))
    return preview, reused_report


def build_scene_candidate(scene, mode="smooth"):
    if mode not in {"smooth", "flatten", "canvas"}:
        raise ValueError("不支持的局部网面重构模式")
    source, targets, excludes, before_snapshot = _source_and_records(scene)
    if mode == "canvas" and len(targets) < 3:
        raise ValueError("帆布波浪重建至少需要 3 处绿色标记，并沿帆布表面分散刷选")
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
    if mode == "canvas" and len(selected_indices) < 6:
        raise ValueError("帆布绿色区域过小；请沿帆布长度和宽度多刷一些表面")

    working = preview = None
    try:
        strength = (
            float(scene.smrn_canvas_wave_strength)
            if mode == "canvas"
            else float(scene.smrn_surface_smooth_strength)
        )
        working, vertices, faces, topology = _rebuild_working_mesh(
            source,
            sorted(selected_indices),
            sorted(excluded_indices),
            int(scene.smrn_surface_subdivision_level),
            strength,
            hard_angle,
            mode,
            height_mode,
            normal_hint,
            normal_mode,
            height_reference_points,
        )
        if not topology["passed"]:
            failures = []
            gates = topology.get("quality_gates", {})
            before_topology = topology.get("before_topology", {})
            after_topology = topology.get("after_topology", {})
            if gates.get("non_manifold_not_worse") is False:
                failures.append(
                    "非流形边 "
                    f"{before_topology.get('invalid_edges', '?')}→"
                    f"{after_topology.get('invalid_edges', '?')}"
                )
            if gates.get("boundary_components_not_worse") is False:
                failures.append(
                    "边界连通块 "
                    f"{before_topology.get('boundary_components', '?')}→"
                    f"{after_topology.get('boundary_components', '?')}"
                )
            if gates.get("matched_dihedral_within_limit") is False:
                failures.append(
                    f"同批 {topology.get('dihedral_edges_before', 0)} 条边的折角 "
                    f"{topology.get('before_dihedral_p95_degrees', 0.0):.2f}°→"
                    f"{topology.get('after_dihedral_p95_degrees', 0.0):.2f}°"
                )
            if gates.get("canvas_base_faceting_reduced") is False:
                fairing = topology.get("canvas_base_fairing_qa") or {}
                failures.append(
                    "帆布低模棱面仍偏强 "
                    f"{fairing.get('before_facet_dihedral_p95_degrees', 0.0):.2f}°→"
                    f"{fairing.get('after_fairing_facet_dihedral_p95_degrees', 0.0):.2f}°"
                )
            if topology.get("flipped_faces"):
                failures.append(f"{topology['flipped_faces']} 个面翻转")
            if topology.get("degenerate_faces"):
                failures.append(f"{topology['degenerate_faces']} 个面退化")
            if topology.get("max_actual_displacement", 0.0) > topology.get("max_allowed_displacement", 0.0):
                failures.append("拟合位移超过局部网格尺度")
            if gates.get("planarity_improved") is False:
                failures.append("平面误差没有改善")
            if gates.get("flatten_progress_sufficient") is False:
                failures.append("安全回退后平整进度不足")
            detail = "、".join(failures) or "未识别的局部质量门失败"
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
                "method": (
                    "strict_green_surface_with_dense_source_proximity"
                    if mode == "canvas" else "exact_brushed_faces_only"
                ),
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
