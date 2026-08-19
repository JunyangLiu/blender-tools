import math
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np


MODULE_PATH = Path(__file__).parents[1] / "blender_addon" / "semantic_mesh_marker_next" / "handle_fit.py"
SPEC = importlib.util.spec_from_file_location("smrn_handle_fit", MODULE_PATH)
HANDLE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HANDLE
SPEC.loader.exec_module(HANDLE)
fit_handle = HANDLE.fit_handle
path_points_2d = HANDLE.path_points_2d
path_points_world = HANDLE.path_points_world


def unit(value):
    value = np.asarray(value, dtype=float)
    return value / np.linalg.norm(value)


def rotated_frame():
    span = unit((0.72, 0.61, 0.33))
    rise_seed = unit((-0.18, 0.62, -0.77))
    normal = unit(np.cross(span, rise_seed))
    rise = unit(np.cross(normal, span))
    return span, rise, normal


def surface_marks(kind="flat_top", uneven=False):
    span, rise, normal = rotated_frame()
    origin = np.array((14.0, -8.0, 5.0))
    if kind == "flat_top":
        local = np.asarray((
            (-5.0, 0.0), (-5.0, 1.1), (-4.3, 2.6), (-2.0, 2.6),
            (0.0, 2.6), (2.0, 2.6), (4.3, 2.6), (5.0, 1.1), (5.0, 0.0),
        ))
    else:
        theta = np.linspace(math.pi, 0.0, 13)
        local = np.column_stack((5.0 * np.cos(theta), 2.6 * np.sin(theta)))
    indices = list(range(len(local)))
    if uneven:
        indices += [0, 1, 2, 3, 4, 5]
    centers = origin + local[indices, :1] * span + local[indices, 1:] * rise
    radius = 0.28
    points = centers + radius * normal
    normals = np.repeat(normal[None, :], len(points), axis=0)
    supports = np.asarray([
        origin - 0.10 * rise - 5.0 * span,
        origin - 0.12 * rise + 5.0 * span,
        origin - 0.11 * rise - 4.5 * span,
        origin - 0.13 * rise + 4.5 * span,
    ])
    support_normals = np.repeat(rise[None, :], len(supports), axis=0)
    return points, normals, supports, support_normals, radius, span, rise, origin


class HandleFitTests(unittest.TestCase):
    def test_flat_top_uses_final_support_frame_before_path_fit(self):
        values = surface_marks("flat_top", uneven=True)
        points, normals, supports, support_normals, radius, span, rise, _origin = values
        fit = fit_handle(points, normals, supports, support_normals, radius_hint=radius)
        self.assertEqual(fit.status, "candidate_ready", fit.reason)
        self.assertEqual(fit.path_kind, "flat_top")
        self.assertGreater(abs(np.dot(fit.span_axis, span)), 0.999)
        self.assertGreater(np.dot(fit.rise_axis, rise), 0.999)
        self.assertAlmostEqual(fit.support_angle_after_degrees, 0.0, places=8)
        self.assertGreater(fit.rise, 2.0)

    def test_semiellipse_is_recovered_in_arbitrary_orientation(self):
        values = surface_marks("semi_ellipse")
        points, normals, supports, support_normals, radius, span, _rise, _origin = values
        fit = fit_handle(points, normals, supports, support_normals, radius_hint=radius)
        self.assertEqual(fit.status, "candidate_ready", fit.reason)
        self.assertEqual(fit.path_kind, "semi_ellipse")
        self.assertGreater(abs(np.dot(fit.span_axis, span)), 0.999)
        self.assertLess(fit.relative_path_p90, 0.16)

    def test_rise_sign_points_away_from_support(self):
        values = surface_marks("flat_top")
        points, normals, supports, support_normals, radius, _span, rise, _origin = values
        fit = fit_handle(points, normals, supports, -support_normals, radius_hint=radius)
        self.assertEqual(fit.status, "candidate_ready", fit.reason)
        self.assertGreater(np.dot(fit.rise_axis, rise), 0.999)

    def test_unrelated_support_angle_is_rejected(self):
        values = surface_marks("flat_top")
        points, normals, supports, support_normals, radius, span, rise, origin = values
        wrong = unit(span * math.cos(math.radians(50.0)) + rise * math.sin(math.radians(50.0)))
        supports = np.asarray([origin - wrong * 5.0, origin + wrong * 5.0])
        fit = fit_handle(points, normals, supports, support_normals[:2], radius_hint=radius)
        self.assertEqual(fit.status, "needs_more_evidence")
        self.assertIn("安装切线", fit.reason)

    def test_planar_armor_patch_is_not_a_handle(self):
        x = np.linspace(-5.0, 5.0, 14)
        points = np.column_stack((x, 0.15 * np.sin(x), np.zeros_like(x)))
        normals = np.repeat(np.array(((0.0, 0.0, 1.0),)), len(points), axis=0)
        supports = np.asarray(((-5.0, 0.0, -0.1), (5.0, 0.0, -0.1)))
        support_normals = np.repeat(np.array(((0.0, 1.0, 0.0),)), 2, axis=0)
        fit = fit_handle(points, normals, supports, support_normals, radius_hint=0.3)
        self.assertEqual(fit.status, "needs_more_evidence")

    def test_missing_two_end_supports_is_rejected(self):
        values = surface_marks("flat_top")
        points, normals, supports, support_normals, radius, _span, _rise, _origin = values
        fit = fit_handle(points, normals, supports[:2] * 0.0 + supports[0],
                         support_normals[:2], radius_hint=radius)
        self.assertEqual(fit.status, "needs_more_evidence")

    def test_green_path_can_infer_end_mounts_without_red_marks(self):
        values = surface_marks("flat_top")
        fit = fit_handle(values[0], values[1], radius_hint=values[4])
        self.assertEqual(fit.status, "candidate_ready", fit.reason)
        self.assertFalse(fit.support_used)
        self.assertIn("自动推断双端安装", fit.reason)

    def test_generated_path_keeps_exact_flat_top(self):
        values = surface_marks("flat_top")
        fit = fit_handle(*values[:4], radius_hint=values[4])
        path = path_points_world(fit, 120, (0.4, 0.5))
        relative = path - np.asarray(fit.origin)
        u = relative @ np.asarray(fit.span_axis)
        v = relative @ np.asarray(fit.rise_axis)
        top = v > fit.rise - 1.0e-7
        self.assertGreater(np.sum(top), 8)
        self.assertLess(float(np.ptp(v[top])), 1.0e-7)
        self.assertLess(v[0], 0.0)
        self.assertLess(v[-1], 0.0)


if __name__ == "__main__":
    unittest.main()
