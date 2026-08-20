"""Apply normal depth testing to the current surface candidate and capture QA."""

import json
from pathlib import Path

import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.scene_state import keep_model_visible


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
preview = bpy.data.objects.get(str(scene.get("smrn_surface_candidate_name", "")))
if source is None or source.type != "MESH":
    raise RuntimeError("Current semantic source is unavailable")
if preview is None or not preview.name.startswith("SMRN_SURFACE_CANDIDATE_"):
    raise RuntimeError("Current surface candidate is unavailable")

before = source_snapshot(source)
was_in_front = bool(preview.show_in_front)
preview.show_in_front = False
preview.hide_viewport = False
preview.hide_render = False
preview.hide_set(False)
keep_model_visible(scene, (source, preview))

# Keep the candidate selected for a clear outline, but let normal scene depth
# decide which fragments are actually visible.
for obj in tuple(bpy.context.selected_objects):
    obj.select_set(False)
preview.select_set(True)
bpy.context.view_layer.objects.active = preview

after = source_snapshot(source)
if before["fingerprint"] != after["fingerprint"]:
    raise RuntimeError("Display update unexpectedly changed the source mesh")

bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
output = Path(
    r"C:\codex_auto\semantic_mesh_restorer_maus_turret\qa_surface_normal_depth_v0510.png"
)
bpy.ops.screen.screenshot(filepath=str(output))
print("SMRN_SURFACE_DEPTH_V0510=" + json.dumps({
    "blend": bpy.data.filepath,
    "candidate": preview.name,
    "show_in_front_before": was_in_front,
    "show_in_front_after": bool(preview.show_in_front),
    "candidate_visible": not preview.hide_get() and not preview.hide_viewport,
    "source_visible": not source.hide_get() and not source.hide_viewport,
    "source_fingerprint": after["fingerprint"],
    "source_unchanged": before["fingerprint"] == after["fingerprint"],
    "screenshot": str(output),
    "screenshot_exists": output.exists(),
}, ensure_ascii=False, separators=(",", ":")))
