"""Read-only audit for normal-derived rings on disconnected rotational marks."""

import json

import bpy
import numpy as np

from semantic_mesh_marker_next.constants import TARGET_ROLE
from semantic_mesh_marker_next.rotational_blender import (
    _selected_weld_frame,
    _source_for_targets,
    _task_records,
    _world_normal,
)


scene = bpy.context.scene
targets, _excludes = _task_records(scene)
source, _snapshot = _source_for_targets(scene, targets)
face_indices = {
    int(item.face_index) for item in targets
    if item.role == TARGET_ROLE and 0 <= int(item.face_index) < len(source.data.polygons)
}
_vertex_keys, key_points, _tolerance, _collapsed = _selected_weld_frame(source, face_indices)
points = np.asarray(tuple(key_points.values()), dtype=float)
normals = np.asarray([
    tuple(_world_normal(source, source.data.polygons[index].normal))
    for index in sorted(face_indices)
], dtype=float)

normal_values, normal_vectors = np.linalg.eigh(normals.T @ normals / len(normals))
axis = normal_vectors[:, 0]
axis /= np.linalg.norm(axis)
center = np.mean(points, axis=0)
axial = (points - center) @ axis

cluster_centers = np.asarray((float(np.min(axial)), float(np.max(axial))))
for _iteration in range(32):
    labels = np.argmin(np.abs(axial[:, None] - cluster_centers[None, :]), axis=1)
    updated = np.asarray([
        float(np.mean(axial[labels == index])) for index in range(2)
    ])
    if np.max(np.abs(updated - cluster_centers)) <= 1.0e-10:
        break
    cluster_centers = updated

separation = abs(float(cluster_centers[1] - cluster_centers[0]))
scatter = float(np.quantile(np.abs(axial - cluster_centers[labels]), 0.90))
payload = {
    "source": source.name,
    "marks": len(targets),
    "faces": len(face_indices),
    "points": len(points),
    "normal_values": [float(value) for value in normal_values],
    "normal_axis": [float(value) for value in axis],
    "normal_plane_condition": float(normal_values[1] / max(normal_values[0], 1.0e-12)),
    "axial_centers": [float(value) for value in cluster_centers],
    "axial_separation": separation,
    "axial_scatter_p90": scatter,
    "scatter_fraction": scatter / max(separation, 1.0e-12),
    "cluster_sizes": [int(np.count_nonzero(labels == index)) for index in range(2)],
    "source_modified": False,
    "whole_vehicle_search": False,
}
print("SMRN_DISCONNECTED_NORMAL_AUDIT_V0625=" + json.dumps(payload, separators=(",", ":")))
