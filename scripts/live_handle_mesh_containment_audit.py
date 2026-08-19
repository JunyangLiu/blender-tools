"""Audit semantic source samples against the actual polygon candidate shell."""

import json

import bpy

from semantic_mesh_marker_next.handle_blender import (
    _dense_face_samples,
    _current_anchor,
    _mesh_containment,
    _records,
    _semantic_handle_faces,
    analyze_scene,
)
from semantic_mesh_marker_next.handle_fit import path_points_world, polyline_nearest


scene = bpy.context.scene
fit, _source, targets, _supports, _context = analyze_scene(scene)
candidate = bpy.data.objects.get(str(scene.get("smrn_handle_candidate_name", "")))
report = json.loads(str(candidate["smrn_handle_report_json"]))
path = path_points_world(fit, max(64, int(scene.smrn_handle_path_segments)), (0.0, 0.0))
marked = []
for record in targets:
    marked.append(tuple(_current_anchor(record)[0]))
_, _, marked_distances = polyline_nearest(marked, path)
corridor = max(float(max(marked_distances)) * 1.35, fit.radius_hint * 1.75)
face_map, expansion = _semantic_handle_faces(targets, path, fit.plane_normal, corridor)
points, areas, owners = _dense_face_samples(face_map, order=4)

vertices = [candidate.matrix_world @ vertex.co for vertex in candidate.data.vertices]
faces = [tuple(polygon.vertices) for polygon in candidate.data.polygons]
tolerance = max(1.0e-7, float(report["coverage_qa"]["normal_radius"]) * 1.0e-6)
containment = _mesh_containment(vertices, faces, points, areas, owners, tolerance)

print("SMRN_HANDLE_MESH_CONTAINMENT=" + json.dumps({
    **containment,
    "semantic_expansion": expansion,
}, ensure_ascii=False, separators=(",", ":")))
