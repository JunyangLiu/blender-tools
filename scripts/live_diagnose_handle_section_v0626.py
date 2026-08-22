"""Inspect only the active semantic handle corridor; never scan the vehicle."""

import json

import bpy
import numpy as np

from semantic_mesh_marker_next.handle_blender import (
    _current_anchor,
    _dense_face_samples,
    _local,
    _semantic_handle_faces,
    analyze_scene,
)
from semantic_mesh_marker_next.handle_fit import path_points_world, polyline_nearest


scene = bpy.context.scene
fit, source, targets, supports, context = analyze_scene(scene)
path = path_points_world(fit, max(64, int(scene.smrn_handle_path_segments)), (0.0, 0.0))
anchors = np.asarray([tuple(_current_anchor(item)[0]) for item in targets], dtype=float)
_, _, anchor_distances = polyline_nearest(anchors, path)
corridor = max(
    float(np.quantile(anchor_distances, 0.95)) + fit.radius_hint * 1.25,
    fit.radius_hint * 2.75,
)
face_map, diagnostics = _semantic_handle_faces(targets, path, fit.plane_normal, corridor)
dense, areas, owners = _dense_face_samples(face_map, order=4)
nearest, tangents, distances = polyline_nearest(dense, path)
local = _local(dense, fit)
below = local[:, 1] < -fit.radius_hint * 1.25
left = np.sqrt(np.square(local[:, 0] + fit.half_span) + np.square(local[:, 2]))
right = np.sqrt(np.square(local[:, 0] - fit.half_span) + np.square(local[:, 2]))
terminal = below & ((left <= corridor) | (right <= corridor))
supported = (distances <= corridor) | terminal

def qs(values):
    values = np.asarray(values, dtype=float)
    return {
        str(q): float(np.quantile(values, q))
        for q in (0.0, 0.5, 0.8, 0.9, 0.95, 0.98, 1.0)
    }

owner_stats = []
for owner in sorted(set(owners)):
    mask = np.asarray([value == owner for value in owners]) & supported & ~terminal
    if np.any(mask):
        owner_stats.append({
            "owner": owner,
            "samples": int(np.sum(mask)),
            "distance_p50": float(np.quantile(distances[mask], 0.5)),
            "distance_p95": float(np.quantile(distances[mask], 0.95)),
            "distance_max": float(np.max(distances[mask])),
        })
owner_stats.sort(key=lambda item: item["distance_max"], reverse=True)

print("SMRN_HANDLE_SECTION_V0626=" + json.dumps({
    "fit_radius_hint": fit.radius_hint,
    "anchor_distances": qs(anchor_distances),
    "corridor": corridor,
    "dense_body_distances": qs(distances[supported & ~terminal]),
    "dense_supported": int(np.sum(supported)),
    "dense_discarded": int(np.sum(~supported)),
    "terminal": int(np.sum(terminal & supported)),
    "worst_faces": owner_stats[:12],
    "semantic": diagnostics,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
}, ensure_ascii=False, separators=(",", ":")))
