"""Blender adapter and non-destructive builder for grab-handle candidates."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import bpy
from mathutils import Vector
import numpy as np

from .anchors import source_snapshot
from .constants import EXCLUDE_ROLE, SOURCE_NAME_KEY, TARGET_ROLE
from .handle_fit import fit_handle, path_points_2d, path_points_world
from .scene_state import ensure_scene_roots, keep_model_visible
from .storage import load_all_marks


CANDIDATE_PREFIX = "SMRN_HANDLE_CANDIDATE_"


def _world_normal(obj, local_normal):
    value = obj.matrix_world.to_3x3().inverted_safe().transposed() @ Vector(local_normal)
    return value.normalized() if value.length_squared else Vector((0.0, 0.0, 1.0))


def _current_anchor(record, obj):
    if record.local_location is not None and record.local_normal is not None:
        return obj.matrix_world @ Vector(record.local_location), _world_normal(obj, record.local_normal)
    return Vector(record.world_location), Vector(record.world_normal).normalized()


def _records(scene):
    records = load_all_marks(scene)
    return (
        [item for item in records if item.role == TARGET_ROLE],
        [item for item in records if item.role == EXCLUDE_ROLE],
    )


def _source_for_targets(scene, targets):
    names = {item.source_object_name for item in targets}
    if len(names) != 1:
        raise ValueError("本轮扶手目标标记必须全部来自同一个语义源")
    source = bpy.data.objects.get(next(iter(names))) or bpy.data.objects.get(
        str(scene.get(SOURCE_NAME_KEY, ""))
    )
    if source is None or source.type != "MESH":
        raise ValueError("找不到扶手标记对应的源网格")
    snapshot = source_snapshot(source)
    fingerprints = {item.source_fingerprint for item in targets if item.source_fingerprint}
    if fingerprints and snapshot["fingerprint"] not in fingerprints:
        raise ValueError("源网格已在标记后变化，请重新标记扶手")
    return source, snapshot


def _marked_edge_radius(source, targets):
    lengths = []
    seen = set()
    for record in targets:
        face_index = int(record.face_index)
        if face_index in seen or not 0 <= face_index < len(source.data.polygons):
            continue
        seen.add(face_index)
        polygon = source.data.polygons[face_index]
        for first, second in polygon.edge_keys:
            a = source.matrix_world @ source.data.vertices[first].co
            b = source.matrix_world @ source.data.vertices[second].co
            length = (a - b).length
            if length > 1.0e-8:
                lengths.append(length)
    return max(1.0e-4, float(np.quantile(lengths, 0.35)) * 0.5) if lengths else 1.0e-4


def analyze_scene(scene):
    targets, excludes = _records(scene)
    if len(targets) < 7:
        fit = fit_handle(
            [item.world_location for item in targets],
            [item.world_normal for item in targets],
        )
        return fit, None, targets, excludes, {"source": None}
    source, snapshot = _source_for_targets(scene, targets)
    target_values = [_current_anchor(item, source) for item in targets]
    supports = [item for item in excludes if item.source_object_name == source.name]
    support_values = [_current_anchor(item, source) for item in supports]
    fit = fit_handle(
        [tuple(value[0]) for value in target_values],
        [tuple(value[1]) for value in target_values],
        [tuple(value[0]) for value in support_values],
        [tuple(value[1]) for value in support_values],
        radius_hint=_marked_edge_radius(source, targets),
    )
    return fit, source, targets, supports, {"source": snapshot}


def _dense_triangle_samples(source, records, order=5):
    result = []
    seen = set()
    for record in records:
        face_index = int(record.face_index)
        if face_index in seen or not 0 <= face_index < len(source.data.polygons):
            continue
        seen.add(face_index)
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


def _local(points, fit):
    points = np.asarray(points, dtype=float)
    relative = points - np.asarray(fit.origin, dtype=float)
    span = np.asarray(fit.span_axis, dtype=float)
    rise = np.asarray(fit.rise_axis, dtype=float)
    normal = np.asarray(fit.plane_normal, dtype=float)
    return np.column_stack((relative @ span, relative @ rise, relative @ normal))


def _path_distances(local, fit):
    path = path_points_2d(fit.path_kind, fit.half_span, fit.rise, fit.corner_radius, 160)
    points = np.asarray(local[:, :2], dtype=float)
    result = np.full(len(points), np.inf, dtype=float)
    for first, second in zip(path[:-1], path[1:]):
        direction = second - first
        denominator = float(direction @ direction)
        if denominator <= 1.0e-12:
            candidate = np.linalg.norm(points - first, axis=1)
        else:
            factor = np.clip(((points - first) @ direction) / denominator, 0.0, 1.0)
            candidate = np.linalg.norm(points - (first + factor[:, None] * direction), axis=1)
        result = np.minimum(result, candidate)
    return result


def _support_penetrations(source, supports, fit, section_radius):
    points = [tuple(_current_anchor(item, source)[0]) for item in supports]
    local = _local(points, fit)
    required = section_radius * 1.15
    result, evidence = [], []
    for side, endpoint in ((-1, -fit.half_span), (1, fit.half_span)):
        mask = np.abs(local[:, 0] - endpoint) <= fit.half_span * 0.38
        values = local[mask, 1]
        if not len(values):
            result.append(0.0)
            evidence.append({"side": side, "samples": 0, "connected": False})
            continue
        support_level = float(np.median(values))
        penetration = max(required, -support_level + required)
        result.append(penetration)
        evidence.append({
            "side": side, "samples": int(len(values)), "support_level": support_level,
            "penetration": penetration, "required_burial": required, "connected": True,
        })
    return tuple(result), evidence


def _candidate_geometry(path, plane_normal, normal_radius, in_plane_radius, sides):
    path = np.asarray(path, dtype=float)
    normal = np.asarray(plane_normal, dtype=float)
    vertices, rings = [], []
    for index, point in enumerate(path):
        if index == 0:
            tangent = path[1] - point
        elif index == len(path) - 1:
            tangent = point - path[-2]
        else:
            tangent = path[index + 1] - path[index - 1]
        tangent /= max(float(np.linalg.norm(tangent)), 1.0e-12)
        in_plane = np.cross(tangent, normal)
        in_plane /= max(float(np.linalg.norm(in_plane)), 1.0e-12)
        ring = []
        for side in range(sides):
            angle = 2.0 * np.pi * side / sides
            ring.append(len(vertices))
            value = point + normal * (np.cos(angle) * normal_radius) + in_plane * (
                np.sin(angle) * in_plane_radius
            )
            vertices.append(tuple(float(component) for component in value))
        rings.append(ring)
    faces = []
    for first, second in zip(rings[:-1], rings[1:]):
        for index in range(sides):
            following = (index + 1) % sides
            faces.append((first[index], first[following], second[following], second[index]))
    faces.append(tuple(reversed(rings[0])))
    faces.append(tuple(rings[-1]))
    return vertices, faces


def _topology(vertices, faces):
    edge_counts = {}
    for face in faces:
        for index, first in enumerate(face):
            edge = tuple(sorted((first, face[(index + 1) % len(face)])))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    nonmanifold = sum(count != 2 for count in edge_counts.values())
    finite = bool(np.all(np.isfinite(np.asarray(vertices, dtype=float))))
    return {
        "vertices": len(vertices), "faces": len(faces), "edges": len(edge_counts),
        "components": 1 if vertices else 0, "boundary_or_nonmanifold_edges": nonmanifold,
        "finite": finite, "passed": finite and nonmanifold == 0 and bool(vertices),
    }


def _checkpoint(scene, source):
    existing = str(scene.get("smrn_handle_checkpoint_path", ""))
    if existing and Path(existing).exists():
        return existing
    if not bpy.data.filepath:
        raise ValueError("当前 .blend 尚未保存，无法建立扶手源检查点")
    current = Path(bpy.data.filepath)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = current.with_name(f"{current.stem}_before_smrn_handle_{stamp}{current.suffix}")
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
    scene["smrn_handle_checkpoint_path"] = str(path)
    source["smrn_handle_checkpoint_fingerprint"] = source_snapshot(source)["fingerprint"]
    return str(path)


def remove_last_candidate(scene):
    name = str(scene.get("smrn_handle_candidate_name", ""))
    obj = bpy.data.objects.get(name)
    if obj is None or not name.startswith(CANDIDATE_PREFIX):
        if name.startswith(CANDIDATE_PREFIX):
            scene["smrn_handle_candidate_name"] = ""
        return False
    source = bpy.data.objects.get(str(obj.get("smrn_source_name", "")))
    _remove_candidate_object(obj)
    scene["smrn_handle_candidate_name"] = ""
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
    key = "smrn_handle_candidate_name"
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


def build_scene_candidate(scene):
    fit, source, targets, supports, context_report = analyze_scene(scene)
    report = {"fit": fit.to_dict(), **context_report}
    if fit.status != "candidate_ready" or source is None:
        report.update({"status": "rejected", "reason": fit.reason})
        return None, report
    fingerprint_before = source_snapshot(source)["fingerprint"]
    dense = _dense_triangle_samples(source, targets)
    if not dense:
        report.update({"status": "rejected", "reason": "标记面没有可用于外覆盖检查的三角形"})
        return None, report
    local = _local(dense, fit)
    residual = _path_distances(local, fit)
    median = float(np.quantile(residual, 0.50))
    mad = float(np.median(np.abs(residual - median)))
    corridor = max(fit.radius_hint * 2.75, median + max(fit.radius_hint * 0.75, mad * 5.0))
    retained = residual <= corridor
    retention = float(np.mean(retained))
    if retention < 0.80:
        report.update({
            "status": "rejected", "reason": "密集管体样本保留不足，长安装桥与扶手主体无法可靠分离",
            "dense_corridor": {"samples": len(dense), "retained_ratio": retention},
        })
        return None, report
    # Mounting bridges/feet may be selected together with the tube.  Keep them
    # for endpoint connectivity, but never let their broad plate-like faces
    # inflate the recovered tube section.
    terminal_bridge = (
        (local[:, 1] < -fit.radius_hint * 1.5)
        & (np.abs(local[:, 0]) > fit.half_span * 0.70)
    )
    body_mask = retained & ~terminal_bridge
    if float(np.mean(body_mask)) < 0.55:
        report.update({
            "status": "rejected",
            "reason": "排除端部安装桥后，扶手管体的密集覆盖证据不足",
            "dense_corridor": {
                "samples": len(dense), "retained_ratio": retention,
                "body_ratio": float(np.mean(body_mask)),
            },
        })
        return None, report
    body_local = local[body_mask]
    body_residual = residual[body_mask]
    clearance = max(0.0, float(scene.smrn_handle_clearance))
    normal_values = np.abs(body_local[:, 2])
    source_normal_radius = max(
        fit.radius_hint, float(np.quantile(normal_values, 0.95))
    )
    source_in_plane_radius = max(
        fit.radius_hint, float(np.quantile(body_residual, 0.95))
    )
    # Scale the two independently measured axes together only as much as is
    # required for every retained body sample to lie inside the elliptic tube.
    ellipse_norm = np.sqrt(
        np.square(normal_values / source_normal_radius)
        + np.square(body_residual / source_in_plane_radius)
    )
    coverage_scale = max(1.0, float(np.max(ellipse_norm)))
    source_normal_radius = source_normal_radius * coverage_scale + clearance
    source_in_plane_radius = source_in_plane_radius * coverage_scale + clearance
    requested_radius = max(0.0, float(scene.smrn_handle_min_diameter) * 0.5)
    normal_radius = max(fit.radius_hint, source_normal_radius, requested_radius)
    in_plane_radius = max(fit.radius_hint, source_in_plane_radius, requested_radius)
    section_radius = max(normal_radius, in_plane_radius)
    penetrations, endpoint_evidence = _support_penetrations(
        source, supports, fit, section_radius
    )
    if not all(item["connected"] for item in endpoint_evidence):
        report.update({"status": "rejected", "reason": "左右端点没有各自独立的安装面证据"})
        return None, report
    path = path_points_world(
        fit, max(48, int(scene.smrn_handle_path_segments)), penetrations
    )
    vertices, faces = _candidate_geometry(
        path, fit.plane_normal, normal_radius, in_plane_radius,
        max(8, int(scene.smrn_handle_section_segments)),
    )
    topology = _topology(vertices, faces)
    normalized = np.sqrt(
        np.square(normal_values / max(normal_radius, 1.0e-12))
        + np.square(body_residual / max(in_plane_radius, 1.0e-12))
    )
    uncovered = int(np.sum(normalized > 1.0 + 1.0e-9))
    coverage = {
        "samples": int(np.sum(body_mask)), "uncovered": uncovered,
        "bridge_outliers": int(np.sum(~retained)), "retained_ratio": retention,
        "terminal_bridge_samples": int(np.sum(terminal_bridge & retained)),
        "normal_radius": normal_radius, "in_plane_radius": in_plane_radius,
        "passed": uncovered == 0,
    }
    source_unchanged = source_snapshot(source)["fingerprint"] == fingerprint_before
    report.update({
        "status": "candidate_ready", "coverage_qa": coverage,
        "endpoint_qa": endpoint_evidence, "endpoint_penetrations": list(penetrations),
        "topology_qa": topology, "source_unchanged": source_unchanged,
    })
    if not topology["passed"] or not coverage["passed"] or not source_unchanged:
        report.update({"status": "rejected", "reason": "扶手候选未通过拓扑或源不变性检查"})
        return None, report
    checkpoint = _checkpoint(scene, source)
    report["checkpoint"] = checkpoint
    _model, candidates, _helpers = ensure_scene_roots(scene)
    mesh = bpy.data.meshes.new(f"{CANDIDATE_PREFIX}MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(f"{CANDIDATE_PREFIX}{fit.path_kind.upper()}", mesh)
    candidates.objects.link(obj)
    obj.color = (1.0, 0.24, 0.03, 0.78)
    obj.show_wire = True
    obj.show_all_edges = True
    obj["smrn_candidate_only"] = True
    obj["smrn_source_name"] = source.name
    obj["smrn_handle_report_json"] = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    _commit_candidate(scene, obj)
    scene["smrn_handle_last_report_json"] = obj["smrn_handle_report_json"]
    return obj, report


def store_analysis(scene, report):
    scene["smrn_handle_last_report_json"] = json.dumps(
        report, ensure_ascii=False, separators=(",", ":")
    )
