"""Analyze the current marks without creating or replacing a candidate."""

import json

import bpy

from semantic_mesh_marker_next.rotational_blender import analyze_scene


fit, source, targets, excludes, context = analyze_scene(bpy.context.scene)
payload = {
    "status": fit.status,
    "reason": fit.reason,
    "profile_kind": fit.profile_kind,
    "surface_side": fit.surface_side,
    "axis": list(fit.axis),
    "radius": abs(float(fit.signed_radius_at_origin)),
    "axial_span": float(fit.axial_max - fit.axial_min),
    "angular_span_degrees": float(fit.angular_span * 180.0 / 3.141592653589793),
    "relative_residual_p90": fit.relative_residual_p90,
    "normal_error_p90_degrees": fit.normal_error_p90_degrees,
    "confidence": fit.confidence,
    "marks": len(targets),
    "excludes": len(excludes),
    "source": source.name if source else None,
    "source_unchanged": True,
    "axis_evidence": context.get("axis_evidence"),
    "whole_vehicle_search": False,
}
print("SMRN_CURRENT_ROTATIONAL_ANALYSIS_V0625=" + json.dumps(
    payload, ensure_ascii=False, separators=(",", ":")
))
