"""Read-only diagnostics for the current marked grab-handle path fit."""

import json

import bpy
import numpy as np

from semantic_mesh_marker_next.handle_blender import _current_anchor, _marked_edge_radius, _records
from semantic_mesh_marker_next.handle_fit import _canonical, _fit_path, _principal, fit_handle


targets, excludes = _records(bpy.context.scene)
anchors = [_current_anchor(item) for item in targets]
points = np.asarray([tuple(value[0]) for value in anchors], dtype=float)
normals = np.asarray([tuple(value[1]) for value in anchors], dtype=float)
normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1.0e-12)
radius_hint = _marked_edge_radius(targets)
medial = points - normals * radius_hint
values, vectors = _principal(medial)
raw_span = _canonical(vectors[:, -1])
plane = _canonical(vectors[:, 0])
span = _canonical(raw_span - plane * float(raw_span @ plane))
rise = np.cross(plane, span)
rise /= max(float(np.linalg.norm(rise)), 1.0e-12)
centroid = np.mean(medial, axis=0)

candidates = []
for sign in (1.0, -1.0):
    this_rise = rise * sign
    this_plane = plane * sign
    relative = medial - centroid
    local = np.column_stack((relative @ span, relative @ this_rise))
    model = _fit_path(local, radius_hint)
    u = local[:, 0]
    v = local[:, 1]
    minimum_u, maximum_u = np.quantile(u, (0.04, 0.96))
    half_span = float((maximum_u - minimum_u) * 0.5)
    centered_u = u - (minimum_u + maximum_u) * 0.5
    terminals = np.abs(centered_u) >= half_span * 0.62
    middle = np.abs(centered_u) <= half_span * 0.58
    candidates.append({
        "sign": sign,
        "rise": this_rise.tolist(),
        "plane": this_plane.tolist(),
        "terminal_count": int(np.sum(terminals)),
        "middle_count": int(np.sum(middle)),
        "terminal_v_q10": float(np.quantile(v[terminals], 0.10)) if np.any(terminals) else None,
        "middle_v_q90": float(np.quantile(v[middle], 0.90)) if np.any(middle) else None,
        "model": None if model is None else {
            key: value for key, value in model.items() if key != "residual"
        },
    })

edge_points = []
edge_normals = []
face_edge_points = []
face_edge_normals = []
seen_edges = set()
seen_face_edges = set()
spacing = max(radius_hint * 0.75, 1.0e-4)
for record in targets:
    obj = bpy.data.objects.get(record.hit_object_name) or bpy.data.objects.get(record.source_object_name)
    if obj is None or obj.type != "MESH" or not 0 <= record.face_index < len(obj.data.polygons):
        continue
    polygon = obj.data.polygons[record.face_index]
    normal_matrix = obj.matrix_world.to_3x3().inverted_safe().transposed()
    face_normal = (normal_matrix @ polygon.normal).normalized()
    for first, second in polygon.edge_keys:
        key = (obj.name, min(first, second), max(first, second))
        if key in seen_edges:
            continue
        seen_edges.add(key)
        a = obj.matrix_world @ obj.data.vertices[first].co
        b = obj.matrix_world @ obj.data.vertices[second].co
        na = normal_matrix @ obj.data.vertices[first].normal
        nb = normal_matrix @ obj.data.vertices[second].normal
        steps = max(1, min(64, int(np.ceil((a - b).length / spacing))))
        for index in range(steps + 1):
            factor = index / steps
            point = a.lerp(b, factor)
            normal = na.lerp(nb, factor).normalized()
            edge_points.append(tuple(point))
            edge_normals.append(tuple(normal))
        face_key = (obj.name, int(record.face_index), min(first, second), max(first, second))
        if face_key not in seen_face_edges:
            seen_face_edges.add(face_key)
            for index in range(steps + 1):
                factor = index / steps
                face_edge_points.append(tuple(a.lerp(b, factor)))
                face_edge_normals.append(tuple(face_normal))

edge_fit = fit_handle(edge_points, edge_normals, radius_hint=radius_hint)
face_edge_fit = fit_handle(face_edge_points, face_edge_normals, radius_hint=radius_hint)

click_medial = points - normals * radius_hint
click_values, click_vectors = _principal(click_medial)
click_span = _canonical(click_vectors[:, -1])
click_u = (click_medial - np.mean(click_medial, axis=0)) @ click_span
middle_index = int(np.argmin(np.abs(click_u)))
augmented_points = np.vstack((points, points[middle_index] + click_span * radius_hint * 0.05))
augmented_normals = np.vstack((normals, normals[middle_index]))
augmented_fit = fit_handle(augmented_points, augmented_normals, radius_hint=radius_hint)

edge_medial = np.asarray(edge_points) - np.asarray(edge_normals) * radius_hint
edge_origin = np.asarray(edge_fit.origin)
edge_span = np.asarray(edge_fit.span_axis)
edge_rise = np.asarray(edge_fit.rise_axis)
edge_local = np.column_stack(((edge_medial - edge_origin) @ edge_span,
                              (edge_medial - edge_origin) @ edge_rise))
bin_rows = []
limits = np.linspace(float(np.min(edge_local[:, 0])), float(np.max(edge_local[:, 0])), 13)
for lower, upper in zip(limits[:-1], limits[1:]):
    mask = (edge_local[:, 0] >= lower) & (edge_local[:, 0] <= upper)
    if not np.any(mask):
        continue
    values_in_bin = edge_local[mask, 1]
    bin_rows.append([float((lower + upper) * 0.5), int(np.sum(mask)),
                     float(np.quantile(values_in_bin, 0.1)),
                     float(np.quantile(values_in_bin, 0.5)),
                     float(np.quantile(values_in_bin, 0.9))])

print("SMRN_HANDLE_PATH_DIAG=" + json.dumps({
    "target_count": len(targets),
    "exclude_count": len(excludes),
    "radius_hint": radius_hint,
    "medial_pca_values": values.tolist(),
    "raw_span": raw_span.tolist(),
    "plane": plane.tolist(),
    "longitudinal_ratio": float(values[-1] / max(values[-2], 1.0e-12)),
    "point_bounds": [np.min(points, axis=0).tolist(), np.max(points, axis=0).tolist()],
    "medial_bounds": [np.min(medial, axis=0).tolist(), np.max(medial, axis=0).tolist()],
    "candidates": candidates,
    "edge_sample_count": len(edge_points),
    "edge_fit": edge_fit.to_dict(),
    "face_edge_sample_count": len(face_edge_points),
    "face_edge_fit": face_edge_fit.to_dict(),
    "augmented_middle_index": middle_index,
    "augmented_fit": augmented_fit.to_dict(),
    "edge_local_bins_u_count_vq10_vq50_vq90": bin_rows,
}, ensure_ascii=False, separators=(",", ":")))
