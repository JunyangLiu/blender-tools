"""Blender adapter and non-destructive candidate builder for rotational patches."""

from __future__ import annotations

from datetime import datetime
from collections import defaultdict, deque
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector
import numpy as np

from .anchors import source_snapshot
from .constants import EXCLUDE_ROLE, SOURCE_NAME_KEY, TARGET_ROLE
from .rotational_fit import RotationalFit, fit_rotational_surface
from .scene_state import ensure_scene_roots, keep_model_visible
from .storage import load_all_marks


CANDIDATE_PREFIX = "SMRN_ROTATIONAL_CANDIDATE_"


def _world_normal(obj, local_normal):
    value = obj.matrix_world.to_3x3().inverted_safe().transposed() @ Vector(local_normal)
    return value.normalized() if value.length_squared else Vector((0.0, 0.0, 1.0))


def _current_anchor(record, obj):
    if record.local_location is not None and record.local_normal is not None:
        return obj.matrix_world @ Vector(record.local_location), _world_normal(obj, record.local_normal)
    return Vector(record.world_location), Vector(record.world_normal).normalized()


def _task_records(scene):
    records = load_all_marks(scene)
    targets = [item for item in records if item.role == TARGET_ROLE]
    excludes = [item for item in records if item.role == EXCLUDE_ROLE]
    return targets, excludes


def _source_for_targets(scene, targets):
    names = {item.source_object_name for item in targets}
    if len(names) != 1:
        raise ValueError("本轮目标标记必须全部来自同一个语义源")
    name = next(iter(names))
    source = bpy.data.objects.get(name) or bpy.data.objects.get(str(scene.get(SOURCE_NAME_KEY, "")))
    if source is None or source.type != "MESH":
        raise ValueError("找不到当前标记对应的源网格")
    fingerprints = {item.source_fingerprint for item in targets if item.source_fingerprint}
    current = source_snapshot(source)
    if fingerprints and current["fingerprint"] not in fingerprints:
        raise ValueError("源网格已在标记后发生变化，请重新标记后再分析")
    return source, current


def analyze_scene(scene):
    targets, excludes = _task_records(scene)
    if len(targets) < 4:
        fit = fit_rotational_surface(
            [item.world_location for item in targets],
            [item.world_normal for item in targets],
        )
        return fit, None, targets, excludes, {"source": None}
    source, snapshot = _source_for_targets(scene, targets)
    points, normals = [], []
    for record in targets:
        point, normal = _current_anchor(record, source)
        points.append(tuple(point))
        normals.append(tuple(normal))
    fit = fit_rotational_surface(points, normals)
    return fit, source, targets, excludes, {"source": snapshot}


def _face_components(source, face_indices):
    """Return connected components without looking beyond the selected faces."""
    selected = {int(index) for index in face_indices}
    edge_faces = defaultdict(list)
    for face_index in selected:
        for edge in source.data.polygons[face_index].edge_keys:
            edge_faces[tuple(sorted(edge))].append(face_index)
    neighbors = defaultdict(set)
    for linked in edge_faces.values():
        if len(linked) == 2:
            first, second = linked
            neighbors[first].add(second)
            neighbors[second].add(first)
    remaining = set(selected)
    components = []
    while remaining:
        seed = remaining.pop()
        component = {seed}
        queue = deque((seed,))
        while queue:
            current = queue.popleft()
            for other in neighbors[current] & remaining:
                remaining.remove(other)
                component.add(other)
                queue.append(other)
        components.append(component)
    return components


def analyze_selected_faces(source, face_indices):
    """Fit only the explicitly selected side faces of the current source."""
    if source is None or source.type != "MESH":
        raise ValueError("请在当前语义源的编辑模式中选中圆柱或圆锥侧面")
    indices = {int(index) for index in face_indices}
    if any(index < 0 or index >= len(source.data.polygons) for index in indices):
        raise ValueError("选中面索引已失效，请重新选择")
    if len(indices) < 4:
        raise ValueError("至少选择 4 个连续侧面；不要选择端盖、台阶或其他零件")
    components = _face_components(source, indices)
    if len(components) != 1:
        raise ValueError("选中面必须属于一个连续曲面；请分别处理不同零件")
    points = []
    normals = []
    for face_index in sorted(indices):
        polygon = source.data.polygons[face_index]
        points.append(tuple(source.matrix_world @ polygon.center))
        normals.append(tuple(_world_normal(source, polygon.normal)))
    fit = fit_rotational_surface(points, normals)
    return fit, {
        "source": source_snapshot(source),
        "selection_qa": {
            "selection_method": "exact_edit_mode_faces",
            "selected_faces": len(indices),
            "connected_components": len(components),
            "whole_vehicle_search": False,
            "passed": len(components) == 1,
        },
    }


