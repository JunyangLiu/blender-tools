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
from .rotational_fit import (
    RotationalFit,
    fit_rotational_boundary_rings,
    fit_rotational_surface,
)
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
    face_indices = _target_face_indices(source, targets)
    fit, topology = _fit_marked_face_strip(source, face_indices)
    return fit, source, targets, excludes, {"source": snapshot, "axis_evidence": topology}


def _selected_weld_frame(source, face_indices):
    """Build scale-derived virtual vertex keys without modifying the source."""
    vertex_ids = {
        int(vertex)
        for face_index in face_indices
        for vertex in source.data.polygons[int(face_index)].vertices
    }
    world = {
        vertex: np.asarray(tuple(source.matrix_world @ source.data.vertices[vertex].co), dtype=float)
        for vertex in vertex_ids
    }
    lengths = []
    for face_index in face_indices:
        for first, second in source.data.polygons[int(face_index)].edge_keys:
            lengths.append(float(np.linalg.norm(world[first] - world[second])))
    typical = float(np.median([value for value in lengths if value > 1.0e-10]))
    tolerance = max(1.0e-7, typical * 1.0e-5)
    keys = {
        vertex: tuple(int(round(value / tolerance)) for value in point)
        for vertex, point in world.items()
    }
    points = defaultdict(list)
    for vertex, key in keys.items():
        points[key].append(world[vertex])
    key_points = {key: np.mean(rows, axis=0) for key, rows in points.items()}
    return keys, key_points, tolerance, len(vertex_ids) - len(key_points)


def _face_components(source, face_indices, vertex_keys=None):
    """Return selected-face components, virtually welding coincident seams."""
    selected = {int(index) for index in face_indices}
    if vertex_keys is None:
        vertex_keys, _points, _tolerance, _collapsed = _selected_weld_frame(source, selected)
    edge_faces = defaultdict(list)
    for face_index in selected:
        for edge in source.data.polygons[face_index].edge_keys:
            key = tuple(sorted((vertex_keys[edge[0]], vertex_keys[edge[1]])))
            edge_faces[key].append(face_index)
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
    fit, axis_evidence = _fit_marked_face_strip(source, indices)
    return fit, {
        "source": source_snapshot(source),
        "axis_evidence": axis_evidence,
        "selection_qa": {
            "selection_method": "exact_edit_mode_faces",
            "selected_faces": len(indices),
            "connected_components": len(components),
            "whole_vehicle_search": False,
            "passed": len(components) == 1,
        },
    }


def _ordered_boundary_component(edges):
    adjacency = defaultdict(set)
    for first, second in edges:
        adjacency[first].add(second)
        adjacency[second].add(first)
    if any(len(linked) > 2 for linked in adjacency.values()):
        raise ValueError("标记边界存在分叉，无法作为单一圆柱或圆锥处理")
    endpoints = sorted(vertex for vertex, linked in adjacency.items() if len(linked) == 1)
    if len(endpoints) not in (0, 2):
        raise ValueError("标记边界不是连续圆周链")
    start = endpoints[0] if endpoints else min(adjacency)
    ordered = [start]
    previous = None
    current = start
    while True:
        choices = sorted(adjacency[current] - ({previous} if previous is not None else set()))
        if not choices:
            break
        following = choices[0]
        if following == start:
            break
        if following in ordered:
            raise ValueError("标记边界包含自交回路")
        ordered.append(following)
        previous, current = current, following
    if len(ordered) != len(adjacency):
        raise ValueError("标记边界链不连续")
    return ordered


