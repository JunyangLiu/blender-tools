"""Hot-reload v0.6.20 and rebuild only the current marked flatten request."""

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
    if module_name == "semantic_mesh_marker_next" or module_name.startswith(
        "semantic_mesh_marker_next."
    ):
        del sys.modules[module_name]

addon = importlib.import_module("semantic_mesh_marker_next")
addon.register()
from semantic_mesh_marker_next import surface_rebuild_blender as surface


scene = bpy.context.scene
preview, report = surface.build_scene_candidate(scene, "flatten")
topology = report["topology_qa"]
planarity = topology.get("planarity_qa") or {}
working = bpy.data.objects.get(str(scene.get("smrn_surface_working_name", "")))

for obj in bpy.context.selected_objects:
    obj.select_set(False)
if working is not None:
    working.select_set(True)
    bpy.context.view_layer.objects.active = working
bpy.context.view_layer.update()
for area in bpy.context.screen.areas:
    area.tag_redraw()
try:
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
except RuntimeError:
    pass

path = REPO / "artifacts" / "maus_current_flatten_candidate_v0620.png"
path.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.screen.screenshot(filepath=str(path))
print("SMRN_CURRENT_FLATTEN_V0620=" + json.dumps({
    "version": list(addon.bl_info["version"]),
    "source": str(scene.get("smrn_source_name", "")),
    "source_unchanged": report["source_unchanged"],
    "selected_faces": report["semantic_region"]["selected_faces"],
    "projected_vertices": planarity.get("projected_vertices"),
    "after_max_abs": planarity.get("after_max_abs"),
    "exact_tolerance": planarity.get("exact_tolerance"),
    "flipped_faces": topology.get("flipped_faces"),
    "accepted_unstable_sliver_flips": topology.get("accepted_unstable_sliver_flips"),
    "accepted_unstable_sliver_flip_details": topology.get(
        "accepted_unstable_sliver_flip_details"
    ),
    "degenerate_faces": topology.get("degenerate_faces"),
    "quality_passed": topology.get("passed"),
    "working": working.name if working is not None else None,
    "whole_vehicle_search": False,
    "screenshot": str(path),
}, ensure_ascii=False, separators=(",", ":")))