def _fit_frame(fit):
    return (
        np.asarray(fit.axis_origin, dtype=float),
        np.asarray(fit.axis, dtype=float),
        np.asarray(fit.basis_x, dtype=float),
        np.asarray(fit.basis_y, dtype=float),
    )


def _coordinates(points, fit):
    origin, axis, basis_x, basis_y = _fit_frame(fit)
    relative = np.asarray(points, dtype=float) - origin
    axial = relative @ axis
    x = relative @ basis_x
    y = relative @ basis_y
    return axial, np.hypot(x, y), np.mod(np.arctan2(y, x), 2.0 * math.pi)


def _angle_offset(angle, start):
    return np.mod(angle - start, 2.0 * math.pi)


def _target_face_indices(source, targets):
    return {
        item.face_index for item in targets
        if 0 <= item.face_index < len(source.data.polygons)
    }


def _face_world_vertices(source, face_index):
    polygon = source.data.polygons[face_index]
    return [
        tuple(source.matrix_world @ source.data.vertices[index].co)
        for index in polygon.vertices
    ]


def _semantic_rotational_faces(fit, source, targets):
    """Expand seeds only across the same source-derived rotational surface."""
    seeds = _target_face_indices(source, targets)
    if not seeds:
        return seeds, {"seed_faces": 0, "surface_faces": 0, "expanded_faces": 0}

    seed_rows = []
    for face_index in seeds:
        axial, radius, _angle = _coordinates(_face_world_vertices(source, face_index), fit)
        predicted = np.abs(fit.signed_radius_at_origin + fit.signed_slope * axial)
        seed_rows.append((axial, radius - predicted))
    seed_spans = np.asarray([np.ptp(row[0]) for row in seed_rows], dtype=float)
    seed_residuals = np.concatenate([np.abs(row[1]) for row in seed_rows])
    typical_span = float(np.median(seed_spans))
    residual_tolerance = max(
        1.0e-5,
        float(np.quantile(seed_residuals, 0.90)) * 2.5,
        fit.point_residual_p90 * 1.5,
        fit.radius_at_axial(0.0) * 0.01,
    )
    minimum_span = max(1.0e-6, typical_span * 0.55)
    normal_tolerance = max(12.0, fit.normal_error_p90_degrees * 2.0)
    origin, axis, basis_x, basis_y = _fit_frame(fit)
    orientation = 1.0 if fit.signed_radius_at_origin >= 0.0 else -1.0
    normal_matrix = source.matrix_world.to_3x3().inverted_safe().transposed()

    def same_surface(face_index):
        polygon = source.data.polygons[face_index]
        points = _face_world_vertices(source, face_index)
        axial, radius, angle = _coordinates(points, fit)
        predicted = np.abs(fit.signed_radius_at_origin + fit.signed_slope * axial)
        if float(np.max(np.abs(radius - predicted))) > residual_tolerance:
            return False
        if float(np.ptp(axial)) < minimum_span:
            return False
        center_angle = float(np.angle(np.mean(np.exp(1j * angle))))
        radial = math.cos(center_angle) * basis_x + math.sin(center_angle) * basis_y
        expected = orientation * radial - fit.signed_slope * axis
        expected /= max(float(np.linalg.norm(expected)), 1.0e-10)
        normal = normal_matrix @ polygon.normal
        if normal.length_squared == 0.0:
            return False
        normal.normalize()
        error = math.degrees(math.acos(float(np.clip(np.dot(expected, tuple(normal)), -1.0, 1.0))))
        return error <= normal_tolerance

    edge_faces = defaultdict(list)
    for polygon in source.data.polygons:
        for edge in polygon.edge_keys:
            edge_faces[tuple(sorted(edge))].append(polygon.index)
    neighbors = defaultdict(set)
    for linked in edge_faces.values():
        for first in linked:
            neighbors[first].update(second for second in linked if second != first)

    accepted = set(seeds)
    queue = deque(seeds)
    while queue:
        current = queue.popleft()
        for other in neighbors[current]:
            if other in accepted or not same_surface(other):
                continue
            accepted.add(other)
            queue.append(other)
    return accepted, {
        "seed_faces": len(seeds),
        "surface_faces": len(accepted),
        "expanded_faces": len(accepted - seeds),
        "profile_residual_tolerance": residual_tolerance,
        "minimum_axial_span": minimum_span,
        "normal_tolerance_degrees": normal_tolerance,
    }


