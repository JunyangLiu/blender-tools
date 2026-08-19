"""Read-only audit of the live Maus Blender session after add-on reload."""

import json

import bpy

import semantic_mesh_marker_next as addon
from semantic_mesh_marker_next.constants import SOURCE_NAME_KEY


scene = bpy.context.scene
source_name = str(scene.get(SOURCE_NAME_KEY, ""))
source = bpy.data.objects.get(source_name)
accepted = bpy.data.objects.get("SMRN_HANDLE_ACCEPTED_MAUS_20260819T184509Z")
surface_objects = [
    obj.name for obj in bpy.data.objects
    if obj.name.startswith(("SMRN_SURFACE_CANDIDATE_", "SMRN_SURFACE_WORKING_FULL_"))
]

result = {
    "blend": bpy.data.filepath,
    "addon_version": list(addon.bl_info["version"]),
    "operators": {
        "smooth_or_flatten": hasattr(bpy.ops.smrn, "build_surface_candidate"),
        "confirm": hasattr(bpy.ops.smrn, "confirm_surface_replacement"),
        "remove": hasattr(bpy.ops.smrn, "remove_surface_candidate"),
    },
    "source": {
        "name": source_name,
        "exists": source is not None,
        "visible": bool(source and not source.hide_get() and not source.hide_viewport),
        "vertices": len(source.data.vertices) if source and source.type == "MESH" else None,
        "faces": len(source.data.polygons) if source and source.type == "MESH" else None,
    },
    "accepted_handle": {
        "exists": accepted is not None,
        "visible": bool(accepted and not accepted.hide_get() and not accepted.hide_viewport),
    },
    "surface_test_artifacts": surface_objects,
    "defaults": {
        "subdivision": int(scene.smrn_surface_subdivision_level),
        "smooth_strength": float(scene.smrn_surface_smooth_strength),
        "hard_angle": float(scene.smrn_surface_hard_angle),
    },
}

print("SMRN_SURFACE_LIVE_AUDIT=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