def _boundary_ring_vertex_chains(source, face_indices, vertex_keys, key_points):
    """Extract two circumferential chains from only the marked face strip."""
    edge_counts = defaultdict(int)
    for face_index in face_indices:
        for edge in source.data.polygons[face_index].edge_keys:
            key = tuple(sorted((vertex_keys[edge[0]], vertex_keys[edge[1]])))
            edge_counts[key] += 1
    boundary = {edge for edge, count in edge_counts.items() if count == 1}
    if len(boundary) < 8:
        raise ValueError("至少需要两条各含 4 个点的圆周边界")

    def components(edges):
        adjacency = defaultdict(set)
        for first, second in edges:
            adjacency[first].add(second)
            adjacency[second].add(first)
        remaining = set(adjacency)
        result = []
        while remaining:
            seed = remaining.pop()
            vertices = {seed}
            queue = deque((seed,))
            while queue:
                current = queue.popleft()
                for other in adjacency[current] & remaining:
                    remaining.remove(other)
                    vertices.add(other)
                    queue.append(other)
            result.append({edge for edge in edges if edge[0] in vertices and edge[1] in vertices})
        return result

    groups = components(boundary)
    separator_edges = set()
    if len(groups) == 1:
        lengths = []
        for edge in boundary:
            first, second = key_points[edge[0]], key_points[edge[1]]
            lengths.append((float(np.linalg.norm(second - first)), edge))
        lengths.sort(reverse=True)
        typical = float(np.median([value for value, _edge in lengths]))
        if len(lengths) < 4 or lengths[1][0] < max(typical * 1.45, lengths[2][0] * 1.35):
            raise ValueError("无法从标记带区分上下圆周边与两端轴向边；已拒绝猜测轴线")
        separator_edges = {lengths[0][1], lengths[1][1]}
        groups = components(boundary - separator_edges)
    if len(groups) != 2:
        raise ValueError("标记区域必须形成上下两条连续圆周边界")
    ordered = [_ordered_boundary_component(group) for group in groups]
    if min(len(chain) for chain in ordered) < 4:
        raise ValueError("每条圆周边界至少需要 4 个源顶点")
    rings = [[tuple(float(value) for value in key_points[key]) for key in chain] for chain in ordered]
    return rings, separator_edges, len(boundary)


def _broad_arc_island_rings(key_points):
    """Recover two rings from disconnected islands only with broad arc evidence."""
    points = np.asarray(tuple(key_points.values()), dtype=float)
    if len(points) < 8:
        raise ValueError("断续绿色面至少需要 8 个唯一空间顶点")
    center = np.mean(points, axis=0)
    centered = points - center
    values, vectors = np.linalg.eigh(centered.T @ centered / len(points))
    if values[1] / max(values[0], 1.0e-12) < 12.0:
        raise ValueError("断续标记没有形成两层稳定圆周，已拒绝猜测轴线")
    axis = vectors[:, 0]
    axial = centered @ axis

    cluster_centers = np.asarray((float(np.min(axial)), float(np.max(axial))))
    labels = np.zeros(len(points), dtype=int)
    for _iteration in range(16):
        labels = np.argmin(np.abs(axial[:, None] - cluster_centers[None, :]), axis=1)
        if len(set(labels.tolist())) != 2:
            raise ValueError("无法把断续标记分成上下两层圆周")
        updated = np.asarray([float(np.mean(axial[labels == index])) for index in range(2)])
        if np.max(np.abs(updated - cluster_centers)) <= 1.0e-10:
            break
        cluster_centers = updated
    separation = abs(float(cluster_centers[1] - cluster_centers[0]))
    scatter = float(np.quantile(np.abs(axial - cluster_centers[labels]), 0.90))
    if separation <= 1.0e-8 or scatter > separation * 0.10:
        raise ValueError("断续标记的上下圆周层不够平直，不能安全合并")

    axis /= max(float(np.linalg.norm(axis)), 1.0e-12)
    helper = np.asarray((1.0, 0.0, 0.0))
    if abs(float(helper @ axis)) > 0.85:
        helper = np.asarray((0.0, 0.0, 1.0))
    basis_x = np.cross(axis, helper)
    basis_x /= max(float(np.linalg.norm(basis_x)), 1.0e-12)
    basis_y = np.cross(axis, basis_x)

    rings = []
    spans = []
    for index in range(2):
        rows = points[labels == index]
        if len(rows) < 4:
            raise ValueError("每层断续圆周至少需要 4 个唯一顶点")
        relative = rows - center
        angles = np.mod(np.arctan2(relative @ basis_y, relative @ basis_x), 2.0 * math.pi)
        order = np.argsort(angles)
        ordered_angles = angles[order]
        gaps = np.diff(np.r_[ordered_angles, ordered_angles[0] + 2.0 * math.pi])
        span = float(2.0 * math.pi - np.max(gaps))
        if span < math.radians(160.0):
            raise ValueError("断续标记圆周跨度不足 160°，请补充两侧绿色面")
        rings.append([tuple(float(value) for value in row) for row in rows[order]])
        spans.append(math.degrees(span))
    return rings, {
        "method": "broad_arc_two_plane_island_merge",
        "pca_values": [float(value) for value in values],
        "ring_plane_separation": separation,
        "ring_plane_scatter_p90": scatter,
        "ring_angular_spans_degrees": spans,
    }


