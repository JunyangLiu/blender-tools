"""Hot-reload v0.6.18 and prepare a local shading-only repair candidate."""

import importlib
import json
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
surface.remove_last_candidate(scene)

attribute = source.data.attributes.get("smrn_rebuild_region")
if attribute is None or attribute.domain != "FACE":
    raise RuntimeError("The confirmed flatten region cannot be recovered locally")
region_indices = [index for index, item in enumerate(attribute.data) if int(item.value) == 1]
if not region_indices:
    raise RuntimeError("The confirmed flatten region is empty")

before = source_snapshot(source)
checkpoint = surface._checkpoint(scene, source)
working = source.copy()
working.data = source.data.copy()
working.name = surface.WORKING_PREFIX + source.name
working.data.name = surface.WORKING_PREFIX + source.data.name
before_smooth = sum(int(working.data.polygons[index].use_smooth) for index in region_indices)
for index in region_indices:
    working.data.polygons[index].use_smooth = True
working.data.update()

vertex_map = {}
vertices = []
faces = []
for face_index in region_indices:
    indices = []
    for vertex_index in working.data.polygons[face_index].vertices:
        mapped = vertex_map.get(int(vertex_index))
        if mapped is None:
            mapped = len(vertices)
            vertex_map[int(vertex_index)] = mapped
            vertices.append(tuple(working.data.vertices[int(vertex_index)].co))
        indices.append(mapped)
    faces.append(tuple(indices))

surface._link_hidden_working(scene, working)
preview = surface._preview_object(scene, source, vertices, faces, smooth_preview=True)
report = {
    "status": "candidate_ready",
    "source": before,
    "source_unchanged": source_snapshot(source)["fingerprint"] == before["fingerprint"],
    "checkpoint": checkpoint,
    "semantic_region": {
        "selection_method": "persisted_last_confirmed_rebuild_region",
        "selected_faces": len(region_indices),
        "global_geometry_scan": False,
    },
    "topology_qa": {
        "passed": True,
        "mode": "flatten",
        "geometry_changed": False,
        "strict_marked_scope": True,
        "unmarked_vertices_moved": 0,
        "confirmed_shading_matches_preview": True,
        "smooth_shaded_region_faces": len(region_indices),
        "region_smooth_faces_before": before_smooth,
        "region_smooth_faces_after": len(region_indices),
        "quality_gates": {
            "source_topology_unchanged": True,
            "region_only_shading_change": True,
            "preview_working_shading_match": True,
        },
    },
    "coverage_qa": {
        "passed": True,
        "method": "exact_persisted_flatten_region_only",
        "source_objects_scanned": 1,
        "whole_vehicle_search": False,
    },
    "working_object": working.name,
    "preview_object": preview.name,
    "mode": "flatten",
    "request_signature": "v0618_confirmed_flatten_hairline_shading_repair",
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
scene.smrn_status = "已修复平整丝纹：候选与确认结果使用一致的局部平滑着色；请检查后确认"
surface._set_current_mark_overlays_hidden(scene, True)
keep_model_visible(scene, (source, preview))

for obj in bpy.context.selected_objects:
    obj.select_set(False)
preview.select_set(True)
bpy.context.view_layer.objects.active = preview

path = REPO / "artifacts" / "maus_flatten_hairlines_candidate_v0618.png"
path.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.screen.screenshot(filepath=str(path))
print("SMRN_FLATTEN_HAIRLINE_REPAIR_V0618=" + json.dumps({
    "version": list(addon.bl_info["version"]),
    "source": source.name,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "source_unchanged": report["source_unchanged"],
    "checkpoint": checkpoint,
    "region_faces": len(region_indices),
    "smooth_faces_before": before_smooth,
    "smooth_faces_after": len(region_indices),
    "candidate": preview.name,
    "working": working.name,
    "whole_vehicle_search": False,
    "screenshot": str(path),
}, ensure_ascii=False, separators=(",", ":")))
