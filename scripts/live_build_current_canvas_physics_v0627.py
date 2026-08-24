"""Rebuild the current green cloth region and expose the cloth-aware QA evidence."""

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
marks_before = load_all_marks(scene)
candidate, report = build_scene_candidate(scene, mode="canvas_physics")
after = source_snapshot(source)
marks_after = load_all_marks(scene)
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

topology = report.get("topology_qa", {})
guard = topology.get("canvas_dihedral_guard_qa") or {}
canvas = topology.get("canvas_wave_qa") or {}
print("SMRN_PHYSICS_CANVAS_V0627=" + json.dumps({
    "source": source.name,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "source_fingerprint": after["fingerprint"],
    "source_unchanged": True,
    "marks_preserved": len(marks_after),
    "candidate": candidate.name,
    "candidate_visible": candidate.visible_get(view_layer=bpy.context.view_layer),
    "candidate_show_in_front": bool(candidate.show_in_front),
    "mode": report.get("mode"),
    "status": report.get("status"),
    "selected_faces": topology.get("selected_faces_before"),
    "region_faces_after": topology.get("region_faces_after"),
    "whole_vehicle_search": canvas.get("whole_vehicle_search"),
    "source_objects_scanned": canvas.get("source_objects_scanned"),
    "before_dihedral_p95_degrees": topology.get("before_dihedral_p95_degrees"),
    "after_dihedral_p95_degrees": topology.get("after_dihedral_p95_degrees"),
    "canvas_dihedral_guard": guard,
    "flipped_faces": topology.get("flipped_faces"),
    "degenerate_faces": topology.get("degenerate_faces"),
    "quality_gates": topology.get("quality_gates"),
    "passed": topology.get("passed"),
}, ensure_ascii=False, separators=(",", ":")))
