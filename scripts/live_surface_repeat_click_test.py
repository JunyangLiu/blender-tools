"""Exercise the repeated-click fast path without rebuilding or changing source geometry."""

import json

import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.scene_state import ensure_scene_roots, keep_model_visible
from semantic_mesh_marker_next.surface_rebuild_blender import (
    CANDIDATE_PREFIX,
    REPORT_KEY,
    WORKING_PREFIX,
    _candidate_request_signature,
    _source_and_records,
    build_scene_candidate,
)


scene = bpy.context.scene
source, targets, excludes, before = _source_and_records(scene)
mode = "flatten"
signature = _candidate_request_signature(scene, before, targets, excludes, mode)
keys = (
    "smrn_surface_candidate_name",
    "smrn_surface_working_name",
    "smrn_surface_candidate_mode",
    "smrn_surface_last_report_json",
)
old_values = {key: scene.get(key) for key in keys}
old_summary = scene.smrn_surface_summary
old_status = str(scene.get("smrn_status", ""))
old_preview = bpy.data.objects.get(str(old_values["smrn_surface_candidate_name"] or ""))
old_working = bpy.data.objects.get(str(old_values["smrn_surface_working_name"] or ""))
created = []
try:
    _model, candidates, _helpers = ensure_scene_roots(scene)
    preview = bpy.data.objects.new(CANDIDATE_PREFIX + "REPEAT_CLICK_TEST", bpy.data.meshes.new("SMRN_REPEAT_PREVIEW_MESH"))
    working = bpy.data.objects.new(WORKING_PREFIX + "REPEAT_CLICK_TEST", bpy.data.meshes.new("SMRN_REPEAT_WORKING_MESH"))
    created.extend((preview, working))
    candidates.objects.link(preview)
    candidates.objects.link(working)
    preview["smrn_source_name"] = source.name
    working["smrn_source_name"] = source.name
    report = {
        "status": "candidate_ready",
        "source": before,
        "source_unchanged": True,
        "semantic_region": {"selected_faces": 1},
        "topology_qa": {"passed": True, "region_faces_after": 1},
        "coverage_qa": {"whole_vehicle_search": False, "source_objects_scanned": 1},
        "working_object": working.name,
        "preview_object": preview.name,
        "mode": mode,
        "request_signature": signature,
        "reused_existing": False,
        "flatten_reference": {
            "height_mode": scene.smrn_surface_height_mode,
            "normal_mode": scene.smrn_surface_normal_mode,
            "normal_hint_local": None,
        },
    }
    payload = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    preview[REPORT_KEY] = payload
    working[REPORT_KEY] = payload
    scene["smrn_surface_candidate_name"] = preview.name
    scene["smrn_surface_working_name"] = working.name
    scene["smrn_surface_candidate_mode"] = mode
    scene["smrn_surface_last_report_json"] = payload

    returned, reused = build_scene_candidate(scene, mode)
    operator_result = bpy.ops.smrn.build_surface_candidate(mode=mode)
    after = source_snapshot(source)
    assert returned == preview
    assert reused.get("reused_existing") is True
    assert operator_result == {"FINISHED"}
    assert "无需重复生成" in scene.smrn_surface_summary
    assert before["fingerprint"] == after["fingerprint"]
    assert reused["coverage_qa"]["whole_vehicle_search"] is False
    result = {
        "passed": True,
        "reused_existing": True,
        "operator_result": sorted(operator_result),
        "operator_summary": scene.smrn_surface_summary,
        "source_unchanged": True,
        "source_objects_scanned": reused["coverage_qa"]["source_objects_scanned"],
        "whole_vehicle_search": reused["coverage_qa"]["whole_vehicle_search"],
        "target_marks": len(targets),
        "exclude_marks": len(excludes),
    }
finally:
    for key, value in old_values.items():
        if value is None:
            if key in scene:
                del scene[key]
        else:
            scene[key] = value
    scene.smrn_surface_summary = old_summary
    scene["smrn_status"] = old_status
    for obj in created:
        mesh = obj.data
        if bpy.data.objects.get(obj.name) is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    keep_model_visible(scene, tuple(item for item in (source, old_preview) if item is not None))
    if old_working is not None:
        old_working.hide_viewport = True
        old_working.hide_render = True
        old_working.hide_set(True)

print("SMRN_SURFACE_REPEAT_CLICK_TEST=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
