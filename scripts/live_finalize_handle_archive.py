"""Verify local-growth regression, remove its working copy, and clear only SMRN marks."""

from __future__ import annotations

import hashlib
import json
import struct

import bpy

from semantic_mesh_marker_next.handle_blender import remove_last_candidate
from semantic_mesh_marker_next.overlay import remove_overlay
from semantic_mesh_marker_next.scene_state import keep_model_visible
from semantic_mesh_marker_next.storage import clear_task_marks


def geometry_hash(obj):
    digest = hashlib.sha256()
    for vertex in obj.data.vertices:
        digest.update(struct.pack("<3d", *obj.matrix_world @ vertex.co))
    for polygon in obj.data.polygons:
        indices = tuple(int(index) for index in polygon.vertices)
        digest.update(struct.pack("<I", len(indices)))
        digest.update(struct.pack(f"<{len(indices)}I", *indices))
    return digest.hexdigest()


scene = bpy.context.scene
accepted = next(
    (obj for obj in bpy.data.objects if bool(obj.get("smrn_accepted", False))
     and obj.name.startswith("SMRN_HANDLE_ACCEPTED_")),
    None,
)
working = bpy.data.objects.get(str(scene.get("smrn_handle_candidate_name", "")))
if accepted is None or working is None:
    raise RuntimeError("Accepted baseline or local-growth regression candidate is missing")

report = json.loads(str(working.get("smrn_handle_report_json", "{}") or "{}"))
accepted_hash = str(accepted.get("smrn_geometry_sha256", ""))
working_hash = geometry_hash(working)
if accepted_hash != working_hash:
    raise RuntimeError("Local-growth candidate differs from the accepted geometry baseline")
if report.get("coverage_qa", {}).get("mesh_containment", {}).get("outside") != 0:
    raise RuntimeError("Local-growth candidate failed dense shell containment")

diagnostics = report.get("semantic_expansion", [])
if not diagnostics or any(item.get("global_geometry_scan") is not False for item in diagnostics):
    raise RuntimeError("Local-growth diagnostics did not prove bounded search")

remove_last_candidate(scene)
removed_marks = clear_task_marks(scene)
for record in removed_marks:
    remove_overlay(record.overlay_object_name)
keep_model_visible(scene)
accepted.hide_set(False)
accepted.hide_viewport = False
accepted.hide_render = False
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)

print("SMRN_HANDLE_ARCHIVE_FINAL=" + json.dumps({
    "accepted_object": accepted.name,
    "geometry_sha256": accepted_hash,
    "regression_exact_match": True,
    "semantic_expansion": diagnostics,
    "coverage_samples": report.get("coverage_qa", {}).get("samples"),
    "outside": report.get("coverage_qa", {}).get("mesh_containment", {}).get("outside"),
    "working_candidate_removed": not bool(scene.get("smrn_handle_candidate_name", "")),
    "plugin_marks_removed": len(removed_marks),
    "accepted_visible": accepted.visible_get(view_layer=bpy.context.view_layer),
}, ensure_ascii=False, separators=(",", ":")))
