"""Verify isolated component safety against the user's current green marks."""

import json

import bpy


scene = bpy.context.scene
source_name = str(scene.get("smrn_source_name", ""))
source = bpy.data.objects.get(source_name)
if source is None:
    raise RuntimeError("Current semantic source is unavailable")
fingerprint_before = tuple((len(source.data.vertices), len(source.data.edges), len(source.data.polygons)))
result = bpy.ops.smrn.build_surface_candidate(mode="flatten")
if result != {"FINISHED"}:
    raise RuntimeError("Flatten operator did not finish: " + repr(result))
report = json.loads(str(scene.get("smrn_surface_last_report_json", "{}")))
topology = report.get("topology_qa") or {}
planarity = topology.get("planarity_qa") or {}
fingerprint_after = tuple((len(source.data.vertices), len(source.data.edges), len(source.data.polygons)))
if fingerprint_before != fingerprint_after or not report.get("source_unchanged"):
    raise RuntimeError("Source topology changed while building the candidate")
if report.get("status") != "candidate_ready" or not topology.get("passed"):
    raise RuntimeError("Candidate did not pass QA: " + repr(report))
if planarity.get("method") != "component_independent_safe_projection_v2":
    raise RuntimeError("Unexpected flatten pipeline: " + repr(planarity.get("method")))
if int(planarity.get("fitted_component_count", 0)) < 1:
    raise RuntimeError("No component was safely flattened")
if int(planarity.get("preserved_component_count", 0)) < 1:
    raise RuntimeError("Weak disconnected components were not preserved")
if not planarity.get("component_safety_passed"):
    raise RuntimeError("Component safety report did not pass")
if not all(bool(value) for value in (topology.get("quality_gates") or {}).values()):
    raise RuntimeError("One or more topology quality gates failed")
second = bpy.ops.smrn.build_surface_candidate(mode="flatten")
second_report = json.loads(str(scene.get("smrn_surface_last_report_json", "{}")))
if second != {"FINISHED"} or not second_report.get("reused_existing"):
    raise RuntimeError("Repeated click did not reuse the accepted candidate")
print("SMRN_FLATTEN_COMPONENTS_V0617=" + json.dumps({
    "status": report["status"],
    "source": source.name,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "source_unchanged": report["source_unchanged"],
    "whole_vehicle_search": report.get("coverage_qa", {}).get("whole_vehicle_search"),
    "target_faces": report["semantic_region"]["selected_faces"],
    "component_count": planarity.get("component_count"),
    "fitted_component_count": planarity.get("fitted_component_count"),
    "preserved_component_count": planarity.get("preserved_component_count"),
    "preserved_faces": planarity.get("preserved_faces"),
    "preserved_reasons": [item.get("reason") for item in planarity.get("preserved_components", [])],
    "component_fractions": [item.get("projection_fraction") for item in planarity.get("components", [])],
    "before_rms": planarity.get("before_rms"),
    "after_rms": planarity.get("after_rms"),
    "quality_gates": topology.get("quality_gates"),
    "repeated_click_reused": second_report.get("reused_existing"),
    "candidate": report.get("preview_object"),
    "working": report.get("working_object"),
}, ensure_ascii=False, separators=(",", ":")))

