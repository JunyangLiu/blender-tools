"""Report ranked data-derived axes for the active rotational marks."""

import json

import bpy
import numpy as np

from semantic_mesh_marker_next.rotational_blender import _current_anchor, _source_for_targets, _task_records
from semantic_mesh_marker_next.rotational_fit import (
    FitThresholds, _angle_interval, _basis, _canonical_axis,
    _fit_one_axis, _fit_sparse_circumference, candidate_axes,
)


targets, _excludes = _task_records(bpy.context.scene)
source, _snapshot = _source_for_targets(bpy.context.scene, targets)
anchors = [_current_anchor(item, source) for item in targets]
points = np.asarray([tuple(point) for point, _normal in anchors], dtype=float)
normals = np.asarray([tuple(normal) for _point, normal in anchors], dtype=float)
thresholds = FitThresholds()
rows = []
for index, axis in enumerate(candidate_axes(points, normals, thresholds.maximum_candidates)):
    fit = _fit_one_axis(axis, points, normals, thresholds)
    if fit is None:
        continue
    rows.append({
        "index": index,
        "axis": [float(value) for value in axis],
        "score": float(fit["score"]),
        "cone": bool(fit["cone"]),
        "normal_constrained": bool(fit["normal_constrained"]),
        "coverage_mode": fit["coverage_mode"],
        "relative_p90": float(fit["relative_p90"]),
        "normal_p90": float(fit["normal_p90"]),
        "condition": float(fit["condition"]),
        "slope": float(fit["solution"][3]) if fit["cone"] else 0.0,
        "axial_span": float(fit["axial_max"] - fit["axial_min"]),
        "radius": abs(float(fit["signed_radius"])),
    })
rows.sort(key=lambda item: item["score"])
centered = points - np.mean(points, axis=0)
eigenvalues, eigenvectors = np.linalg.eigh(centered.T @ centered)
axis = _canonical_axis(eigenvectors[:, 0])
basis_x, basis_y = _basis(axis)
plane = np.column_stack((centered @ basis_x, centered @ basis_y))
design = np.column_stack((2.0 * plane[:, 0], 2.0 * plane[:, 1], np.ones(len(points))))
values = np.sum(np.square(plane), axis=1)
circle, _residuals, _rank, _singular = np.linalg.lstsq(design, values, rcond=None)
radial = plane - circle[:2]
angles = np.arctan2(radial[:, 1], radial[:, 0])
unit_normals = normals / np.linalg.norm(normals, axis=1)[:, None]
normal_axial = unit_normals @ axis
normal_radial = unit_normals - normal_axial[:, None] * axis
radial_length = np.linalg.norm(normal_radial, axis=1)
slope_samples = -normal_axial / radial_length
sparse_debug = {
    "eigenvalues": [float(value) for value in eigenvalues],
    "plane_ratio": float(np.sqrt(eigenvalues[0] / eigenvalues[1])),
    "spread_ratio": float(np.sqrt(eigenvalues[1] / eigenvalues[2])),
    "axis": [float(value) for value in axis],
    "angle_interval": list(_angle_interval(angles)),
    "slope_samples": [float(value) for value in slope_samples],
    "slope_p90_deviation": float(np.quantile(np.abs(slope_samples - np.median(slope_samples)), 0.90)),
    "fit_returned": _fit_sparse_circumference(points, normals, thresholds) is not None,
}
print("SMRN_AXIS_AUDIT=" + json.dumps({"ranked": rows[:12], "sparse": sparse_debug}, separators=(",", ":")))