def _fit_marked_face_strip(source, face_indices):
    indices = {int(index) for index in face_indices}
    if len(indices) < 4:
        raise ValueError("至少需要 4 个实际源面，重复刷点不会增加轴线证据")
    vertex_keys, key_points, weld_tolerance, collapsed_vertices = _selected_weld_frame(
        source, indices
    )
    components = _face_components(source, indices, vertex_keys=vertex_keys)
    if len(components) == 1:
        rings, separators, boundary_count = _boundary_ring_vertex_chains(
            source, indices, vertex_keys, key_points
        )
        island_evidence = {"method": "two_source_boundary_rings"}
    else:
        rings, island_evidence = _broad_arc_island_rings(key_points)
        separators = set()
        boundary_count = 0
    points, normals = [], []
    for face_index in sorted(indices):
        polygon = source.data.polygons[face_index]
        points.append(tuple(source.matrix_world @ polygon.center))
        normals.append(tuple(_world_normal(source, polygon.normal)))
    fit = fit_rotational_boundary_rings(rings[0], rings[1], points, normals)
    evidence = {
        **island_evidence,
        "unique_mark_faces": len(indices),
        "source_face_islands": len(components),
        "island_merge_applied": len(components) > 1,
        "ring_vertex_counts": [len(ring) for ring in rings],
        "virtual_weld_tolerance": weld_tolerance,
        "coincident_vertices_collapsed": collapsed_vertices,
        "source_mesh_modified": False,
        "boundary_edges": boundary_count,
        "axial_separator_edges": len(separators),
        "whole_vehicle_search": False,
    }
    return fit, evidence


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
    # Preserve the calibrated visible envelope and add a useful structural
    # backing only on the material/centre side.  The old preview shell used
    # one percent of the feature scale and was effectively a membrane on
    # vehicle-sized rings.  Bound the backing from both the local axial span
    # and radius so it scales with this marked part without swallowing the
    # opening or borrowing a fixed dimension from another model.
    feature_scale = min(max(radius, 1.0e-5), axial_span)
    return max(1.0e-5, min(radius * 0.04, feature_scale * 0.18))


def _ring_point(fit, axial, angle, radius):
    origin, axis, basis_x, basis_y = _fit_frame(fit)
    return origin + axis * axial + radius * (math.cos(angle) * basis_x + math.sin(angle) * basis_y)


def _envelope_profile(fit, points, axial_min, axial_max, extra_clearance=0.0,
                      requested_knots=12):
    """Build a smooth local radial envelope instead of one global clearance.

    Every dense source sample is covered, but a local protrusion only raises
    neighboring axial rings.  The one-sided smoothing step fills narrow dents
    without sanding down peaks that are required for source coverage.
    """
    axial, radius, _angle = _coordinates(points, fit)
    predicted = np.abs(fit.signed_radius_at_origin + fit.signed_slope * axial)
    residual = radius - predicted if fit.surface_side == "outer" else predicted - radius
    span = max(float(axial_max - axial_min), 1.0e-8)
    knot_count = max(4, min(int(requested_knots), max(4, len(points))))
    knots = np.linspace(axial_min, axial_max, knot_count)
    step = span / max(knot_count - 1, 1)
    values = np.empty(knot_count, dtype=float)
    for index, knot in enumerate(knots):
        distance = np.abs(axial - knot)
        local = residual[distance <= step * 1.05]
        values[index] = float(np.max(local)) if len(local) else float(residual[np.argmin(distance)])

    # Raise valleys only. Required peaks never move inward.
    for _iteration in range(3):
        neighbor = values.copy()
        neighbor[1:-1] = 0.25 * values[:-2] + 0.5 * values[1:-1] + 0.25 * values[2:]
        values = np.maximum(values, neighbor)

    # Piecewise-linear candidate must cover every dense triangle sample.
    for _iteration in range(4):
        interpolated = np.interp(axial, knots, values)
        deficit = residual - interpolated
        if float(np.max(deficit)) <= 1.0e-8:
            break
        for sample_axial, amount in zip(axial, deficit):
            if amount <= 0.0:
                continue
            right = int(np.searchsorted(knots, sample_axial, side="right"))
            right = min(max(right, 1), knot_count - 1)
            left = right - 1
            values[left] += float(amount) + 1.0e-8
            values[right] += float(amount) + 1.0e-8
    values += max(0.0, float(extra_clearance))
    return knots, values