def _marked_face_vertices(source, targets, face_indices=None):
    result = []
    indices = _target_face_indices(source, targets) if face_indices is None else face_indices
    for face_index in indices:
        polygon = source.data.polygons[face_index]
        for index in polygon.vertices:
            result.append(tuple(source.matrix_world @ source.data.vertices[index].co))
    return result


def _expanded_domain(fit, source, targets, face_indices=None):
    points = _marked_face_vertices(source, targets, face_indices)
    if targets:
        points.extend(tuple(_current_anchor(item, source)[0]) for item in targets)
    axial, radius, angle = _coordinates(points, fit)
    axial_min, axial_max = float(np.min(axial)), float(np.max(axial))
    ordered = np.sort(np.mod(angle, 2.0 * math.pi))
    gaps = np.diff(np.r_[ordered, ordered[0] + 2.0 * math.pi])
    gap_index = int(np.argmax(gaps))
    nonzero_gaps = gaps[gaps > math.radians(0.05)]
    typical_gap = float(np.median(nonzero_gaps)) if len(nonzero_gaps) else float(gaps[gap_index])
    # A strictly profile-matched, shared-edge surface can contain a damaged
    # sector.  Once it supplies broad multi-face evidence, tolerate up to five
    # native facet steps and restore the closed circumference instead of
    # preserving the break as an artificial fan opening.
    semantic_evidence = (
        face_indices is not None
        and len(face_indices) >= max(12, 2 * len(_target_face_indices(source, targets)))
    )
    closure_factor = 5.0 if semantic_evidence else 2.8
    closure_limit = max(math.radians(12.0), closure_factor * typical_gap)
    source_ring_closed = len(nonzero_gaps) >= 6 and float(gaps[gap_index]) <= closure_limit
    if fit.coverage_mode == "full_rotation" or source_ring_closed:
        angle_start, angle_span = float(ordered[0]), 2.0 * math.pi
    else:
        angle_start = float(ordered[(gap_index + 1) % len(ordered)])
        angle_span = float(2.0 * math.pi - gaps[gap_index])
    predicted = np.abs(fit.signed_radius_at_origin + fit.signed_slope * axial)
    visible_residual = radius - predicted if fit.surface_side == "outer" else predicted - radius
    clearance = max(0.0, float(np.max(visible_residual)))
    return axial_min, axial_max, angle_start, angle_span, clearance, points


def _auto_thickness(fit, axial_min, axial_max):
    middle = 0.5 * (axial_min + axial_max)
    radius = fit.radius_at_axial(middle)
    axial_span = max(axial_max - axial_min, 1.0e-5)
    # Automatic mode is a surface-restoration preview, not a structural
    # thickening operation. Keep the visible fitted envelope exact and use
    # only a scale-derived thin backing shell. Explicit advanced thickness
    # remains available when a printable wall is intentionally requested.
    feature_scale = min(max(radius, 1.0e-5), axial_span)
    return max(1.0e-5, min(radius * 0.005, feature_scale * 0.01))


def _ring_point(fit, axial, angle, radius):
    origin, axis, basis_x, basis_y = _fit_frame(fit)
    return origin + axis * axial + radius * (math.cos(angle) * basis_x + math.sin(angle) * basis_y)


