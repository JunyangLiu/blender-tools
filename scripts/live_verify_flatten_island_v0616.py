"""Build the current flatten candidate and report low-support island handling."""

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
if int(planarity.get("preserved_component_count", 0)) < 1:
    raise RuntimeError("The known low-support island was not preserved")
print("SMRN_FLATTEN_ISLAND_V0616=" + json.dumps({
    "status": report["status"],
    "source": source.name,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "source_unchanged": report["source_unchanged"],
    "target_faces": report["semantic_region"]["selected_faces"],
    "component_count": planarity.get("component_count"),
    "fitted_component_count": planarity.get("fitted_component_count"),
    "preserved_component_count": planarity.get("preserved_component_count"),
    "preserved_faces": planarity.get("preserved_faces"),
    "preserved_movable_vertices": planarity.get("preserved_movable_vertices"),
    "projection_fraction": topology.get("flatten_projection_fraction"),
    "before_rms": planarity.get("before_rms"),
    "after_rms": planarity.get("after_rms"),
    "quality_gates": topology.get("quality_gates"),
    "candidate": report.get("preview_object"),
    "working": report.get("working_object"),
    "summary": scene.smrn_surface_summary,
}, ensure_ascii=False, separators=(",", ":")))
