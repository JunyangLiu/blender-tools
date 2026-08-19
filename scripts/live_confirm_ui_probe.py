"""Read-only probe for the active candidate confirmation UI."""

import json

import bpy


scene = bpy.context.scene
handle_name = str(scene.get("smrn_handle_candidate_name", ""))
rotational_name = str(scene.get("smrn_rotational_candidate_name", ""))
handle = bpy.data.objects.get(handle_name)
rotational = bpy.data.objects.get(rotational_name)
before = [tuple(vertex.co) for vertex in handle.data.vertices] if handle else []
adjust_result = bpy.ops.smrn.adjust_handle_thickness() if handle else {"CANCELLED"}
after = [tuple(vertex.co) for vertex in handle.data.vertices] if handle else []
adjustment = {}
if handle:
    adjustment = json.loads(str(handle.get("smrn_handle_report_json", "{}"))).get(
        "thickness_adjustment", {}
    )

print("SMRN_CONFIRM_UI_PROBE=" + json.dumps({
    "blend": bpy.data.filepath,
    "handle_candidate": handle_name or None,
    "handle_exists": handle is not None,
    "handle_accepted": bool(handle.get("smrn_accepted", False)) if handle else None,
    "rotational_candidate": rotational_name or None,
    "rotational_exists": rotational is not None,
    "confirm_operator": hasattr(bpy.types, "SMRN_OT_confirm_candidate"),
    "thickness_operator": hasattr(bpy.types, "SMRN_OT_adjust_handle_thickness"),
    "thickness_scale": float(scene.smrn_handle_thickness_scale),
    "adjust_result": sorted(adjust_result),
    "geometry_unchanged_at_1x": before == after,
    "adjustment": adjustment,
    "accepted_objects": [
        obj.name for obj in bpy.data.objects
        if bool(obj.get("smrn_accepted", False))
    ],
}, ensure_ascii=False, separators=(",", ":")))
