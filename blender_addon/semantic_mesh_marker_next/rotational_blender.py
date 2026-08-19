"""Blender adapter and non-destructive candidate builder for rotational patches."""

from __future__ import annotations

from datetime import datetime
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


def _marked_face_vertices(source, targets):
    result = []
    seen = set()
    for record in targets:
        if record.face_index in seen or not 0 <= record.face_index < len(source.data.polygons):
            continue
        seen.add(record.face_index)
        polygon = source.data.polygons[record.face_index]
        for index in polygon.vertices:
            result.append(tuple(source.matrix_world @ source.data.vertices[index].co))
    return result


def _expanded_domain(fit, source, targets):
    points = _marked_face_vertices(source, targets)
    points.extend(tuple(_current_anchor(item, source)[0]) for item in targets)
    axial, radius, angle = _coordinates(points, fit)
    axial_min, axial_max = float(np.min(axial)), float(np.max(axial))
    if fit.coverage_mode == "full_rotation":
        angle_start, angle_span = fit.angular_start, 2.0 * math.pi
    else:
        ordered = np.sort(np.mod(angle, 2.0 * math.pi))
        gaps = np.diff(np.r_[ordered, ordered[0] + 2.0 * math.pi])
        gap_index = int(np.argmax(gaps))
        angle_start = float(ordered[(gap_index + 1) % len(ordered)])
        angle_span = float(2.0 * math.pi - gaps[gap_index])
    predicted = np.abs(fit.signed_radius_at_origin + fit.signed_slope * axial)
    visible_residual = radius - predicted if fit.surface_side == "outer" else predicted - radius
    clearance = max(0.0, float(np.max(visible_residual)))
    return axial_min, axial_max, angle_start, angle_span, clearance, points


def _auto_thickness(fit, axial_min, axial_max):
    middle = 0.5 * (axial_min + axial_max)
    radius = fit.radius_at_axial(middle)
    return max(0.02, min(radius * 0.08, max(axial_max - axial_min, 0.02) * 0.35))


def _ring_point(fit, axial, angle, radius):
    origin, axis, basis_x, basis_y = _fit_frame(fit)
    return origin + axis * axial + radius * (math.cos(angle) * basis_x + math.sin(angle) * basis_y)


def _candidate_geometry(fit, axial_min, axial_max, angle_start, angle_span,
                        thickness, clearance, requested_segments):
    full = fit.coverage_mode == "full_rotation"
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


def _dense_triangle_samples(source, targets, order=5):
    result = []
    seen = set()
    for record in targets:
        if record.face_index in seen or not 0 <= record.face_index < len(source.data.polygons):
            continue
        seen.add(record.face_index)
        polygon = source.data.polygons[record.face_index]
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
        return False
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    scene["smrn_rotational_candidate_name"] = ""
    keep_model_visible(scene)
    return True


def build_scene_candidate(scene):
    fit, source, targets, excludes, context_report = analyze_scene(scene)
    report = {"fit": fit.to_dict(), **context_report}
    if fit.status != "candidate_ready" or source is None:
        report["status"] = "rejected"
        report["reason"] = fit.reason
        return None, report
    axial_min, axial_max, angle_start, angle_span, fitted_clearance, _points = _expanded_domain(
        fit, source, targets
    )
    dense = _dense_triangle_samples(source, targets)
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
        "domain": {"axial_min": axial_min, "axial_max": axial_max,
                   "angular_start_degrees": math.degrees(angle_start),
                   "angular_span_degrees": math.degrees(angle_span),
                   "clearance": clearance, "thickness": thickness,
                   "segments": segments},
        "coverage_qa": coverage, "exclude_qa": excludes_report,
        "topology_qa": topology,
    })
    if not (coverage["passed"] and excludes_report["passed"] and topology["passed"]):
        report["status"] = "rejected"
        report["reason"] = "候选未通过覆盖、排除或拓扑质量门槛"
        return None, report

    checkpoint = _checkpoint(scene, source)
    report["checkpoint"] = checkpoint
    remove_last_candidate(scene)
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
    obj["smrn_rotational_report_json"] = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    scene["smrn_rotational_candidate_name"] = obj.name
    scene["smrn_rotational_last_report_json"] = obj["smrn_rotational_report_json"]
    keep_model_visible(scene)
    return obj, report


def store_analysis(scene, report):
    scene["smrn_rotational_last_report_json"] = json.dumps(
        report, ensure_ascii=False, separators=(",", ":")
    )