def _analytic_envelope_profile(fit, points, axial_min, axial_max, extra_clearance=0.0):
    """Return the tightest fitted affine correction that covers every sample.

    A cylinder/cone must remain analytic along its axis.  Following individual
    low-poly triangles with many clearance rings creates visible annular
    ripples, so only an intercept and slope correction are allowed here.
    """
    axial, radius, _angle = _coordinates(points, fit)
    predicted = np.abs(fit.signed_radius_at_origin + fit.signed_slope * axial)
    residual = radius - predicted if fit.surface_side == "outer" else predicted - radius
    centered = axial - float(np.mean(axial))
    denominator = float(centered @ centered)
    slope = 0.0 if denominator <= 1.0e-12 else float(centered @ residual) / denominator
    intercept = float(np.max(residual - slope * axial)) + max(0.0, float(extra_clearance))
    knots = np.asarray((axial_min, axial_max), dtype=float)
    values = intercept + slope * knots
    return knots, values


def _profile_clearance(axial, knots, values):
    return np.interp(axial, np.asarray(knots, dtype=float), np.asarray(values, dtype=float))


def _candidate_geometry(fit, axial_knots, profile_clearance, angle_start, angle_span,
                        thickness, requested_segments):
    full = angle_span >= 2.0 * math.pi - 1.0e-7
    segments = max(12, int(round(requested_segments * angle_span / (2.0 * math.pi))))
    if full:
        segments = max(32, requested_segments)
        angles = [angle_start + angle_span * index / segments for index in range(segments)]
    else:
        angles = [angle_start + angle_span * index / segments for index in range(segments + 1)]
    ring_pairs = []
    vertices = []
    for axial, clearance in zip(axial_knots, profile_clearance):
        base_radius = fit.radius_at_axial(axial)
        if fit.surface_side == "outer":
            visible_radius = base_radius + clearance
            radii = (visible_radius, max(1.0e-5, visible_radius - thickness))
        else:
            visible_radius = max(1.0e-5, base_radius - clearance)
            radii = (visible_radius, visible_radius + thickness)
        pair = []
        for radius in radii:
            ring = []
            for angle in angles:
                ring.append(len(vertices))
                vertices.append(tuple(float(value) for value in _ring_point(fit, axial, angle, radius)))
            pair.append(ring)
        ring_pairs.append(pair)

    faces = []
    smooth_faces = []
    pair_count = len(angles) if full else len(angles) - 1
    def connect(first, second, reverse=False, smooth=False):
        for index in range(pair_count):
            following = (index + 1) % len(angles)
            face = (first[index], first[following], second[following], second[index])
            faces.append(tuple(reversed(face)) if reverse else face)
            if smooth:
                smooth_faces.append(len(faces) - 1)
    # Visible and backing skins for every axial interval, then axial caps.
    for first, second in zip(ring_pairs, ring_pairs[1:]):
        connect(first[0], second[0], reverse=(fit.surface_side == "inner"), smooth=True)
        connect(first[1], second[1], reverse=(fit.surface_side != "inner"), smooth=True)
    connect(ring_pairs[0][0], ring_pairs[0][1], reverse=True)
    connect(ring_pairs[-1][0], ring_pairs[-1][1], reverse=False)
    if not full:
        for first, second in zip(ring_pairs, ring_pairs[1:]):
            faces.append((first[0][0], second[0][0], second[1][0], first[1][0]))
            faces.append((first[0][-1], first[1][-1], second[1][-1], second[0][-1]))
    return vertices, faces, segments, smooth_faces


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


def _coverage_report(fit, points, axial_min, axial_max, angle_start, angle_span,
                     axial_knots, profile_clearance):
    axial, radius, angle = _coordinates(points, fit)
    angular = _angle_offset(angle, angle_start)
    full = angle_span >= 2.0 * math.pi - 1.0e-7
    in_angle = np.ones(len(points), dtype=bool) if full else angular <= angle_span + 1e-7
    in_axial = (axial >= axial_min - 1e-7) & (axial <= axial_max + 1e-7)
    predicted = np.abs(fit.signed_radius_at_origin + fit.signed_slope * axial)
    clearance = _profile_clearance(axial, axial_knots, profile_clearance)
    if fit.surface_side == "outer":
        overshoot = radius - (predicted + clearance)
    else:
        overshoot = (predicted - clearance) - radius
    gap = -overshoot
    covered = in_angle & in_axial & (overshoot <= 1e-6)
    return {"samples": len(points), "uncovered": int(np.sum(~covered)),
            "maximum_overshoot": float(max(0.0, np.max(overshoot))) if len(points) else 0.0,
            "median_visible_gap": float(max(0.0, np.median(gap))) if len(points) else 0.0,
            "p90_visible_gap": float(max(0.0, np.quantile(gap, 0.90))) if len(points) else 0.0,
            "maximum_visible_gap": float(max(0.0, np.max(gap))) if len(points) else 0.0,
            "passed": bool(np.all(covered))}


