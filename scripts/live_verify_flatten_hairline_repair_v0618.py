"""Verify the prepared hairline repair candidate without accepting it."""

import json

import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.surface_rebuild_blender import REPORT_KEY


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
preview = bpy.data.objects.get(str(scene.get("smrn_surface_candidate_name", "")))
working = bpy.data.objects.get(str(scene.get("smrn_surface_working_name", "")))
if source is None or preview is None or working is None:
    raise RuntimeError("The v0.6.18 repair candidate is incomplete")
report = json.loads(str(preview.get(REPORT_KEY, "{}")))
attribute = working.data.attributes.get("smrn_rebuild_region")
region = [index for index, item in enumerate(attribute.data) if int(item.value) == 1]
smooth = sum(int(working.data.polygons[index].use_smooth) for index in region)
if report.get("status") != "candidate_ready" or not report.get("topology_qa", {}).get("passed"):
    raise RuntimeError("Repair candidate report did not pass")
if source_snapshot(source)["fingerprint"] != report.get("source", {}).get("fingerprint"):
    raise RuntimeError("Source changed after preparing the repair candidate")
if smooth != len(region):
    raise RuntimeError("Working mesh shading does not match the smooth preview")
print("SMRN_VERIFY_FLATTEN_HAIRLINE_V0618=" + json.dumps({
    "source": source.name,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "source_unchanged": report.get("source_unchanged"),
    "candidate_visible": preview.visible_get(view_layer=bpy.context.view_layer),
    "candidate_show_in_front": preview.show_in_front,
    "working_hidden": bool(working.hide_viewport and working.hide_render),
    "region_faces": len(region),
    "working_smooth_faces": smooth,
    "geometry_changed": report.get("topology_qa", {}).get("geometry_changed"),
    "whole_vehicle_search": report.get("coverage_qa", {}).get("whole_vehicle_search"),
    "checkpoint": report.get("checkpoint"),
}, ensure_ascii=False, separators=(",", ":")))
