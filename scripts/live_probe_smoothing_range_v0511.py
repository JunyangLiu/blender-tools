"""Probe old-max and strong smoothing without touching the visible candidate."""

import json
import math

import bmesh
import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.surface_rebuild_blender import (
    _grow_marked_region,
    _rebuild_working_mesh,
    _remove_object,
    _seed_face_indices,
    _source_and_records,
)


scene = bpy.context.scene
source, targets, excludes, before = _source_and_records(scene)
candidate_name = str(scene.get("smrn_surface_candidate_name", ""))
hard_angle = math.radians(float(scene.smrn_surface_hard_angle))
probe = bmesh.new()
probe.from_mesh(source.data)
selected, growth = _grow_marked_region(probe, source, targets, excludes, hard_angle)
excluded = set(_seed_face_indices(
    [record for record in excludes if record.hit_object_name == source.name],
    len(probe.faces),
))
probe.free()

results = {}
for strength in (0.5, 1.0):
    working = None
    try:
        working, _vertices, _faces, report = _rebuild_working_mesh(
            source,
            sorted(selected),
            sorted(excluded),
            int(scene.smrn_surface_subdivision_level),
            strength,
            hard_angle,
            "smooth",
        )
        results[str(strength)] = {
            "iterations": report["smoothing_iterations"],
            "factor": report["smoothing_factor"],
            "max_allowed_displacement": report["max_allowed_displacement"],
            "max_actual_displacement": report["max_actual_displacement"],
            "quality_passed": report["passed"],
            "quality_gates": report["quality_gates"],
        }
    finally:
        if working is not None:
            _remove_object(working)

after = source_snapshot(source)
print("SMRN_SMOOTHING_PROBE_V0511=" + json.dumps({
    "source": source.name,
    "source_unchanged": before["fingerprint"] == after["fingerprint"],
    "semantic_region": growth,
    "visible_candidate_preserved": bpy.data.objects.get(candidate_name) is not None,
    "results": results,
}, ensure_ascii=False, separators=(",", ":")))
