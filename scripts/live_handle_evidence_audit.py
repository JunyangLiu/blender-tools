"""Read-only audit of marked and locally expanded handle evidence."""

import json

import bpy
import numpy as np

from semantic_mesh_marker_next.handle_blender import (
    _local,
    _dense_face_samples,
    _dense_triangle_samples,
    _records,
    _semantic_handle_faces,
    analyze_scene,
)
from semantic_mesh_marker_next.handle_fit import path_points_world, polyline_nearest


scene = bpy.context.scene
fit, _source, targets, supports, context = analyze_scene(scene)
path = path_points_world(fit, max(64, int(scene.smrn_handle_path_segments)))
marked = np.asarray(_dense_triangle_samples(targets, order=6), dtype=float)
_nearest, _tangents, marked_distances = polyline_nearest(marked, path)
corridor = max(float(np.max(marked_distances)) * 1.35, fit.radius_hint * 1.75)
face_map, growth = _semantic_handle_faces(targets, path, fit.plane_normal, corridor)
dense, _areas, owners = _dense_face_samples(face_map, order=4)
_nearest, _tangents, dense_distances = polyline_nearest(dense, path)
local_dense = _local(dense, fit)
worst_indices = np.argsort(dense_distances)[-12:][::-1]


def quantiles(values):
    return [float(value) for value in np.quantile(values, (0, .1, .5, .9, .95, .99, 1))]


owner_counts = {}
for owner in owners:
    key = f"{owner[0]}:{owner[1]}"
    owner_counts[key] = owner_counts.get(key, 0) + 1

accepted = bpy.data.objects.get("SMRN_HANDLE_ACCEPTED_MAUS_20260819T184509Z")
accepted_report = json.loads(str(
    accepted.get("smrn_handle_report_json", "{}") if accepted is not None else "{}"
) or "{}")

print("SMRN_HANDLE_EVIDENCE_AUDIT=" + json.dumps({
    "fit": fit.to_dict(),
    "support_evidence": context.get("support_evidence"),
    "active_supports": len(supports),
    "marked_samples": len(marked),
    "marked_distance_quantiles": quantiles(marked_distances),
    "growth_corridor": corridor,
    "semantic_faces": {name: len(indices) for name, indices in face_map.items()},
    "semantic_samples": len(dense),
    "semantic_distance_quantiles": quantiles(dense_distances),
    "semantic_local_bounds": {
        "u": [float(np.min(local_dense[:, 0])), float(np.max(local_dense[:, 0]))],
        "v": [float(np.min(local_dense[:, 1])), float(np.max(local_dense[:, 1]))],
        "n": [float(np.min(local_dense[:, 2])), float(np.max(local_dense[:, 2]))],
    },
    "worst_samples": [
        {
            "owner": f"{owners[index][0]}:{owners[index][1]}",
            "distance": float(dense_distances[index]),
            "local": [float(value) for value in local_dense[index]],
        }
        for index in worst_indices
    ],
    "worst_faces": sorted(owner_counts.items(), key=lambda item: item[1], reverse=True)[:12],
    "growth": growth,
    "accepted_exists": accepted is not None,
    "accepted_fit": accepted_report.get("fit"),
    "accepted_coverage": accepted_report.get("coverage_qa"),
}, ensure_ascii=False, separators=(",", ":")))
