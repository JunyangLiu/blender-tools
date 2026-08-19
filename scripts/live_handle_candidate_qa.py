"""Audit and frame the current handle candidate without hiding the vehicle."""

import json
from pathlib import Path

import bpy


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
candidate = bpy.data.objects.get(str(scene.get("smrn_handle_candidate_name", "")))
if source is None or candidate is None:
    raise RuntimeError("Missing active source or handle candidate")

report = json.loads(str(candidate.get("smrn_handle_report_json", "{}") or "{}"))
for obj in bpy.context.selected_objects:
    obj.select_set(False)
candidate.select_set(True)
bpy.context.view_layer.objects.active = candidate
candidate.show_in_front = False
candidate.show_wire = True

window = bpy.context.window
area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
space = area.spaces.active
space.show_region_ui = True
space.shading.color_type = "OBJECT"
with bpy.context.temp_override(window=window, area=area, region=next(
    region for region in area.regions if region.type == "WINDOW"
)):
    bpy.ops.view3d.view_selected(use_all_regions=False)
area.spaces.active.region_3d.view_distance *= 1.45
bpy.context.view_layer.update()

output = Path(r"C:\codex_auto\semantic-mesh-restorer-next\artifacts\maus_handle_candidate_current.png")
output.parent.mkdir(exist_ok=True)
with bpy.context.temp_override(window=window, area=area):
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
    bpy.ops.screen.screenshot(filepath=str(output))

occlusion_output = output.with_name("maus_handle_candidate_occlusion.png")
candidate.select_set(False)
candidate.show_wire = False
with bpy.context.temp_override(window=window, area=area):
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
    bpy.ops.screen.screenshot(filepath=str(occlusion_output))
candidate.select_set(True)
candidate.show_wire = True
bpy.context.view_layer.objects.active = candidate

print("SMRN_HANDLE_CANDIDATE_QA=" + json.dumps({
    "screenshot": str(output),
    "occlusion_screenshot": str(occlusion_output),
    "source": source.name,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "source_topology": [len(source.data.vertices), len(source.data.edges), len(source.data.polygons)],
    "candidate": candidate.name,
    "candidate_visible": candidate.visible_get(view_layer=bpy.context.view_layer),
    "candidate_topology": report.get("topology_qa"),
    "coverage": report.get("coverage_qa"),
    "endpoints": report.get("endpoint_qa"),
    "fit": report.get("fit"),
    "frame": report.get("frame_qa"),
    "source_unchanged": report.get("source_unchanged"),
    "evidence_sources_unchanged": report.get("evidence_sources_unchanged"),
}, ensure_ascii=False, separators=(",", ":")))