def _candidate_geometry(fit, axial_min, axial_max, angle_start, angle_span,
                        thickness, clearance, requested_segments):
    full = angle_span >= 2.0 * math.pi - 1.0e-7
    segments = max(12, int(round(requested_segments * angle_span / (2.0 * math.pi))))
    if full:
        segments = max(32, requested_segments)
        angles = [angle_start + angle_span * index / segments for index in range(segments)]
    else:
        angles = [angle_start + angle_span * index / segments for index in range(segments + 1)]
    rings = []
    vertices = []
    for axial in (axial_min, axial_max):
        base_radius = fit.radius_at_axial(axial)
        if fit.surface_side == "outer":
            radii = (base_radius + clearance, max(1.0e-5, base_radius - thickness))
        else:
            radii = (max(1.0e-5, base_radius - clearance), base_radius + thickness)
        for radius in radii:
            ring = []
            for angle in angles:
                ring.append(len(vertices))
                vertices.append(tuple(float(value) for value in _ring_point(fit, axial, angle, radius)))
            rings.append(ring)

    faces = []
    pair_count = len(angles) if full else len(angles) - 1
    def connect(first, second, reverse=False):
        for index in range(pair_count):
            following = (index + 1) % len(angles)
            face = (first[index], first[following], second[following], second[index])
            faces.append(tuple(reversed(face)) if reverse else face)
    # outer/visible, inner/backing, then both axial caps
    connect(rings[0], rings[2], reverse=(fit.surface_side == "inner"))
    connect(rings[1], rings[3], reverse=(fit.surface_side != "inner"))
    connect(rings[0], rings[1], reverse=True)
    connect(rings[2], rings[3], reverse=False)
    if not full:
        faces.append((rings[0][0], rings[2][0], rings[3][0], rings[1][0]))
        faces.append((rings[0][-1], rings[1][-1], rings[3][-1], rings[2][-1]))
    return vertices, faces, segments


def _topology_report(vertices, faces):
    counts = {}
    for face in faces:
        for index, first in enumerate(face):
            second = face[(index + 1) % len(face)]
            key = tuple(sorted((first, second)))
            counts[key] = counts.get(key, 0) + 1
    nonmanifold = sum(value != 2 for value in counts.values())
    finite = bool(np.all(np.isfinite(np.asarray(vertices, dtype=float))))
    return {"vertices": len(vertices), "faces": len(faces), "edges": len(counts),
            "nonmanifold_edges": nonmanifold, "finite": finite,
            "passed": finite and nonmanifold == 0}


def _dense_triangle_samples(source, targets, order=5, face_indices=None):
    result = []
    indices_to_sample = _target_face_indices(source, targets) if face_indices is None else face_indices
    for face_index in indices_to_sample:
        polygon = source.data.polygons[face_index]
        indices = list(polygon.vertices)
        if len(indices) < 3:
            continue
        anchor = source.matrix_world @ source.data.vertices[indices[0]].co
        for corner in range(1, len(indices) - 1):
            b = source.matrix_world @ source.data.vertices[indices[corner]].co
            c = source.matrix_world @ source.data.vertices[indices[corner + 1]].co
            for i in range(order + 1):
                for j in range(order + 1 - i):
                    u, v = i / order, j / order
                    result.append(tuple(anchor * (1.0 - u - v) + b * u + c * v))
    return result


def _coverage_report(fit, points, axial_min, axial_max, angle_start, angle_span, clearance):
    axial, radius, angle = _coordinates(points, fit)
    angular = _angle_offset(angle, angle_start)
    in_angle = np.ones(len(points), dtype=bool) if fit.coverage_mode == "full_rotation" else angular <= angle_span + 1e-7
    in_axial = (axial >= axial_min - 1e-7) & (axial <= axial_max + 1e-7)
    predicted = np.abs(fit.signed_radius_at_origin + fit.signed_slope * axial)
    if fit.surface_side == "outer":
        overshoot = radius - (predicted + clearance)
    else:
        overshoot = (predicted - clearance) - radius
    covered = in_angle & in_axial & (overshoot <= 1e-6)
    return {"samples": len(points), "uncovered": int(np.sum(~covered)),
            "maximum_overshoot": float(max(0.0, np.max(overshoot))) if len(points) else 0.0,
            "passed": bool(np.all(covered))}


