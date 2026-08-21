"""Freeze the accepted-for-debugging surface preview before legacy-shell work."""

import json
from pathlib import Path

import bpy


root = Path(r"C:\codex_auto\semantic-mesh-restorer-next\artifacts\checkpoints")
root.mkdir(parents=True, exist_ok=True)
checkpoint = root / "maus_rotational_surface_v068_frozen.blend"
current_file = bpy.data.filepath
scene = bpy.context.scene
source_name = str(scene.get("smrn_source_name", ""))
source = bpy.data.objects.get(source_name)
surface_name = str(scene.get("smrn_surface_candidate_name", ""))
surface = bpy.data.objects.get(surface_name)

bpy.ops.wm.save_as_mainfile(filepath=str(checkpoint), copy=True, check_existing=False)

report = {
    "checkpoint": str(checkpoint),
    "checkpoint_exists": checkpoint.exists(),
    "active_blend_unchanged": bpy.data.filepath == current_file,
    "active_blend": bpy.data.filepath,
    "source": source_name,
    "source_vertices": len(source.data.vertices) if source and source.type == "MESH" else 0,
    "source_faces": len(source.data.polygons) if source and source.type == "MESH" else 0,
    "surface_candidate": surface_name,
    "surface_candidate_exists": surface is not None,
    "surface_candidate_mode": str(scene.get("smrn_surface_candidate_mode", "")),
    "legacy_rotational_candidate": str(scene.get("smrn_rotational_candidate_name", "")),
}
(root / "maus_rotational_surface_v068_frozen.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("SMRN_FROZEN_SURFACE=" + json.dumps(report, ensure_ascii=False, separators=(",", ":")))
