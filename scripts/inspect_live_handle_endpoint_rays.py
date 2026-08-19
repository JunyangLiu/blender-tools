"""Trace repeated scene ray hits below both fitted handle endpoints."""

import json

import bpy
from mathutils import Vector

from semantic_mesh_marker_next.handle_blender import analyze_scene


scene = bpy.context.scene
fit, _source, _targets, _supports, _report = analyze_scene(scene)
depsgraph = bpy.context.evaluated_depsgraph_get()
origin = Vector(fit.origin)
span = Vector(fit.span_axis)
rise = Vector(fit.rise_axis)
radius = float(fit.radius_hint)
rows = []
for side in (-1, 1):
    baseline = origin + span * (side * fit.half_span)
    cursor = baseline + rise * (radius * 2.0)
    travelled = -radius * 2.0
    hits = []
    for _index in range(16):
        hit, location, normal, face, obj, _matrix = scene.ray_cast(
            depsgraph, cursor, -rise, distance=max(10.0, radius * 20.0)
        )
        if not hit:
            break
        step = float((cursor - location).dot(rise))
        travelled += step
        hits.append({
            "depth_from_baseline": travelled,
            "object": obj.name if obj else None,
            "face": int(face),
            "normal_dot_rise": float(normal.dot(rise)),
        })
        cursor = location - rise * max(1.0e-4, radius * 0.02)
        travelled += max(1.0e-4, radius * 0.02)
    rows.append({"side": side, "baseline": list(baseline), "hits": hits})

print("SMRN_HANDLE_ENDPOINT_RAYS=" + json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
