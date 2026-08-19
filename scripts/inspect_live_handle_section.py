"""Read-only section diagnostics for the current handle marks."""

import json
import numpy as np

import bpy
from semantic_mesh_marker_next.handle_blender import (
    _dense_triangle_samples,
    _local,
    _marked_edge_radius,
    _path_distances,
    _records,
)
from semantic_mesh_marker_next.handle_fit import fit_handle


targets, _supports = _records(bpy.context.scene)
radius_hint = _marked_edge_radius(targets)
fit = fit_handle(
    [item.world_location for item in targets],
    [item.world_normal for item in targets],
    radius_hint=radius_hint,
)
dense = _dense_triangle_samples(targets)
local = _local(dense, fit)
residual = _path_distances(local, fit)
median = float(np.quantile(residual, 0.50))
mad = float(np.median(np.abs(residual - median)))
corridor = max(fit.radius_hint * 2.75, median + max(fit.radius_hint * 0.75, mad * 5.0))
retained = residual <= corridor
terminal_bridge = (
    (local[:, 1] < -fit.radius_hint * 1.5)
    & (np.abs(local[:, 0]) > fit.half_span * 0.70)
)
body = retained & ~terminal_bridge

def qs(values):
    return [round(float(value), 6) for value in np.quantile(values, (0, .1, .25, .5, .75, .9, .95, 1))]

print("SMRN_HANDLE_SECTION=" + json.dumps({
    "radius_hint": radius_hint,
    "samples": len(dense),
    "body_samples": int(np.sum(body)),
    "abs_depth_quantiles": qs(np.abs(local[body, 2])),
    "path_residual_quantiles": qs(residual[body]),
    "cross_radius_quantiles": qs(np.sqrt(np.square(local[body, 2]) + np.square(residual[body]))),
    "local_rise_quantiles": qs(local[body, 1]),
    "local_span_quantiles": qs(local[body, 0]),
    "terminal_bridge_samples": int(np.sum(terminal_bridge & retained)),
}, separators=(",", ":")))
