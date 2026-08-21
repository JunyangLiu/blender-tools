"""Bounded read-only QA for the two reported brush gaps."""

import json
import time

import bpy

from semantic_mesh_marker_next.raycast import brush_object_stroke_hits


area = next(item for item in bpy.context.screen.areas if item.type == "VIEW_3D")
region = next(item for item in area.regions if item.type == "WINDOW")
region_3d = area.spaces.active.region_3d
scene = bpy.context.scene
working = bpy.data.objects.get(str(scene.get("smrn_surface_working_name", "")))

cases = {
    "small_gap": ((472, 525), (567, 525), {189636, 190645, 190648}),
    "large_gap": ((817, 695), (1037, 725), {190296, 189823, 189841}),
}
results = {}
for label, (start, end, expected) in cases.items():
    started = time.perf_counter()
    hits = brush_object_stroke_hits(
        bpy.context,
        region,
        region_3d,
        start,
        end,
        12,
        working.name,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    faces = {int(hit["face_index"]) for hit in hits}
    results[label] = {
        "elapsed_ms": round(elapsed_ms, 3),
        "hit_faces": len(faces),
        "expected_faces_covered": sorted(expected.intersection(faces)),
        "all_expected_covered": expected.issubset(faces),
    }

print("SMRN_BRUSH_CAPSULE_QA=" + json.dumps({
    "results": results,
    "source_mesh_modified": False,
    "whole_vehicle_search": False,
}, ensure_ascii=False, separators=(",", ":")))
