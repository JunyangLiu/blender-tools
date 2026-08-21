"""Read-only fit diagnostics for the marked legacy rotational cover."""

import json
import math

import bpy
import numpy as np

from semantic_mesh_marker_next.rotational_blender import (
    _coordinates,
    _dense_triangle_samples,
    _expanded_domain,
    _semantic_rotational_faces,
    analyze_scene,
)


scene = bpy.context.scene
fit, source, targets, excludes, context = analyze_scene(scene)
faces, expansion = _semantic_rotational_faces(fit, source, targets)
domain = _expanded_domain(fit, source, targets, faces)
dense = _dense_triangle_samples(source, targets, face_indices=faces)
axial, radius, angle = _coordinates(dense, fit)
predicted = np.abs(fit.signed_radius_at_origin + fit.signed_slope * axial)
residual = radius - predicted if fit.surface_side == "outer" else predicted - radius

bins = []
for lo in np.linspace(float(np.min(axial)), float(np.max(axial)), 9)[:-1]:
    hi = lo + (float(np.max(axial)) - float(np.min(axial))) / 8.0
    mask = (axial >= lo) & (axial <= hi)
    if np.any(mask):
        bins.append({
            "axial_min": float(lo),
            "axial_max": float(hi),
            "samples": int(np.sum(mask)),
            "residual_median": float(np.median(residual[mask])),
            "residual_p95": float(np.quantile(residual[mask], 0.95)),
            "residual_max": float(np.max(residual[mask])),
        })

payload = {
    "fit": fit.to_dict(),
    "semantic_expansion": expansion,
    "domain": {
        "axial_min": domain[0],
        "axial_max": domain[1],
        "angle_start_degrees": math.degrees(domain[2]),
        "angle_span_degrees": math.degrees(domain[3]),
        "legacy_global_clearance": domain[4],
    },
    "dense_samples": len(dense),
    "residual": {
        "minimum": float(np.min(residual)),
        "median": float(np.median(residual)),
        "p90": float(np.quantile(residual, 0.90)),
        "p95": float(np.quantile(residual, 0.95)),
        "p99": float(np.quantile(residual, 0.99)),
        "maximum": float(np.max(residual)),
    },
    "axial_bins": bins,
}
print("SMRN_LEGACY_DIAG=" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
