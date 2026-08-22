"""Blender adapter and non-destructive builder for grab-handle candidates."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
import numpy as np

from .anchors import source_snapshot
from .constants import EXCLUDE_ROLE, SOURCE_NAME_KEY, TARGET_ROLE
from .handle_fit import (
    endpoint_support_indices,
    fit_handle,
    minimum_enclosing_circle,
    path_points_2d,
    path_points_world,
    polyline_nearest,
)
from .scene_state import ensure_scene_roots, keep_model_visible
from .storage import load_all_marks


CANDIDATE_PREFIX = "SMRN_HANDLE_CANDIDATE_"


def _evidence_request(fit, targets, supports):
    """Return one compact, actionable request instead of guessing geometry."""
    if fit.status == "candidate_ready":
        return {"required": False, "message": "当前证据充足"}
    missing_green = max(0, 7 - len(targets))
    if missing_green:
        green = (
            f"再补至少 {missing_green} 个绿色管体标记，分布到两腿、两处弯角和顶部"
        )
    else:
        green = (
            "绿色标记数量已经足够；当前拒绝来自路径一致性检查："
            f"{fit.reason}。无需继续增加标记"
        )
    red = None
    if len(supports) < 2:
        red = "若两端安装角度或落点不明确，请在左右安装平面各补 1 个红色标记"
    message = green if red is None else f"{green}；{red}"
    return {
        "required": True,
        "green": green,
        "red": red,
        "message": message,
        "target_count": len(targets),
        "support_count": len(supports),
    }


def _world_normal(obj, local_normal):
    value = obj.matrix_world.to_3x3().inverted_safe().transposed() @ Vector(local_normal)
    return value.normalized() if value.length_squared else Vector((0.0, 0.0, 1.0))


def _evidence_object(record):
    """Return the mesh that owns the stored face/local anchor.

    The semantic task source and the ray-hit mesh are deliberately separate:
    overlapping component meshes may belong to one vehicle while retaining
    independent face indices and transforms.
    """
    obj = bpy.data.objects.get(record.hit_object_name) or bpy.data.objects.get(
        record.source_object_name
    )
    if obj is None or obj.type != "MESH":
        raise ValueError(f"找不到标记 {record.id} 对应的命中网格")
    return obj


def _current_anchor(record, obj=None):
    obj = obj or _evidence_object(record)
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
    source = bpy.data.objects.get(str(scene.get(SOURCE_NAME_KEY, "")))
    if source is None and targets:
        source = _evidence_object(targets[0])
    if source is None or source.type != "MESH":
        raise ValueError("找不到扶手标记对应的源网格")
    snapshot = source_snapshot(source)
    evidence = {}
    for record in targets:
        obj = _evidence_object(record)
        current = evidence.setdefault(obj.name, source_snapshot(obj))
        if record.source_fingerprint and current["fingerprint"] != record.source_fingerprint:
            raise ValueError(f"命中网格 {obj.name} 已在标记后变化，请重新标记扶手")
    return source, snapshot, list(evidence.values())


def _marked_edge_radius(targets):
    lengths = []
    seen = set()
    for record in targets:
        source = _evidence_object(record)
        face_index = int(record.face_index)
        face_key = (source.name, face_index)
        if face_key in seen or not 0 <= face_index < len(source.data.polygons):
            continue
        seen.add(face_key)
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
        return fit, None, targets, excludes, {
            "source": None,
            "evidence_request": _evidence_request(fit, targets, excludes),
        }
    source, snapshot, evidence = _source_for_targets(scene, targets)
    target_values = [_current_anchor(item) for item in targets]
    all_supports = excludes
    support_values = [_current_anchor(item) for item in all_supports]
    target_points = [tuple(value[0]) for value in target_values]
    target_normals = [tuple(value[1]) for value in target_values]
    # The green tube is the primary geometric source.  Red installation marks
    # may refine it only after proving that they independently cover both feet.
    # Face-edge scale is a useful section estimate, but it must only influence
    # the green tube fit.  It must never be combined with an unverified red
    # background strip to define the handle span/frame.
    green_fit = fit_handle(
        target_points, target_normals, radius_hint=_marked_edge_radius(targets)
    )
    support_indices, support_assessment = endpoint_support_indices(
        green_fit, [tuple(value[0]) for value in support_values]
    )
    supports = [all_supports[index] for index in support_indices]
    active_values = [support_values[index] for index in support_indices]
    supported_fit = None
    if supports:
        supported_fit = fit_handle(
            target_points,
            target_normals,
            [tuple(value[0]) for value in active_values],
            [tuple(value[1]) for value in active_values],
            radius_hint=green_fit.radius_hint,
        )
    # Conflicting optional evidence cannot veto an already valid green fit.
    # It is kept in the report so the decision remains inspectable.
    if supported_fit is not None and supported_fit.status == "candidate_ready":
        fit = supported_fit
        support_assessment["used_for_frame"] = True
    else:
        fit = green_fit
        support_assessment["used_for_frame"] = False
        if supported_fit is not None:
            support_assessment["supported_fit_reason"] = supported_fit.reason
    return fit, source, targets, supports, {
        "source": snapshot,
        "evidence_sources": evidence,
        "support_evidence": support_assessment,
        "evidence_request": _evidence_request(fit, targets, all_supports),
    }


def _dense_triangle_samples(records, order=5):
    result = []
    seen = set()
    for record in records:
        source = _evidence_object(record)
        face_index = int(record.face_index)
        face_key = (source.name, face_index)
        if face_key in seen or not 0 <= face_index < len(source.data.polygons):
            continue
        seen.add(face_key)
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


def _dense_face_samples(face_map, order=4):
    """Densely sample every triangle in a semantic face map without trimming."""
    result = []
    areas = []
    owners = []
    for object_name, face_indices in face_map.items():
        source = bpy.data.objects.get(object_name)
        if source is None or source.type != "MESH":
            continue
        for face_index in sorted(face_indices):
            if not 0 <= face_index < len(source.data.polygons):
                continue
            polygon = source.data.polygons[face_index]
            indices = list(polygon.vertices)
            if len(indices) < 3:
                continue
            anchor = source.matrix_world @ source.data.vertices[indices[0]].co
            triangle_area = float(polygon.area) / max(1, len(indices) - 2)
            for corner in range(1, len(indices) - 1):
                b = source.matrix_world @ source.data.vertices[indices[corner]].co
                c = source.matrix_world @ source.data.vertices[indices[corner + 1]].co
                sample_count = (order + 1) * (order + 2) // 2
                for i in range(order + 1):
                    for j in range(order + 1 - i):
                        u, v = i / order, j / order
                        result.append(tuple(anchor * (1.0 - u - v) + b * u + c * v))
                        areas.append(triangle_area / sample_count)
                        owners.append((object_name, face_index))
    return np.asarray(result, dtype=float), np.asarray(areas, dtype=float), owners


def _path_vertex_frames(path, plane_normal):
    path = np.asarray(path, dtype=float)
    normal = np.asarray(plane_normal, dtype=float)
    tangents = np.empty_like(path)
    tangents[0] = path[1] - path[0]
    tangents[-1] = path[-1] - path[-2]
    tangents[1:-1] = path[2:] - path[:-2]
    tangents /= np.maximum(np.linalg.norm(tangents, axis=1)[:, None], 1.0e-12)
    in_plane = np.cross(tangents, normal)
    in_plane /= np.maximum(np.linalg.norm(in_plane, axis=1)[:, None], 1.0e-12)
    return tangents, in_plane


def _semantic_handle_faces(targets, path, plane_normal, corridor):
    """Grow marked tube faces by local topology from the explicit seeds.

    The old handle is welded into the vehicle mesh, so unrestricted connected
    selection reaches the complete turret.  This traversal only evaluates
    neighbours reached from marked faces; it never constructs centers,
    normals, or a geometric eligibility mask for every face in the vehicle.
    A reached face enters the flood only when it is close to the fitted
    centerline and transverse to the local path tangent, as a tube wall must
    be. BMesh supplies edge links, while geometric work remains local.
    """
    import bmesh

    seeds_by_object = {}
    for record in targets:
        source = _evidence_object(record)
        seeds_by_object.setdefault(source.name, set()).add(int(record.face_index))
    result = {}
    diagnostics = []
    for object_name, seeds in seeds_by_object.items():
        source = bpy.data.objects.get(object_name)
        if source is None or source.type != "MESH":
            continue
        mesh_face_count = len(source.data.polygons)
        bm = bmesh.new()
        try:
            bm.from_mesh(source.data)
            bm.faces.ensure_lookup_table()
            accepted = set()
            visited = set()
            queued = set()
            queue = []
            for seed in seeds:
                if not 0 <= seed < len(bm.faces):
                    continue
                accepted.add(seed)
                for edge in bm.faces[seed].edges:
                    for adjacent in edge.link_faces:
                        index = int(adjacent.index)
                        if index not in accepted and index not in queued:
                            queue.append(adjacent)
                            queued.add(index)
            while queue:
                face = queue.pop()
                face_index = int(face.index)
                queued.discard(face_index)
                if face_index in accepted or face_index in visited:
                    continue
                visited.add(face_index)
                center = source.matrix_world @ face.calc_center_median()
                normal = _world_normal(source, face.normal)
                _nearest, tangents, distances = polyline_nearest(
                    np.asarray([tuple(center)], dtype=float), path
                )
                transverse = abs(float(np.dot(tuple(normal), tangents[0]))) <= 0.62
                if float(distances[0]) > corridor or not transverse:
                    continue
                accepted.add(face_index)
                for edge in face.edges:
                    for adjacent in edge.link_faces:
                        index = int(adjacent.index)
                        if index not in accepted and index not in visited and index not in queued:
                            queue.append(adjacent)
                            queued.add(index)
            result[object_name] = accepted
            diagnostics.append({
                "object": object_name,
                "seed_faces": len(seeds),
                "expanded_faces": len(accepted),
                "locally_tested_faces": len(visited),
                "object_faces": mesh_face_count,
                "tested_ratio": len(visited) / max(1, mesh_face_count),
                "global_geometry_scan": False,
                "corridor": float(corridor),
                "normal_tangent_limit": 0.62,
            })
        finally:
            bm.free()
    return result, diagnostics


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


def _inferred_mount_surface(scene, fit, side, section_radius):
    """Find the outer and inner mounting skins below one fitted handle leg."""
    origin = Vector(fit.origin)
    span = Vector(fit.span_axis)
    rise = Vector(fit.rise_axis)
    baseline = origin + span * (side * fit.half_span)
    cursor = baseline + rise * (section_radius * 2.0)
    travelled = -section_radius * 2.0
    depsgraph = bpy.context.evaluated_depsgraph_get()
    step_epsilon = max(1.0e-4, section_radius * 0.02)
    maximum_depth = max(section_radius * 8.0, fit.rise * 2.0)
    surface = None
    for _index in range(20):
        hit, location, normal, face_index, obj, _matrix = scene.ray_cast(
            depsgraph, cursor, -rise, distance=maximum_depth
        )
        if not hit:
            return surface
        travelled += float((cursor - location).dot(rise))
        name = obj.name if obj is not None else ""
        alignment = float(normal.dot(rise))
        # Tube/candidate caps face downward; the mounting skin faces back up
        # toward the leg. This also avoids deriving an angle from world axes.
        is_helper = (
            name.startswith((CANDIDATE_PREFIX, "SMRN_MARK_", "SMR_VISIBLE_MARK_", "SMR_CONSTRAINT_"))
            or bool(obj and (
                obj.get("smrn_accepted", False)
                or obj.get("smrn_accepted_baseline", False)
            ))
        )
        if surface is None and (
            not is_helper
            and travelled >= section_radius * 0.05
            and travelled <= maximum_depth
            and alignment >= 0.55
        ):
            surface = {
                "object": name,
                "face_index": int(face_index),
                "surface_depth": travelled,
                "normal_alignment": alignment,
            }
        elif (
            surface is not None
            and name == surface["object"]
            and travelled > surface["surface_depth"]
            and alignment <= -0.55
        ):
            surface["back_face_index"] = int(face_index)
            surface["back_depth"] = travelled
            surface["wall_thickness"] = travelled - surface["surface_depth"]
            return surface
        cursor = location - rise * step_epsilon
        travelled += step_epsilon
    return surface


def _support_penetrations(scene, supports, fit, section_radius):
    points = [tuple(_current_anchor(item)[0]) for item in supports]
    local = _local(points, fit) if points else np.empty((0, 3), dtype=float)
    required = section_radius * 1.50
    result, evidence = [], []
    for side, endpoint in ((-1, -fit.half_span), (1, fit.half_span)):
        mask = np.abs(local[:, 0] - endpoint) <= fit.half_span * 0.38
        values = local[mask, 1]
        if not len(values):
            surface = _inferred_mount_surface(scene, fit, side, section_radius)
            surface_depth = float(surface["surface_depth"]) if surface else 0.0
            if surface and surface.get("wall_thickness", 0.0) > 0.0:
                # End inside the actual wall, not beyond its back face. This
                # is deep enough to eliminate a floating cap while remaining
                # safe on thin shells.
                penetration = surface_depth + float(surface["wall_thickness"]) * 0.65
            elif surface:
                penetration = max(required, surface_depth + section_radius * 0.50)
            else:
                penetration = required
            result.append(penetration)
            evidence.append({
                "side": side, "samples": 0, "connected": True,
                "inferred": True, "penetration": penetration,
                "required_burial": required,
                "mount_surface": surface,
            })
            continue
        support_level = float(np.median(values))
        penetration = max(required, -support_level + required)
        result.append(penetration)
        evidence.append({
            "side": side, "samples": int(len(values)), "support_level": support_level,
            "penetration": penetration, "required_burial": required,
            "connected": True, "inferred": False,
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


def _mesh_containment(vertices, faces, points, sample_areas, owners, tolerance):
    """Test points against the actual watertight shell using winding numbers.

    Nearest-face normal signs are not a valid inside/outside test around swept
    bends, while parity rays can double-hit shared polygon boundaries.  The
    generalized winding number integrates solid angle over every candidate
    triangle and therefore tests the closed shell itself. Nearest distance is
    retained as the measured deficit used to enlarge a rejected shell.
    """
    bvh = BVHTree.FromPolygons(
        [Vector(value) for value in vertices], faces, all_triangles=False
    )
    vertex_values = np.asarray(vertices, dtype=float)
    triangles = []
    for face in faces:
        for index in range(1, len(face) - 1):
            triangles.append((face[0], face[index], face[index + 1]))
    triangle_values = vertex_values[np.asarray(triangles, dtype=int)]

    def winding_inside(point):
        vectors = triangle_values - np.asarray(point, dtype=float)[None, None, :]
        first, second, third = vectors[:, 0], vectors[:, 1], vectors[:, 2]
        first_length = np.linalg.norm(first, axis=1)
        second_length = np.linalg.norm(second, axis=1)
        third_length = np.linalg.norm(third, axis=1)
        numerator = np.einsum("ij,ij->i", first, np.cross(second, third))
        denominator = (
            first_length * second_length * third_length
            + np.einsum("ij,ij->i", first, second) * third_length
            + np.einsum("ij,ij->i", second, third) * first_length
            + np.einsum("ij,ij->i", third, first) * second_length
        )
        winding = float(np.sum(2.0 * np.arctan2(numerator, denominator)))
        return abs(winding) > 2.0 * np.pi

    signed_values = []
    outside = []
    for index, point in enumerate(points):
        _location, _normal, _face, distance = bvh.find_nearest(Vector(point))
        distance = float(distance)
        if distance <= tolerance:
            inside = True
        else:
            inside = winding_inside(point)
        signed = -distance if inside else distance
        signed_values.append(signed)
        if not inside:
            outside.append((index, signed, distance, owners[index]))
    worst = sorted(outside, key=lambda item: item[1], reverse=True)[:12]
    return {
        "samples": int(len(points)),
        "outside": int(len(outside)),
        "outside_area": float(sum(sample_areas[index] for index, *_rest in outside)),
        "max_signed": float(max(signed_values)),
        "min_signed": float(min(signed_values)),
        "tolerance": float(tolerance),
        "worst": [[int(index), signed, distance, list(owner)]
                  for index, signed, distance, owner in worst],
        "passed": not outside,
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


def adjust_candidate_thickness(scene):
    """Resize only the current unaccepted handle tube; never rescan the model."""
    name = str(scene.get("smrn_handle_candidate_name", ""))
    obj = bpy.data.objects.get(name)
    if obj is None or not name.startswith(CANDIDATE_PREFIX):
        raise ValueError("没有可调整的扶手候选")
    if bool(obj.get("smrn_accepted", False)):
        raise ValueError("已确认扶手受保护，不能再调整")
    try:
        report = json.loads(str(obj.get("smrn_handle_report_json", "{}")))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("当前候选缺少可靠的生成报告") from error
    if report.get("status") != "candidate_ready":
        raise ValueError("当前候选尚未通过生成质量门槛")

    sides = int(obj.get("smrn_handle_section_segments", scene.smrn_handle_section_segments))
    vertex_count = len(obj.data.vertices)
    if sides < 8 or vertex_count < sides * 2 or vertex_count % sides:
        raise ValueError("当前候选的截面结构不可安全调整")
    target_scale = max(1.0, float(scene.smrn_handle_thickness_scale))
    current_scale = max(1.0, float(obj.get("smrn_handle_thickness_scale", 1.0)))
    ratio = target_scale / current_scale
    if abs(ratio - 1.0) > 1.0e-9:
        vertices = obj.data.vertices
        for start in range(0, vertex_count, sides):
            center = Vector((0.0, 0.0, 0.0))
            for index in range(start, start + sides):
                center += vertices[index].co
            center /= sides
            for index in range(start, start + sides):
                vertices[index].co = center + (vertices[index].co - center) * ratio
        obj.data.update()

    coverage = report.setdefault("coverage_qa", {})
    adjustment = report.setdefault("thickness_adjustment", {})
    base_radius = float(adjustment.get(
        "base_radius", float(coverage.get("normal_radius", 0.0)) / current_scale,
    ))
    base_clearances = adjustment.get("base_clearances")
    if not isinstance(base_clearances, dict):
        base_clearances = {
            key: float(coverage[key])
            for key in ("clearance_min", "clearance_median", "clearance_p95", "clearance_max")
            if key in coverage
        }
    adjusted_radius = base_radius * target_scale
    coverage["normal_radius"] = adjusted_radius
    coverage["in_plane_radius"] = adjusted_radius
    radius_growth = adjusted_radius - base_radius
    for key, value in base_clearances.items():
        coverage[key] = float(value) + radius_growth
    adjustment.update({
        "scale": target_scale,
        "base_radius": base_radius,
        "adjusted_radius": adjusted_radius,
        "base_clearances": base_clearances,
        "model_rescanned": False,
        "accepted_geometry_modified": False,
    })
    obj["smrn_handle_thickness_scale"] = target_scale
    obj["smrn_handle_report_json"] = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    scene["smrn_handle_last_report_json"] = obj["smrn_handle_report_json"]
    source = bpy.data.objects.get(str(obj.get("smrn_source_name", "")))
    keep_model_visible(scene, (obj, source))
    return obj, report


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
    # Accepted objects are immutable baselines. Even a stale scene pointer must
    # never make a future build treat one as a disposable working candidate.
    if old_obj is not None and bool(old_obj.get("smrn_accepted", False)):
        old_obj = None
        old_name = ""
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


def _build_scene_candidate_legacy(scene):
    fit, source, targets, supports, context_report = analyze_scene(scene)
    report = {"fit": fit.to_dict(), **context_report}
    if fit.status != "candidate_ready" or source is None:
        report.update({"status": "rejected", "reason": fit.reason})
        return None, report
    fingerprint_before = source_snapshot(source)["fingerprint"]
    evidence_before = {
        _evidence_object(item).name: source_snapshot(_evidence_object(item))["fingerprint"]
        for item in targets + supports
    }
    dense = _dense_triangle_samples(targets)
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
    cross_radius = np.sqrt(np.square(normal_values) + np.square(body_residual))
    # A handful of broad mounting-face/corner samples must not determine the
    # whole tube diameter. Recover one round section from the robust 95th
    # percentile, then keep the trimmed samples explicit in the QA report.
    source_radius = max(fit.radius_hint, float(np.quantile(cross_radius, 0.95)))
    section_tolerance = max(1.0e-9, source_radius * 1.0e-6)
    section_body = cross_radius <= source_radius + section_tolerance
    if int(np.sum(section_body)) < 24:
        report.update({
            "status": "rejected",
            "reason": "扶手圆截面的可靠密集样本不足",
        })
        return None, report
    reliable_normal = normal_values[section_body]
    reliable_residual = body_residual[section_body]
    requested_radius = max(0.0, float(scene.smrn_handle_min_diameter) * 0.5)
    section_radius = max(source_radius + clearance, requested_radius)
    normal_radius = in_plane_radius = section_radius
    penetrations, endpoint_evidence = _support_penetrations(
        scene, supports, fit, section_radius
    )
    path = path_points_world(
        fit, max(48, int(scene.smrn_handle_path_segments)), penetrations
    )
    vertices, faces = _candidate_geometry(
        path, fit.plane_normal, normal_radius, in_plane_radius,
        max(8, int(scene.smrn_handle_section_segments)),
    )
    topology = _topology(vertices, faces)
    normalized = np.sqrt(
        np.square(reliable_normal / max(normal_radius, 1.0e-12))
        + np.square(reliable_residual / max(in_plane_radius, 1.0e-12))
    )
    uncovered = int(np.sum(normalized > 1.0 + 1.0e-9))
    coverage = {
        "samples": int(np.sum(section_body)), "uncovered": uncovered,
        "bridge_outliers": int(np.sum(~retained)), "retained_ratio": retention,
        "terminal_bridge_samples": int(np.sum(terminal_bridge & retained)),
        "section_outliers": int(np.sum(~section_body)),
        "normal_radius": normal_radius, "in_plane_radius": in_plane_radius,
        "passed": uncovered == 0,
    }
    source_unchanged = source_snapshot(source)["fingerprint"] == fingerprint_before
    evidence_unchanged = all(
        bpy.data.objects.get(name) is not None
        and source_snapshot(bpy.data.objects[name])["fingerprint"] == fingerprint
        for name, fingerprint in evidence_before.items()
    )
    report.update({
        "status": "candidate_ready", "coverage_qa": coverage,
        "endpoint_qa": endpoint_evidence, "endpoint_penetrations": list(penetrations),
        "topology_qa": topology, "source_unchanged": source_unchanged,
        "evidence_sources_unchanged": evidence_unchanged,
        "frame_qa": {
            "shared_leg_axis": True,
            "span_rise_dot": abs(float(np.dot(fit.span_axis, fit.rise_axis))),
            "span_normal_dot": abs(float(np.dot(fit.span_axis, fit.plane_normal))),
            "rise_normal_dot": abs(float(np.dot(fit.rise_axis, fit.plane_normal))),
            "plane_thickness_ratio": fit.plane_thickness_ratio,
            "passed": fit.status == "candidate_ready",
        },
    })
    if not topology["passed"] or not coverage["passed"] or not source_unchanged or not evidence_unchanged:
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
    obj["smrn_handle_section_segments"] = max(8, int(scene.smrn_handle_section_segments))
    obj["smrn_handle_thickness_scale"] = 1.0
    obj["smrn_source_name"] = source.name
    obj["smrn_handle_report_json"] = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    _commit_candidate(scene, obj)
    scene["smrn_handle_last_report_json"] = obj["smrn_handle_report_json"]
    return obj, report


def build_scene_candidate(scene):
    """Build a centered, minimum-radius candidate covering all semantic tube faces."""
    fit, source, targets, supports, context_report = analyze_scene(scene)
    report = {"fit": fit.to_dict(), **context_report}
    if fit.status != "candidate_ready" or source is None:
        report.update({"status": "rejected", "reason": fit.reason})
        return None, report
    fingerprint_before = source_snapshot(source)["fingerprint"]
    evidence_before = {
        _evidence_object(item).name: source_snapshot(_evidence_object(item))["fingerprint"]
        for item in targets + supports
    }
    marked_dense = _dense_triangle_samples(targets, order=6)
    if not marked_dense:
        report.update({"status": "rejected", "reason": "marked faces have no valid triangles"})
        return None, report

    path_segments = max(64, int(scene.smrn_handle_path_segments))
    base_path = path_points_world(fit, path_segments, (0.0, 0.0))
    # Bound semantic growth from the actual brush-hit anchors, not from every
    # vertex of the hit polygons.  A valid low-poly handle face can contain a
    # long triangulation tail welded into the vehicle shell; using that tail's
    # maximum distance made one good green mark inflate the corridor, section,
    # and inferred endpoint depth by an order of magnitude.
    anchor_values = np.asarray(
        [tuple(_current_anchor(item)[0]) for item in targets], dtype=float
    )
    _anchor_nearest, _anchor_tangents, anchor_distances = polyline_nearest(
        anchor_values, base_path
    )
    corridor = max(
        float(np.quantile(anchor_distances, 0.95)) + fit.radius_hint * 1.25,
        fit.radius_hint * 2.75,
    )
    semantic_faces, semantic_diagnostics = _semantic_handle_faces(
        targets, base_path, fit.plane_normal, corridor
    )
    dense, sample_areas, sample_owners = _dense_face_samples(semantic_faces, order=4)
    if len(dense) < 24:
        report.update({
            "status": "rejected",
            "reason": "topology and orientation gates found too little complete tube-wall evidence",
            "evidence_request": {
                "required": True,
                "green": "沿缺失的腿部、弯角或顶部补充绿色管体标记",
                "red": "若端部安装面仍不明确，在左右安装平面各补 1 个红色标记",
                "message": "局部管体证据不足：补绿色路径标记；端部角度不明确时再补左右红色安装平面",
            },
            "semantic_expansion": semantic_diagnostics,
        })
        return None, report

    raw_semantic_samples = int(len(dense))

    nearest, tangents, base_distances = polyline_nearest(dense, base_path)
    plane_normal = np.asarray(fit.plane_normal, dtype=float)
    local_dense = _local(dense, fit)
    # Faces on the mounting feet extend axially below the fitted baseline.
    # They determine endpoint burial, not tube diameter.  Including those
    # axial extensions in a cross-section circle is the exact failure that
    # produced an enormously thick handle when the user added more marks.
    below_baseline = local_dense[:, 1] < -fit.radius_hint * 1.25
    start_terminal_distance = np.sqrt(
        np.square(local_dense[:, 0] + fit.half_span)
        + np.square(local_dense[:, 2])
    )
    end_terminal_distance = np.sqrt(
        np.square(local_dense[:, 0] - fit.half_span)
        + np.square(local_dense[:, 2])
    )
    terminal_extension = below_baseline & (
        (start_terminal_distance <= corridor)
        | (end_terminal_distance <= corridor)
    )
    # Retain the complete local tube corridor and bounded axial mounting
    # extensions.  Samples outside both are triangulation bridges, not a
    # request to cover the surrounding hull.  They remain counted and
    # reported, but cannot determine tube diameter or candidate containment.
    path_supported = (base_distances <= corridor) | terminal_extension
    if np.any(~path_supported):
        dense = dense[path_supported]
        sample_areas = sample_areas[path_supported]
        sample_owners = [
            owner for owner, retained in zip(sample_owners, path_supported) if retained
        ]
        nearest = nearest[path_supported]
        tangents = tangents[path_supported]
        base_distances = base_distances[path_supported]
        local_dense = local_dense[path_supported]
        terminal_extension = terminal_extension[path_supported]
    discarded_path_bridge_samples = raw_semantic_samples - int(len(dense))
    if len(dense) < 24:
        report.update({
            "status": "rejected",
            "reason": "排除与车体相连的长三角桥接后，局部管体证据不足",
            "semantic_expansion": semantic_diagnostics,
        })
        return None, report
    # Rebuild the cross-section frame after dropping triangulation bridges.
    # Keeping the pre-filter arrays here would pair retained samples with stale
    # offsets and can either fail by shape mismatch or corrupt the radius fit.
    in_plane = np.cross(tangents, plane_normal)
    in_plane /= np.maximum(np.linalg.norm(in_plane, axis=1)[:, None], 1.0e-12)
    offsets = dense - nearest
    section_mask = ~terminal_extension
    if int(np.sum(section_mask)) < 24:
        report.update({
            "status": "rejected",
            "reason": "排除两端轴向安装段后，管体截面证据不足",
            "evidence_request": {
                "required": True,
                "message": "请只在扶手管体表面补少量绿色标记；无需增加红色安装面",
            },
        })
        return None, report
    cross_points = np.column_stack((
        offsets @ plane_normal,
        np.sum(offsets * in_plane, axis=1),
    ))[section_mask]
    section_center, enclosing_radius = minimum_enclosing_circle(cross_points)

    clearance = max(0.0, float(scene.smrn_handle_clearance))
    requested_radius = max(0.0, float(scene.smrn_handle_min_diameter) * 0.5)
    preliminary_radius = max(enclosing_radius + clearance, requested_radius)
    # A marked seed can be a long triangulation bridge welded from the handle
    # into the vehicle shell. Its centroid is locally valid, while one remote
    # vertex can lie beyond the endpoint. A swept tube of the measured radius
    # cannot occupy |u| > half_span + radius, so that exact geometric bound
    # separates the bridge tail without using a hand-tuned width multiplier.
    endpoint_margin = preliminary_radius
    topology_bridge = np.abs(local_dense[:, 0]) > fit.half_span + endpoint_margin
    if np.any(topology_bridge):
        keep = ~topology_bridge
        dense = dense[keep]
        sample_areas = sample_areas[keep]
        sample_owners = [owner for owner, retained in zip(sample_owners, keep) if retained]
        local_dense = local_dense[keep]
        terminal_extension = terminal_extension[keep]
        section_mask = section_mask[keep]
    discarded_topology_bridge_samples = raw_semantic_samples - int(len(dense))
    if len(dense) < 24:
        report.update({
            "status": "rejected",
            "reason": "排除与车体相连的长三角桥接后，局部管体证据不足",
        })
        return None, report

    def shifted_path(endpoint_penetrations):
        raw = path_points_world(fit, path_segments, endpoint_penetrations)
        _frame_tangents, frame_in_plane = _path_vertex_frames(raw, plane_normal)
        return raw + plane_normal * section_center[0] + frame_in_plane * section_center[1]

    penetrations, endpoint_evidence = _support_penetrations(
        scene, supports, fit, preliminary_radius
    )
    path = shifted_path(penetrations)
    start_tangent = path[1] - path[0]
    start_tangent /= max(float(np.linalg.norm(start_tangent)), 1.0e-12)
    end_tangent = path[-1] - path[-2]
    end_tangent /= max(float(np.linalg.norm(end_tangent)), 1.0e-12)
    start_deficit = max(
        0.0, float(np.max(-((dense - path[0]) @ start_tangent)))
    )
    end_deficit = max(
        0.0, float(np.max((dense - path[-1]) @ end_tangent))
    )
    cap_margin = max(1.0e-5, preliminary_radius * 1.0e-4)
    penetrations = (
        float(penetrations[0] + start_deficit + (cap_margin if start_deficit else 0.0)),
        float(penetrations[1] + end_deficit + (cap_margin if end_deficit else 0.0)),
    )
    path = shifted_path(penetrations)
    endpoint_coverage_extension = {
        "start": start_deficit,
        "end": end_deficit,
        "margin": cap_margin,
    }
    _coverage_nearest, _coverage_tangents, source_distances = polyline_nearest(dense, path)
    source_radius = float(np.max(source_distances))
    section_radius = max(source_radius + clearance, requested_radius)
    section_segments = max(8, int(scene.smrn_handle_section_segments))
    containment_iterations = []
    for iteration in range(6):
        vertices, faces = _candidate_geometry(
            path, fit.plane_normal, section_radius, section_radius, section_segments
        )
        containment_tolerance = max(1.0e-7, section_radius * 1.0e-6)
        containment = _mesh_containment(
            vertices, faces, dense, sample_areas, sample_owners,
            containment_tolerance,
        )
        containment_iterations.append({
            "iteration": iteration,
            "radius": float(section_radius),
            "outside": containment["outside"],
            "max_signed": containment["max_signed"],
        })
        if containment["passed"]:
            break
        # Compensate the measured polygon-shell deficit. The cosine converts
        # radial vertex movement to the minimum face-normal movement of the
        # regular section; repeated measured checks also cover bend chords.
        projection = max(float(np.cos(np.pi / section_segments)), 0.80)
        if iteration < 5:
            section_radius += (
                max(0.0, containment["max_signed"]) + containment_tolerance * 2.0
            ) / projection
    topology = _topology(vertices, faces)
    coverage_tolerance = max(1.0e-8, section_radius * 1.0e-7)
    uncovered_mask = source_distances > section_radius + coverage_tolerance
    uncovered = int(np.sum(uncovered_mask))
    clearances = section_radius - source_distances
    coverage = {
        "samples": int(len(dense)), "uncovered": uncovered,
        "uncovered_area": float(np.sum(sample_areas[uncovered_mask])),
        "semantic_faces": int(sum(len(values) for values in semantic_faces.values())),
        "marked_samples": int(len(marked_dense)),
        "discarded_semantic_samples": discarded_topology_bridge_samples,
        "path_bridge_samples": discarded_path_bridge_samples,
        "topology_bridge_samples": (
            discarded_topology_bridge_samples - discarded_path_bridge_samples
        ),
        "raw_semantic_samples": raw_semantic_samples,
        "anchor_corridor": float(corridor),
        "endpoint_span_margin": float(endpoint_margin),
        "terminal_extension_samples": int(np.sum(terminal_extension)),
        "section_samples": int(np.sum(section_mask)),
        "section_center_offset": [float(value) for value in section_center],
        "minimum_enclosing_radius": float(enclosing_radius),
        "normal_radius": section_radius, "in_plane_radius": section_radius,
        "clearance_min": float(np.min(clearances)),
        "clearance_median": float(np.median(clearances)),
        "clearance_p95": float(np.quantile(clearances, 0.95)),
        "clearance_max": float(np.max(clearances)),
        "passed": uncovered == 0,
    }
    coverage["mesh_containment"] = containment
    coverage["mesh_containment_iterations"] = containment_iterations
    coverage["passed"] = coverage["passed"] and containment["passed"]
    source_unchanged = source_snapshot(source)["fingerprint"] == fingerprint_before
    evidence_unchanged = all(
        bpy.data.objects.get(name) is not None
        and source_snapshot(bpy.data.objects[name])["fingerprint"] == fingerprint
        for name, fingerprint in evidence_before.items()
    )
    report.update({
        "status": "candidate_ready", "coverage_qa": coverage,
        "semantic_expansion": semantic_diagnostics,
        "endpoint_qa": endpoint_evidence, "endpoint_penetrations": list(penetrations),
        "endpoint_coverage_extension": endpoint_coverage_extension,
        "topology_qa": topology, "source_unchanged": source_unchanged,
        "evidence_sources_unchanged": evidence_unchanged,
        "frame_qa": {
            "shared_leg_axis": True,
            "span_rise_dot": abs(float(np.dot(fit.span_axis, fit.rise_axis))),
            "span_normal_dot": abs(float(np.dot(fit.span_axis, fit.plane_normal))),
            "rise_normal_dot": abs(float(np.dot(fit.rise_axis, fit.plane_normal))),
            "plane_thickness_ratio": fit.plane_thickness_ratio,
            "passed": fit.status == "candidate_ready",
        },
    })
    if not topology["passed"] or not coverage["passed"] or not source_unchanged or not evidence_unchanged:
        report.update({"status": "rejected", "reason": "handle candidate failed topology, coverage, or source immutability QA"})
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
    obj["smrn_handle_section_segments"] = section_segments
    obj["smrn_handle_thickness_scale"] = 1.0
    obj["smrn_source_name"] = source.name
    obj["smrn_handle_report_json"] = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    _commit_candidate(scene, obj)
    scene["smrn_handle_last_report_json"] = obj["smrn_handle_report_json"]
    return obj, report


def store_analysis(scene, report):
    scene["smrn_handle_last_report_json"] = json.dumps(
        report, ensure_ascii=False, separators=(",", ":")
    )