def _required_clearance(fit, points):
    if not points:
        return 0.0
    axial, radius, _angle = _coordinates(points, fit)
    predicted = np.abs(fit.signed_radius_at_origin + fit.signed_slope * axial)
    residual = radius - predicted if fit.surface_side == "outer" else predicted - radius
    return max(0.0, float(np.max(residual)))


def _exclude_report(fit, source, excludes, axial_min, axial_max, angle_start, angle_span,
                    clearance, thickness):
    relevant = [item for item in excludes if item.source_object_name == source.name]
    if not relevant:
        return {"samples": 0, "conflicts": 0, "passed": True}
    points = [tuple(_current_anchor(item, source)[0]) for item in relevant]
    axial, radius, angle = _coordinates(points, fit)
    angular = _angle_offset(angle, angle_start)
    in_angle = np.ones(len(points), dtype=bool) if fit.coverage_mode == "full_rotation" else angular <= angle_span + 1e-7
    in_axial = (axial >= axial_min) & (axial <= axial_max)
    predicted = np.abs(fit.signed_radius_at_origin + fit.signed_slope * axial)
    if fit.surface_side == "outer":
        radial_hit = (radius >= predicted - thickness) & (radius <= predicted + clearance)
    else:
        radial_hit = (radius >= predicted - clearance) & (radius <= predicted + thickness)
    conflicts = int(np.sum(in_angle & in_axial & radial_hit))
    return {"samples": len(points), "conflicts": conflicts, "passed": conflicts == 0}


def _checkpoint(scene, source):
    existing = str(scene.get("smrn_rotational_checkpoint_path", ""))
    if existing and Path(existing).exists():
        return existing
    current = Path(bpy.data.filepath) if bpy.data.filepath else None
    if current is None:
        raise ValueError("当前 .blend 尚未保存，无法建立可靠源检查点")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = current.with_name(f"{current.stem}_before_smrn_rotational_{stamp}{current.suffix}")
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
    scene["smrn_rotational_checkpoint_path"] = str(path)
    source["smrn_rotational_checkpoint_fingerprint"] = source_snapshot(source)["fingerprint"]
    return str(path)


def remove_last_candidate(scene):
    name = str(scene.get("smrn_rotational_candidate_name", ""))
    obj = bpy.data.objects.get(name)
    if obj is None or not name.startswith(CANDIDATE_PREFIX):
        if name.startswith(CANDIDATE_PREFIX):
            scene["smrn_rotational_candidate_name"] = ""
        return False
    source = bpy.data.objects.get(str(obj.get("smrn_source_name", "")))
    _remove_candidate_object(obj)
    scene["smrn_rotational_candidate_name"] = ""
    keep_model_visible(scene, (source,))
    return True


def _remove_candidate_object(obj):
    mesh = obj.data if obj is not None and obj.type == "MESH" else None
    if obj is not None:
        bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _commit_candidate(scene, obj):
    """Finalize a new candidate before discarding the previous working one."""
    key = "smrn_rotational_candidate_name"
    old_name = str(scene.get(key, ""))
    old_obj = bpy.data.objects.get(old_name)
    source = bpy.data.objects.get(str(obj.get("smrn_source_name", "")))
    try:
        keep_model_visible(scene, (source,))
    except Exception:
        _remove_candidate_object(obj)
        scene[key] = old_name if old_obj is not None else ""
        raise
    if old_obj is not None and old_obj != obj and old_name.startswith(CANDIDATE_PREFIX):
        _remove_candidate_object(old_obj)
    scene[key] = obj.name


