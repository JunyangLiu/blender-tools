"""Regenerate only the current unaccepted canvas candidate with v0.6.1."""

import importlib
import json
from pathlib import Path

import bpy


OUTPUT = Path(r"C:\codex_auto\semantic_mesh_restorer_maus_turret\qa_canvas_fair_base_v061.png")
scene = bpy.context.scene
anchors = importlib.import_module("semantic_mesh_marker_next.anchors")
storage = importlib.import_module("semantic_mesh_marker_next.storage")
surface = importlib.import_module("semantic_mesh_marker_next.surface_rebuild_blender")
scene_state = importlib.import_module("semantic_mesh_marker_next.scene_state")
addon = importlib.import_module("semantic_mesh_marker_next")

source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
if source is None or source.type != "MESH":
    raise RuntimeError("Current semantic source is unavailable")
before = anchors.source_snapshot(source)
marks_before = len(storage.load_all_marks(scene))
old_candidate_name = str(scene.get("smrn_surface_candidate_name", ""))

candidate, report = surface.build_scene_candidate(scene, mode="canvas")
after = anchors.source_snapshot(source)
if before["fingerprint"] != after["fingerprint"]:
    raise RuntimeError("Canvas regeneration unexpectedly changed the source mesh")
marks_after = len(storage.load_all_marks(scene))
if marks_before != marks_after:
    raise RuntimeError("Canvas regeneration unexpectedly changed the marks")

scene_state.keep_model_visible(scene, (source, candidate))
bpy.context.view_layer.objects.active = candidate
candidate.select_set(True)
bpy.context.view_layer.update()
bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=3)
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
bpy.ops.screen.screenshot(filepath=str(OUTPUT))

topology = report.get("topology_qa", {})
canvas = topology.get("canvas_wave_qa") or {}
fairing = topology.get("canvas_base_fairing_qa") or canvas.get("base_surface_fairing") or {}
print("SMRN_CANVAS_REGENERATE_V061=" + json.dumps({
    "addon_version": list(addon.bl_info["version"]),
    "source": source.name,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "source_fingerprint": after["fingerprint"],
    "source_unchanged": before["fingerprint"] == after["fingerprint"],
    "marks_preserved": marks_after,
    "old_candidate": old_candidate_name,
    "candidate": candidate.name,
    "candidate_visible": candidate.visible_get(view_layer=bpy.context.view_layer),
    "candidate_ready": report.get("status") == "candidate_ready",
    "selected_faces": topology.get("selected_faces_before"),
    "region_faces_after": topology.get("region_faces_after"),
    "subdivision_cuts": topology.get("subdivision_cuts"),
    "base_fairing": fairing,
    "wave_method": canvas.get("method"),
    "wave_amplitude": canvas.get("wave_amplitude"),
    "maximum_source_displacement": topology.get("max_actual_displacement"),
    "maximum_allowed_displacement": topology.get("max_allowed_displacement"),
    "flipped_faces": topology.get("flipped_faces"),
    "degenerate_faces": topology.get("degenerate_faces"),
    "quality_gates": topology.get("quality_gates"),
    "screenshot": str(OUTPUT),
    "screenshot_exists": OUTPUT.exists(),
}, ensure_ascii=False, separators=(",", ":")))
