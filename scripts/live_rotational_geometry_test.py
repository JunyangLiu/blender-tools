"""In-Blender smoke test for closed full and partial rotational shells."""

import json
import math

from semantic_mesh_marker_next.rotational_blender import _candidate_geometry, _topology_report
from semantic_mesh_marker_next.rotational_fit import RotationalFit


def sample_fit(mode, span):
    return RotationalFit(
        status="candidate_ready", reason="test", profile_kind="cylinder", surface_side="outer",
        axis=(0.31, 0.72, 0.62), axis_origin=(2.0, -4.0, 1.0),
        basis_x=(0.0, 0.6520392685, -0.7581852049),
        basis_y=(-0.9507367752, 0.2350349831, 0.2020701525),
        signed_radius_at_origin=3.0, signed_slope=0.0,
        axial_min=-2.0, axial_max=2.0, angular_start=0.2, angular_span=span,
        angular_largest_gap=2.0 * math.pi - span, coverage_mode=mode,
        point_residual_p50=0.0, point_residual_p90=0.0, relative_residual_p90=0.0,
        normal_error_p90_degrees=0.0, condition_number=1.0, confidence=1.0, sample_count=20,
    )


results = {}
for mode, span in (("partial_arc", math.radians(125.0)), ("full_rotation", 2.0 * math.pi)):
    fit = sample_fit(mode, span)
    vertices, faces, segments = _candidate_geometry(
        fit, -2.0, 2.0, 0.2, span, 0.25, 0.02, 128
    )
    results[mode] = {**_topology_report(vertices, faces), "segments": segments}
print("SMRN_GEOMETRY_TEST=" + json.dumps(results, separators=(",", ":")))

