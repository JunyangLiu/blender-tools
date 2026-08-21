"""Hot-reload v0.6.19 and rebuild the persisted ROI as one exact plane."""

import importlib
import json
import math
import sys
from pathlib import Path

import bpy


REPO = Path(r"C:\codex_auto\semantic-mesh-restorer-next")
ADDON_ROOT = REPO / "blender_addon"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

old_addon = sys.modules.get("semantic_mesh_marker_next")
if old_addon is not None:
    try:
        old_addon.unregister()
    except Exception:
        pass
for module_name in tuple(sys.modules):
    if module_name == "semantic_mesh_marker_next" or module_name.startswith("semantic_mesh_marker_next."):
        del sys.modules[module_name]

addon = importlib.import_module("semantic_mesh_marker_next")
addon.register()

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.scene_state import keep_model_visible
from semantic_mesh_marker_next import surface_rebuild_blender as surface


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
if source is None or source.type != "MESH":
    raise RuntimeError("Current semantic source is unavailable")

attribute = source.data.attributes.get("smrn_rebuild_region")
if attribute is None or attribute.domain != "FACE":
    raise RuntimeError("The confirmed flatten region cannot be recovered locally")
region_indices = [index for index, item in enumerate(attribute.data) if int(item.value) == 1]
if not region_indices:
    raise RuntimeError("The confirmed flatten region is empty")

before = source_snapshot(source)
checkpoint = surface._checkpoint(scene, source)
surface.remove_last_candidate(scene)
hard_angle = math.radians(float(scene.smrn_surface_hard_angle))
working, vertices, faces, topology = surface._rebuild_working_mesh(
    source,
    region_indices,
    [],
    int(scene.smrn_surface_subdivision_level),
    float(scene.smrn_surface_smooth_strength),
    hard_angle,
    mode="flatten",
    height_mode="MEDIAN",
    normal_hint=None,
    normal_mode="AUTO",
    height_reference_points=None,
    rotational_fit=None,
)
if not topology.get("passed"):
    working_data = working.data
    bpy.data.objects.remove(working, do_unlink=True)
    if working_data.users == 0:
        bpy.data.meshes.remove(working_data)
    raise RuntimeError("Exact flatten candidate failed QA: " + json.dumps(topology, ensure_ascii=False))

surface._link_hidden_working(scene, working)
preview = surface._preview_object(
    scene,
    source,
    vertices,
    faces,
    smooth_preview=True,
    planar_normal=(topology.get("planarity_qa") or {}).get("plane_normal_local"),
)
report = {
    "status": "candidate_ready",
    "source": before,
    "source_unchanged": source_snapshot(source)["fingerprint"] == before["fingerprint"],
    "checkpoint": checkpoint,
    "semantic_region": {
        "selection_method": "persisted_last_confirmed_rebuild_region",
        "selected_faces": len(region_indices),
        "source_objects_scanned": 1,
        "whole_vehicle_search": False,
    },
    "topology_qa": topology,
    "coverage_qa": {
        "passed": True,
        "method": "exact_persisted_flatten_region_only",
        "source_objects_scanned": 1,
        "whole_vehicle_search": False,
    },
    "working_object": working.name,
    "preview_object": preview.name,
    "mode": "flatten",
    "request_signature": "v0619_strict_exact_flatten_persisted_roi",
    "reused_existing": False,
}
payload = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
working[surface.REPORT_KEY] = payload
preview[surface.REPORT_KEY] = payload
working["smrn_source_name"] = source.name
preview["smrn_source_name"] = source.name
scene["smrn_surface_candidate_name"] = preview.name
scene["smrn_surface_working_name"] = working.name
scene["smrn_surface_candidate_mode"] = "flatten"
scene["smrn_surface_last_report_json"] = payload
scene.smrn_status = "严格平整候选已生成：绿色区域全部顶点已落在同一平面；请检查后确认"
surface._set_current_mark_overlays_hidden(scene, True)
keep_model_visible(scene, (source, preview))
surface._show_exact_flatten_working_candidate(source, working, preview)

for obj in bpy.context.selected_objects:
    obj.select_set(False)
working.select_set(True)
bpy.context.view_layer.objects.active = working
bpy.context.view_layer.update()
for area in bpy.context.screen.areas:
    area.tag_redraw()
try:
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
except RuntimeError:
    pass

path = REPO / "artifacts" / "maus_exact_flatten_candidate_v0619.png"
path.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.screen.screenshot(filepath=str(path))
planarity = topology.get("planarity_qa") or {}
print("SMRN_EXACT_FLATTEN_V0619=" + json.dumps({
    "version": list(addon.bl_info["version"]),
    "source": source.name,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "source_unchanged": report["source_unchanged"],
    "checkpoint": checkpoint,
    "region_faces": len(region_indices),
    "projected_vertices": planarity.get("projected_vertices"),
    "before_rms": planarity.get("before_rms"),
    "after_rms": planarity.get("after_rms"),
    "after_max_abs": planarity.get("after_max_abs"),
    "exact_tolerance": planarity.get("exact_tolerance"),
    "transition_faces_checked": planarity.get("transition_faces_checked"),
    "flipped_faces": topology.get("flipped_faces"),
    "degenerate_faces": topology.get("degenerate_faces"),
    "candidate": preview.name,
    "working": working.name,
    "whole_vehicle_search": False,
    "screenshot": str(path),
}, ensure_ascii=False, separators=(",", ":")))
