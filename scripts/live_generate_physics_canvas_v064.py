"""Generate a non-destructive rope-hung physics canvas candidate."""

import json

import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.scene_state import keep_model_visible
from semantic_mesh_marker_next.storage import load_all_marks
from semantic_mesh_marker_next.surface_rebuild_blender import build_scene_candidate


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
if source is None or source.type != "MESH":
    raise RuntimeError("Current semantic source is unavailable")

before = source_snapshot(source)
marks_before = len(load_all_marks(scene))
candidate, report = build_scene_candidate(scene, mode="canvas_physics")
after = source_snapshot(source)
marks_after = len(load_all_marks(scene))
if before["fingerprint"] != after["fingerprint"]:
    raise RuntimeError("Physics canvas generation changed the source mesh")
if marks_before != marks_after:
    raise RuntimeError("Physics canvas generation changed semantic marks")

keep_model_visible(scene, (source, candidate))
for obj in bpy.context.selected_objects:
    obj.select_set(False)
candidate.select_set(True)
bpy.context.view_layer.objects.active = candidate
bpy.context.view_layer.update()
bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=3)
bpy.ops.wm.save_mainfile()

topology = report.get("topology_qa", {})
canvas = topology.get("canvas_wave_qa") or {}
attachment = canvas.get("attachment_inference") or {}
print("SMRN_PHYSICS_CANVAS_V064=" + json.dumps({
    "source": source.name,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "source_fingerprint": after["fingerprint"],
    "source_unchanged": before["fingerprint"] == after["fingerprint"],
    "marks_preserved": marks_after,
    "candidate": candidate.name,
    "candidate_visible": candidate.visible_get(view_layer=bpy.context.view_layer),
    "candidate_show_in_front": bool(candidate.show_in_front),
    "mode": report.get("mode"),
    "status": report.get("status"),
    "selected_faces": topology.get("selected_faces_before"),
    "region_faces_after": topology.get("region_faces_after"),
    "attachment_vertices": attachment.get("attachment_vertices"),
    "attachment_span_ratio": attachment.get("attachment_span_ratio"),
    "safe_fraction": (topology.get("canvas_base_fairing_qa") or {}).get("safe_deformation_fraction"),
    "solver": canvas.get("method"),
    "structural_constraints": canvas.get("structural_constraints"),
    "whole_vehicle_search": canvas.get("whole_vehicle_search"),
    "source_objects_scanned": canvas.get("source_objects_scanned"),
    "max_actual_displacement": topology.get("max_actual_displacement"),
    "before_dihedral_p95_degrees": topology.get("before_dihedral_p95_degrees"),
    "after_dihedral_p95_degrees": topology.get("after_dihedral_p95_degrees"),
    "flipped_faces": topology.get("flipped_faces"),
    "degenerate_faces": topology.get("degenerate_faces"),
    "quality_gates": topology.get("quality_gates"),
}, ensure_ascii=False, separators=(",", ":")))
