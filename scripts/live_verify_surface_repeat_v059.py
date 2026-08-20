"""Verify that repeating the current flatten request reuses its safe preview."""

import json

import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.surface_rebuild_blender import REPORT_KEY


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
if source is None or source.type != "MESH":
    raise RuntimeError("Current semantic source is unavailable")

before = source_snapshot(source)
operator_result = sorted(bpy.ops.smrn.build_surface_candidate(mode="flatten"))
preview = bpy.data.objects.get(str(scene.get("smrn_surface_candidate_name", "")))
if preview is None:
    raise RuntimeError("Repeated flatten did not retain the current candidate")
after = source_snapshot(source)
stored = json.loads(str(preview.get(REPORT_KEY, "{}")))
print("SMRN_SURFACE_REPEAT_VERIFY=" + json.dumps({
    "candidate": preview.name,
    "operator_result": operator_result,
    "summary": str(scene.smrn_surface_summary),
    "stored_status": stored.get("status"),
    "quality_passed": stored.get("topology_qa", {}).get("passed"),
    "source_fingerprint_unchanged": before["fingerprint"] == after["fingerprint"],
}, ensure_ascii=False, separators=(",", ":")))