def _required_clearance(fit, points):
    if not points:
        return 0.0
    axial, radius, _angle = _coordinates(points, fit)
    predicted = np.abs(fit.signed_radius_at_origin + fit.signed_slope * axial)
    residual = radius - predicted if fit.surface_side == "outer" else predicted - radius
    return max(0.0, float(np.max(residual)))


def _exclude_report(fit, source, excludes, axial_min, axial_max, angle_start, angle_span,
                    axial_knots, profile_clearance, thickness):
    relevant = [item for item in excludes if item.source_object_name == source.name]
    if not relevant:
        return {"samples": 0, "conflicts": 0, "passed": True}
    points = [tuple(_current_anchor(item, source)[0]) for item in relevant]
    axial, radius, angle = _coordinates(points, fit)
    angular = _angle_offset(angle, angle_start)
    full = angle_span >= 2.0 * math.pi - 1.0e-7
    in_angle = np.ones(len(points), dtype=bool) if full else angular <= angle_span + 1e-7
    in_axial = (axial >= axial_min) & (axial <= axial_max)
    predicted = np.abs(fit.signed_radius_at_origin + fit.signed_slope * axial)
    clearance = _profile_clearance(axial, axial_knots, profile_clearance)
    if fit.surface_side == "outer":
        radial_hit = (radius >= predicted + clearance - thickness) & (radius <= predicted + clearance)
    else:
        radial_hit = (radius >= predicted - clearance) & (radius <= predicted - clearance + thickness)
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
    axial_knots, profile_clearance = _analytic_envelope_profile(
        fit, dense, axial_min, axial_max,
        extra_clearance=float(scene.smrn_rotational_clearance),
    )
    requested_thickness = float(scene.smrn_rotational_thickness)
    thickness = requested_thickness
    if thickness <= 0.0:
        thickness = _auto_thickness(fit, axial_min, axial_max)
    coverage = _coverage_report(
        fit, dense, axial_min, axial_max, angle_start, angle_span,
        axial_knots, profile_clearance,
    )
    excludes_report = _exclude_report(
        fit, source, excludes, axial_min, axial_max, angle_start, angle_span,
        axial_knots, profile_clearance, thickness
    )
    vertices, faces, segments, smooth_faces = _candidate_geometry(
        fit, axial_knots, profile_clearance, angle_start, angle_span,
        thickness, int(scene.smrn_rotational_segments),
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
                   "clearance_mode": "analytic_affine_outer_envelope",
                   "legacy_global_clearance": fitted_clearance,
                   "clearance_min": float(np.min(profile_clearance)),
                   "clearance_max": float(np.max(profile_clearance)),
                   "axial_profile_rings": len(axial_knots),
                   "thickness": thickness,
                   "thickness_mode": ("auto_inward_structural_backing"
                                      if requested_thickness <= 0.0 else "explicit"),
                   "visible_surface_preserved": True,
                   "backing_direction": ("toward_axis" if fit.surface_side == "outer"
                                         else "away_from_axis_into_material"),
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
    smooth_face_set = set(smooth_faces)
    for polygon in mesh.polygons:
        polygon.use_smooth = polygon.index in smooth_face_set
    obj = bpy.data.objects.new(f"{CANDIDATE_PREFIX}{fit.profile_kind.upper()}", mesh)
    candidates.objects.link(obj)
    obj.display_type = "SOLID"
    obj.color = (0.04, 0.55, 1.0, 0.72)
    obj.show_wire = False
    obj.show_all_edges = False
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
    """Build from the exact green-marked strip without scanning the vehicle."""
    fit, source, targets, excludes, context_report = analyze_scene(scene)
    if fit.status != "candidate_ready" or source is None:
        return _build_candidate(
            scene, fit, source, targets, excludes, context_report, set(), {}, "semantic_marks"
        )
    surface_faces = _target_face_indices(source, targets)
    expansion = {
        "selection_method": "exact_green_mark_faces",
        "seed_faces": len(surface_faces),
        "surface_faces": len(surface_faces),
        "expanded_faces": 0,
        "whole_vehicle_search": False,
    }
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
