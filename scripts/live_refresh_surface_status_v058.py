"""Refresh the panel summary from the already verified strict candidate."""

import json

import bpy


operator_result = sorted(bpy.ops.smrn.build_surface_candidate(mode="flatten"))
bpy.ops.wm.save_mainfile()
print("SMRN_STRICT_SURFACE_STATUS=" + json.dumps({
    "operator_result": operator_result,
    "summary": bpy.context.scene.smrn_surface_summary,
    "status": bpy.context.scene.smrn_status,
}, ensure_ascii=False, separators=(",", ":")))
