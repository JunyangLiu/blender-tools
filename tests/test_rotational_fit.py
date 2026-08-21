from pathlib import Path
import importlib.util
import math
import sys
import unittest

import numpy as np


MODULE_PATH = (
    Path(__file__).parents[1]
    / "blender_addon" / "semantic_mesh_marker_next" / "rotational_fit.py"
)
SPEC = importlib.util.spec_from_file_location("smrn_rotational_fit", MODULE_PATH)
ROTATIONAL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ROTATIONAL
SPEC.loader.exec_module(ROTATIONAL)


def basis(axis):
    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    helper = np.array((1.0, 0.0, 0.0))
    if abs(helper @ axis) > 0.85:
        helper = np.array((0.0, 0.0, 1.0))
    x = np.cross(axis, helper)
    x /= np.linalg.norm(x)
    y = np.cross(axis, x)
    return axis, x, y


def surface_samples(axis=(0.31, -0.82, 0.48), radius=3.2, slope=0.0,
                    angle_degrees=(-70.0, 80.0), inner=False, noise=0.0):
    axis, x, y = basis(axis)
    origin = np.array((4.5, -2.0, 7.25))
    points, normals = [], []
    rng = np.random.default_rng(2817)
    for axial in np.linspace(-5.0, 5.0, 7):
        for angle in np.linspace(math.radians(angle_degrees[0]),
                                 math.radians(angle_degrees[1]), 9):
            radial = math.cos(angle) * x + math.sin(angle) * y
            signed = radius + slope * axial
            point = origin + axial * axis + signed * radial
            normal = radial - slope * axis
            normal /= np.linalg.norm(normal)
            if inner:
                normal *= -1.0
            if noise:
                point += rng.normal(0.0, noise, 3)
                normal += rng.normal(0.0, noise * 0.08, 3)
                normal /= np.linalg.norm(normal)
            points.append(point)
            normals.append(normal)
    return np.asarray(points), np.asarray(normals), axis


class RotationalFitTests(unittest.TestCase):
    def test_too_few_samples_returns_a_structured_rejection(self):
        fit = ROTATIONAL.fit_rotational_surface([], [])
        self.assertEqual(fit.status, "needs_more_evidence")
        self.assertEqual(fit.sample_count, 0)

    def test_arbitrarily_rotated_partial_cylinder(self):
        points, normals, expected_axis = surface_samples(noise=0.006)
        fit = ROTATIONAL.fit_rotational_surface(points, normals)
        self.assertEqual(fit.status, "candidate_ready", fit.reason)
        self.assertEqual(fit.profile_kind, "cylinder")
        self.assertEqual(fit.surface_side, "outer")
        self.assertGreater(abs(np.dot(fit.axis, expected_axis)), 0.995)
        self.assertAlmostEqual(abs(fit.signed_radius_at_origin), 3.2, delta=0.04)
        self.assertEqual(fit.coverage_mode, "partial_arc")

    def test_cone_requires_measurable_profile_change(self):
        points, normals, expected_axis = surface_samples(radius=4.0, slope=0.22, noise=0.004)
        fit = ROTATIONAL.fit_rotational_surface(points, normals)
        self.assertEqual(fit.status, "candidate_ready", fit.reason)
        self.assertEqual(fit.profile_kind, "cone")
        self.assertGreater(abs(np.dot(fit.axis, expected_axis)), 0.995)
        self.assertAlmostEqual(abs(fit.signed_slope), 0.22, delta=0.025)

    def test_inner_bore_keeps_material_side_semantics(self):
        points, normals, _axis = surface_samples(radius=2.4, inner=True, noise=0.003)
        fit = ROTATIONAL.fit_rotational_surface(points, normals)
        self.assertEqual(fit.status, "candidate_ready", fit.reason)
        self.assertEqual(fit.surface_side, "inner")
        self.assertLess(fit.signed_radius_at_origin, 0.0)

    def test_full_rotation_needs_closed_angular_evidence(self):
        points, normals, _axis = surface_samples(angle_degrees=(-180.0, 180.0), noise=0.002)
        fit = ROTATIONAL.fit_rotational_surface(points, normals)
        self.assertEqual(fit.status, "candidate_ready", fit.reason)
        self.assertEqual(fit.coverage_mode, "full_rotation")

    def test_sparse_circumference_uses_point_plane_axis_and_normal_slope(self):
        expected_axis, x, y = basis((0.37, -0.51, 0.776))
        origin = np.array((11.0, -7.0, 3.5))
        radius = 5.8
        slope = -0.82
        points, normals = [], []
        for index, angle in enumerate(np.radians((-166, -104, -43, 18, 81, 142))):
            axial = (index - 2.5) * 0.012
            radial = math.cos(angle) * x + math.sin(angle) * y
            points.append(origin + axial * expected_axis + (radius + slope * axial) * radial)
            normal = radial - slope * expected_axis
            normals.append(normal / np.linalg.norm(normal))
        fit = ROTATIONAL.fit_rotational_surface(points, normals)
        self.assertEqual(fit.status, "candidate_ready", fit.reason)
        self.assertEqual(fit.profile_kind, "cone")
        self.assertEqual(fit.coverage_mode, "full_rotation")
        self.assertGreater(abs(np.dot(fit.axis, expected_axis)), 0.995)
        self.assertAlmostEqual(fit.signed_slope, slope, delta=0.04)

    def test_planar_strip_is_rejected_instead_of_inventing_large_radius(self):
        points = []
        normals = []
        for x in np.linspace(-3.0, 3.0, 6):
            for y in np.linspace(-6.0, 6.0, 7):
                points.append((x, y, 0.01 * x))
                normals.append((-0.01, 0.0, 0.99995))
        fit = ROTATIONAL.fit_rotational_surface(points, normals)
        self.assertEqual(fit.status, "needs_more_evidence")
        self.assertNotEqual(fit.reason, "")

    def test_partial_cone_strip_uses_two_boundary_rings_for_axis(self):
        expected_axis, x, y = basis((0.13, -0.42, 0.898))
        origin = np.array((17.0, 8.0, -4.0))
        slope = 0.74
        angles = np.radians(np.linspace(-62.0, 68.0, 10))

        def ring(axial):
            radius = 5.6 + slope * axial
            return np.asarray([
                origin + axial * expected_axis + radius * (math.cos(angle) * x + math.sin(angle) * y)
                for angle in angles
            ])

        points, normals = [], []
        for axial in np.linspace(-1.4, 1.4, 3):
            radius = 5.6 + slope * axial
            for angle in np.radians(np.linspace(-58.0, 64.0, 6)):
                radial = math.cos(angle) * x + math.sin(angle) * y
                points.append(origin + axial * expected_axis + radius * radial)
                normal = radial - slope * expected_axis
                normals.append(normal / np.linalg.norm(normal))

        fit = ROTATIONAL.fit_rotational_boundary_rings(
            ring(-1.4), ring(1.4), points, normals
        )
        self.assertEqual(fit.status, "candidate_ready", fit.reason)
        self.assertEqual(fit.profile_kind, "cone")
        self.assertGreater(abs(np.dot(fit.axis, expected_axis)), 0.999)
        self.assertAlmostEqual(abs(fit.signed_radius_at_origin), 5.6, delta=0.02)
        self.assertAlmostEqual(abs(fit.signed_slope), slope, delta=0.02)
        self.assertEqual(fit.coverage_mode, "partial_arc")


if __name__ == "__main__":
    unittest.main()