def _build_candidate(scene, fit, source, targets, excludes, context_report,
                     surface_faces, expansion, input_mode):
    report = {"fit": fit.to_dict(), "input_mode": input_mode, **context_report}
    if fit.status != "candidate_ready" or source is None:
        report["status"] = "rejected"
        report["reason"] = fit.reason
        return None, report
    axial_min, axial_max, angle_start, angle_span, fitted_clearance, _points = _expanded_domain(
        fit, source, targets, surface_faces
    )
    dense = _dense_triangle_samples(source, targets, face_indices=surface_faces)
    clearance = max(fitted_clearance, _required_clearance(fit, dense))
    clearance += max(0.0, float(scene.smrn_rotational_clearance))
    thickness = float(scene.smrn_rotational_thickness)
    if thickness <= 0.0:
        thickness = _auto_thickness(fit, axial_min, axial_max)
    coverage = _coverage_report(
        fit, dense, axial_min, axial_max, angle_start, angle_span, clearance
    )
    excludes_report = _exclude_report(
        fit, source, excludes, axial_min, axial_max, angle_start, angle_span,
        clearance, thickness
    )
    vertices, faces, segments = _candidate_geometry(
        fit, axial_min, axial_max, angle_start, angle_span,
        thickness, clearance, int(scene.smrn_rotational_segments),
    )
    topology = _topology_report(vertices, faces)
    report.update({
        "status": "candidate_ready",
        "semantic_expansion": expansion,
        "domain": {"axial_min": axial_min, "axial_max": axial_max,
                   "angular_start_degrees": math.degrees(angle_start),
                   "angular_span_degrees": math.degrees(angle_span),
                   "coverage_mode": ("full_rotation" if angle_span >= 2.0 * math.pi - 1.0e-7
                                     else "partial_arc"),
                   "clearance": clearance, "thickness": thickness,
                   "segments": segments},
        "coverage_qa": {
            **coverage,
            "scope": ("exact_selected_faces_only" if input_mode == "selected_faces"
                      else "semantic_mark_surface"),
            "whole_vehicle_search": False,
        }, "exclude_qa": excludes_report,
        "topology_qa": topology,
    })
    if not (coverage["passed"] and excludes_report["passed"] and topology["passed"]):
        report["status"] = "rejected"
        report["reason"] = "候选未通过覆盖、排除或拓扑质量门槛"
        return None, report

    checkpoint = _checkpoint(scene, source)
    report["checkpoint"] = checkpoint
    _model, candidates, _helpers = ensure_scene_roots(scene)
    mesh = bpy.data.meshes.new(f"{CANDIDATE_PREFIX}MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(f"{CANDIDATE_PREFIX}{fit.profile_kind.upper()}", mesh)
    candidates.objects.link(obj)
    obj.display_type = "SOLID"
    obj.color = (0.04, 0.55, 1.0, 0.72)
    obj.show_wire = True
    obj.show_all_edges = True
    obj["smrn_candidate_only"] = True
    obj["smrn_source_name"] = source.name
    obj["smrn_input_mode"] = input_mode
    report["source_unchanged"] = (
        source_snapshot(source)["fingerprint"] == context_report["source"]["fingerprint"]
    )
    if not report["source_unchanged"]:
        _remove_candidate_object(obj)
        report["status"] = "rejected"
        report["reason"] = "源网格在生成候选期间发生变化"
        return None, report
    obj["smrn_rotational_report_json"] = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    _commit_candidate(scene, obj)
    scene["smrn_rotational_last_report_json"] = obj["smrn_rotational_report_json"]
    return obj, report


def build_scene_candidate(scene):
    """Compatibility path: expand green marks across the matching surface."""
    fit, source, targets, excludes, context_report = analyze_scene(scene)
    if fit.status != "candidate_ready" or source is None:
        return _build_candidate(
            scene, fit, source, targets, excludes, context_report, set(), {}, "semantic_marks"
        )
    surface_faces, expansion = _semantic_rotational_faces(fit, source, targets)
    return _build_candidate(
        scene, fit, source, targets, excludes, context_report,
        surface_faces, expansion, "semantic_marks",
    )


def build_selected_scene_candidate(scene, source, face_indices):
    """Rebuild exactly one selected rotational patch; never scan or grow over the vehicle."""
    selected = {int(index) for index in face_indices}
    fit, context_report = analyze_selected_faces(source, selected)
    expansion = {
        "selection_method": "exact_edit_mode_faces",
        "seed_faces": len(selected),
        "surface_faces": len(selected),
        "expanded_faces": 0,
        "whole_vehicle_search": False,
    }
    return _build_candidate(
        scene, fit, source, (), (), context_report,
        selected, expansion, "selected_faces",
    )


def store_analysis(scene, report):
    scene["smrn_rotational_last_report_json"] = json.dumps(
        report, ensure_ascii=False, separators=(",", ":")
    )
