"""Read-only state probe after the canvas-wave hot reload."""

import importlib
import json

import bpy

scene = bpy.context.scene
addon = importlib.import_module("semantic_mesh_marker_next")
from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.storage import load_all_marks

source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
candidate = bpy.data.objects.get(str(scene.get("smrn_surface_candidate_name", "")))
working = bpy.data.objects.get(str(scene.get("smrn_surface_working_name", "")))
print("SMRN_CANVAS_STATE=" + json.dumps({
    "version": list(addon.bl_info["version"]),
    "source": source.name if source else None,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer) if source else None,
    "fingerprint": source_snapshot(source)["fingerprint"] if source else None,
    "candidate": candidate.name if candidate else None,
    "candidate_visible": candidate.visible_get(view_layer=bpy.context.view_layer) if candidate else None,
    "candidate_mode": str(scene.get("smrn_surface_candidate_mode", "")),
    "working": working.name if working else None,
    "marks": len(load_all_marks(scene)),
    "smooth_strength": float(scene.smrn_surface_smooth_strength),
    "canvas_strength": float(scene.smrn_canvas_wave_strength),
    "candidate_like_objects": [obj.name for obj in bpy.data.objects if obj.name.startswith("SMRN_SURFACE_")],
}, ensure_ascii=False, separators=(",", ":")))
