"""Audit only the explicitly marked source faces for rotational geometry."""

import json
import math
from collections import Counter

import bpy
import numpy as np
from mathutils import Vector

from semantic_mesh_marker_next.constants import TARGET_ROLE
from semantic_mesh_marker_next.storage import load_all_marks


scene = bpy.context.scene
records = [item for item in load_all_marks(scene) if item.role == TARGET_ROLE]
source_names = {item.source_object_name for item in records}
source = bpy.data.objects.get(next(iter(source_names))) if len(source_names) == 1 else None
if source is None or source.type != "MESH":
    raise RuntimeError("marked source is missing or ambiguous")

face_ids = sorted({int(item.face_index) for item in records})
matrix = source.matrix_world
normal_matrix = matrix.to_3x3().inverted_safe().transposed()

vertex_ids = sorted({vid for fid in face_ids for vid in source.data.polygons[fid].vertices})
points = np.asarray([tuple(matrix @ source.data.vertices[vid].co) for vid in vertex_ids], dtype=float)
center = points.mean(axis=0)

rows = []
edge_counts = Counter()
edge_vectors = {}
normals = []
weights = []
for fid in face_ids:
    face = source.data.polygons[fid]
    normal = normal_matrix @ face.normal
    normal.normalize()
    world_vertices = [matrix @ source.data.vertices[vid].co for vid in face.vertices]
    area = 0.0
    if len(world_vertices) >= 3:
        anchor = world_vertices[0]
        area = sum(
            0.5 * (world_vertices[index] - anchor).cross(world_vertices[index + 1] - anchor).length
            for index in range(1, len(world_vertices) - 1)
        )
    normals.append(tuple(normal))
    weights.append(max(area, 1.0e-9))
    rows.append({
        "face": fid,
        "vertices": list(face.vertices),
        "center": [round(value, 6) for value in tuple(matrix @ face.center)],
        "normal": [round(value, 6) for value in tuple(normal)],
        "area": round(area, 6),
    })
    for edge in face.edge_keys:
        key = tuple(sorted(edge))
        edge_counts[key] += 1
        a = matrix @ source.data.vertices[key[0]].co
        b = matrix @ source.data.vertices[key[1]].co
        edge_vectors[key] = np.asarray(tuple(b - a), dtype=float)


def canonical(direction):
    value = np.asarray(direction, dtype=float)
    value /= max(np.linalg.norm(value), 1.0e-12)
    pivot = int(np.argmax(np.abs(value)))
    return -value if value[pivot] < 0.0 else value


def cluster_edges():
    clusters = []
    for key, vector in sorted(edge_vectors.items(), key=lambda item: -np.linalg.norm(item[1])):
        length = float(np.linalg.norm(vector))
        if length <= 1.0e-9:
            continue
        direction = canonical(vector)
        for cluster in clusters:
            if abs(float(np.dot(direction, cluster["axis"]))) >= math.cos(math.radians(8.0)):
                cluster["vectors"].append(direction)
                cluster["lengths"].append(length)
                cluster["boundary"] += int(edge_counts[key] == 1)
                cluster["shared"] += int(edge_counts[key] > 1)
                aligned = [item if np.dot(item, cluster["axis"]) >= 0.0 else -item for item in cluster["vectors"]]
                cluster["axis"] = canonical(np.mean(aligned, axis=0))
                break
        else:
            clusters.append({
                "axis": direction,
                "vectors": [direction],
                "lengths": [length],
                "boundary": int(edge_counts[key] == 1),
                "shared": int(edge_counts[key] > 1),
            })
    return sorted(clusters, key=lambda item: (-len(item["vectors"]), -np.median(item["lengths"])))


normal_array = np.asarray(normals, dtype=float)
weight_array = np.asarray(weights, dtype=float)
weight_array /= weight_array.sum()
cov_points = (points - center).T @ (points - center) / max(len(points), 1)
point_values, point_vectors = np.linalg.eigh(cov_points)
normal_cov = (normal_array * weight_array[:, None]).T @ normal_array
normal_values, normal_vectors = np.linalg.eigh(normal_cov)
clusters = cluster_edges()

candidates = []
candidate_sources = []
for index in range(3):
    candidates.append(canonical(point_vectors[:, index]))
    candidate_sources.append(f"point_pca_{index}")
    candidates.append(canonical(normal_vectors[:, index]))
    candidate_sources.append(f"normal_null_{index}")
for index, cluster in enumerate(clusters[:8]):
    candidates.append(cluster["axis"])
    candidate_sources.append(f"edge_cluster_{index}")

scores = []
for source_label, axis in zip(candidate_sources, candidates):
    axial = (points - center) @ axis
    radial_vectors = (points - center) - axial[:, None] * axis[None, :]
    radii = np.linalg.norm(radial_vectors, axis=1)
    design = np.column_stack((np.ones(len(axial)), axial))
    coefficients, *_ = np.linalg.lstsq(design, radii, rcond=None)
    prediction = design @ coefficients
    profile_residual = float(np.quantile(np.abs(radii - prediction), 0.90))
    normal_axial = normal_array @ axis
    scores.append({
        "source": source_label,
        "axis": [round(value, 7) for value in axis.tolist()],
        "axial_span": round(float(np.ptp(axial)), 6),
        "radial_span": round(float(np.ptp(radii)), 6),
        "profile_p90": round(profile_residual, 6),
        "normal_axial_std": round(float(np.std(normal_axial)), 6),
        "normal_axial_mean": round(float(np.mean(normal_axial)), 6),
    })

payload = {
    "source": source.name,
    "mark_count": len(records),
    "unique_faces": len(face_ids),
    "unique_vertices": len(vertex_ids),
    "face_ids": face_ids,
    "point_center": [round(value, 6) for value in center.tolist()],
    "point_pca_values": [round(value, 7) for value in point_values.tolist()],
    "point_pca_axes": [[round(value, 7) for value in canonical(point_vectors[:, index]).tolist()] for index in range(3)],
    "normal_cov_values": [round(value, 7) for value in normal_values.tolist()],
    "normal_cov_axes": [[round(value, 7) for value in canonical(normal_vectors[:, index]).tolist()] for index in range(3)],
    "edge_clusters": [{
        "axis": [round(value, 7) for value in item["axis"].tolist()],
        "count": len(item["vectors"]),
        "median_length": round(float(np.median(item["lengths"])), 6),
        "min_length": round(float(np.min(item["lengths"])), 6),
        "max_length": round(float(np.max(item["lengths"])), 6),
        "boundary": item["boundary"],
        "shared": item["shared"],
    } for item in clusters[:12]],
    "boundary_edges": [{
        "vertices": list(key),
        "length": round(float(np.linalg.norm(edge_vectors[key])), 6),
        "direction": [round(value, 7) for value in canonical(edge_vectors[key]).tolist()],
    } for key in sorted(edge_counts) if edge_counts[key] == 1],
    "candidate_scores": scores,
    "faces": rows,
    "whole_vehicle_search": False,
}
print("SMRN_MARKED_GEOMETRY=" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
