"""Build a guarded v0.5.3 flatten preview from the user's current marks."""

import json

import bpy

from semantic_mesh_marker_next.surface_rebuild_blender import build_scene_candidate


scene = bpy.context.scene
candidate, report = build_scene_candidate(scene, "flatten")
topology = report["topology_qa"]
planarity = topology.get("planarity_qa") or {}
scene.smrn_surface_summary = (
    f"平整候选已通过：{report['semantic_region']['selected_faces']} 面，"
    f"无翻面、无塌面；源网格未修改"
)
scene.smrn_status = "已生成安全平整预览；请检查橙色候选，满意后再确认替换。"
bpy.ops.wm.save_mainfile()

print("SMRN_FLATTEN_V053=" + json.dumps({
    "blend": bpy.data.filepath,
    "candidate": candidate.name,
    "candidate_visible": candidate.visible_get(),
    "source": report["source"]["object_name"],
    "source_unchanged": report["source_unchanged"],
    "selected_faces": report["semantic_region"]["selected_faces"],
    "whole_vehicle_search": report["coverage_qa"]["whole_vehicle_search"],
    "selection_method": report["semantic_region"].get("selection_method"),
    "flatten_reference": report.get("flatten_reference"),
    "component_count": planarity.get("component_count"),
    "fitted_component_count": planarity.get("fitted_component_count"),
    "before_rms": planarity.get("before_rms"),
    "after_rms": planarity.get("after_rms"),
    "projection_fraction": topology.get("flatten_projection_fraction"),
    "flipped_faces": topology.get("flipped_faces"),
    "degenerate_faces": topology.get("degenerate_faces"),
    "max_displacement": topology.get("max_actual_displacement"),
    "displacement_limit": topology.get("max_allowed_displacement"),
    "passed": topology["passed"],
}, ensure_ascii=False, separators=(",", ":")))
