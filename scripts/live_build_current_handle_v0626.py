"""Build and QA one candidate from the exact current handle marks."""

import json

import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.handle_blender import build_scene_candidate
from semantic_mesh_marker_next.scene_state import keep_model_visible


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
before = source_snapshot(source)
candidate, report = build_scene_candidate(scene)
after = source_snapshot(source)
keep_model_visible(scene)
print("SMRN_CURRENT_HANDLE_BUILD_V0626=" + json.dumps({
    "candidate": None if candidate is None else candidate.name,
    "candidate_visible": bool(candidate and candidate.visible_get(view_layer=bpy.context.view_layer)),
    "status": report.get("status"),
    "reason": report.get("reason"),
    "fit": report.get("fit"),
    "coverage_qa": report.get("coverage_qa"),
    "topology_qa": report.get("topology_qa"),
    "endpoint_qa": report.get("endpoint_qa"),
    "source_unchanged": before == after,
    "source_visible": not source.hide_get(),
}, ensure_ascii=False, separators=(",", ":")))
