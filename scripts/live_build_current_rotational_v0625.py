"""Build the current marked rotational candidate and report bounded QA."""

import json

import bpy

from semantic_mesh_marker_next.rotational_blender import build_scene_candidate


candidate, report = build_scene_candidate(bpy.context.scene)
payload = {
    "candidate": candidate.name if candidate else None,
    "status": report.get("status"),
    "reason": report.get("reason"),
    "source_unchanged": report.get("source_unchanged"),
    "fit": report.get("fit"),
    "axis_evidence": report.get("axis_evidence"),
    "coverage_qa": report.get("coverage_qa"),
    "topology_qa": report.get("topology_qa"),
    "selection": report.get("selection"),
    "whole_vehicle_search": False,
}
print("SMRN_CURRENT_ROTATIONAL_BUILD_V0625=" + json.dumps(
    payload, ensure_ascii=False, separators=(",", ":")
))
