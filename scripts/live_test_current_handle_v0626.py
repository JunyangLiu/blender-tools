"""Analyze the exact current handle marks without changing the scene."""

import json

import bpy

from semantic_mesh_marker_next.handle_blender import analyze_scene


fit, source, targets, supports, report = analyze_scene(bpy.context.scene)
print("SMRN_CURRENT_HANDLE_V0626=" + json.dumps({
    "fit": fit.to_dict(),
    "source": None if source is None else source.name,
    "target_count": len(targets),
    "active_support_count": len(supports),
    "support_evidence": report.get("support_evidence"),
    "evidence_request": report.get("evidence_request"),
}, ensure_ascii=False, separators=(",", ":")))
