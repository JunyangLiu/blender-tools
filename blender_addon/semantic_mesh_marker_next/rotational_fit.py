"""Robust, source-independent fitting for cylindrical and conical surface patches.

The fitter intentionally uses only the current task's points and normals.  It
does not inject object axes or vehicle-specific dimensions.  A signed radius
keeps convex outer surfaces distinct from concave inner bores.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np


EPSILON = 1.0e-10


@dataclass(frozen=True)
class FitThresholds:
    minimum_samples: int = 4
    maximum_candidates: int = 32
    huber_iterations: int = 8
    maximum_condition: float = 250.0
    maximum_relative_p90: float = 0.22
    maximum_normal_p90_degrees: float = 28.0
    minimum_angular_span_degrees: float = 12.0
    cone_minimum_axial_ratio: float = 0.18
    cone_minimum_improvement: float = 0.12


@dataclass(frozen=True)
class RotationalFit:
    status: str
    reason: str
    profile_kind: str
    surface_side: str
    axis: tuple[float, float, float]
    axis_origin: tuple[float, float, float]
    basis_x: tuple[float, float, float]
    basis_y: tuple[float, float, float]
    signed_radius_at_origin: float
    signed_slope: float
    axial_min: float
    axial_max: float
    angular_start: float
    angular_span: float
    angular_largest_gap: float
    coverage_mode: str
    point_residual_p50: float
    point_residual_p90: float
    relative_residual_p90: float
    normal_error_p90_degrees: float
    condition_number: float
    confidence: float
    sample_count: int

    def radius_at_axial(self, axial: float) -> float:
        return abs(self.signed_radius_at_origin + self.signed_slope * axial)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "profile_kind": self.profile_kind,
            "surface_side": self.surface_side,
            "axis": list(self.axis),
            "axis_origin": list(self.axis_origin),
            "basis_x": list(self.basis_x),
            "basis_y": list(self.basis_y),
            "signed_radius_at_origin": self.signed_radius_at_origin,
            "signed_slope": self.signed_slope,
            "axial_min": self.axial_min,
            "axial_max": self.axial_max,
            "angular_start": self.angular_start,
            "angular_span_degrees": math.degrees(self.angular_span),
            "angular_largest_gap_degrees": math.degrees(self.angular_largest_gap),
            "coverage_mode": self.coverage_mode,
            "point_residual_p50": self.point_residual_p50,
            "point_residual_p90": self.point_residual_p90,
            "relative_residual_p90": self.relative_residual_p90,
            "normal_error_p90_degrees": self.normal_error_p90_degrees,
            "condition_number": self.condition_number,
            "confidence": self.confidence,
            "sample_count": self.sample_count,
        }


def _as_rows(values: Iterable[Iterable[float]], name: str) -> np.ndarray:
    rows = tuple(tuple(row) for row in values)
    if not rows:
        return np.empty((0, 3), dtype=float)
    result = np.asarray(rows, dtype=float)
    if result.ndim != 2 or result.shape[1] != 3:
        raise ValueError(f"{name} must be an N by 3 array")
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{name} contains non-finite values")
    return result


def _unit(value: np.ndarray) -> np.ndarray | None:
    length = float(np.linalg.norm(value))
    return None if length <= EPSILON else value / length


def _canonical_axis(value: np.ndarray) -> np.ndarray | None:
    result = _unit(value)
    if result is None:
        return None
    pivot = int(np.argmax(np.abs(result)))
    return -result if result[pivot] < 0.0 else result


def _basis(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    helper = np.array((1.0, 0.0, 0.0))
    if abs(float(helper @ axis)) > 0.85:
        helper = np.array((0.0, 0.0, 1.0))
    basis_x = _unit(np.cross(axis, helper))
    basis_y = _unit(np.cross(axis, basis_x))
    return basis_x, basis_y


def _append_axis(result: list[np.ndarray], value: np.ndarray, maximum: int) -> None:
    axis = _canonical_axis(value)
    if axis is None or any(abs(float(axis @ existing)) > 0.997 for existing in result):
        return
    if len(result) < maximum:
        result.append(axis)


def candidate_axes(points: np.ndarray, normals: np.ndarray, maximum: int = 32) -> list[np.ndarray]:
    """Build data-derived axes without introducing object/global frame bias."""
    result: list[np.ndarray] = []
    centered_points = points - np.mean(points, axis=0)
    point_values, point_vectors = np.linalg.eigh(centered_points.T @ centered_points)
    for index in np.argsort(point_values)[::-1]:
        _append_axis(result, point_vectors[:, index], maximum)

    normalized = normals / np.maximum(np.linalg.norm(normals, axis=1)[:, None], EPSILON)
    centered_normals = normalized - np.mean(normalized, axis=0)
    normal_values, normal_vectors = np.linalg.eigh(centered_normals.T @ centered_normals)
    for index in np.argsort(normal_values):
        _append_axis(result, normal_vectors[:, index], maximum)

    # Crossed normal differences are useful for narrow conical patches because
    # their common axial normal component cancels before the cross product.
    step = max(1, len(normalized) // 8)
    sampled = normalized[::step][:10]
    for first in range(len(sampled)):
        for second in range(first):
            _append_axis(result, np.cross(sampled[first], sampled[second]), maximum)
            _append_axis(
                result,
                np.cross(sampled[first] - np.mean(normalized, axis=0),
                         sampled[second] - np.mean(normalized, axis=0)),
                maximum,
            )
    return result


def _robust_linear(design: np.ndarray, values: np.ndarray, groups: int, iterations: int):
    weights = np.ones(groups, dtype=float)
    solution = np.zeros(design.shape[1], dtype=float)
    for _iteration in range(iterations):
        row_weights = np.repeat(np.sqrt(weights), 2)
        weighted_design = design * row_weights[:, None]
        weighted_values = values * row_weights
        solution, _residuals, rank, singular = np.linalg.lstsq(
            weighted_design, weighted_values, rcond=None
        )
        vectors = (design @ solution - values).reshape(groups, 2)
        residual = np.linalg.norm(vectors, axis=1)
        median = float(np.median(residual))
        scale = 1.4826 * float(np.median(np.abs(residual - median))) + EPSILON
        cutoff = max(median + 1.5 * scale, EPSILON)
        weights = np.minimum(1.0, cutoff / np.maximum(residual, EPSILON))
    condition = float("inf") if singular[-1] <= EPSILON else float(singular[0] / singular[-1])
    return solution, residual, int(rank), condition


def _design(radial_directions: np.ndarray, axial: np.ndarray, cone: bool):
    columns = 4 if cone else 3
    design = np.zeros((len(axial) * 2, columns), dtype=float)
    values = np.zeros(len(axial) * 2, dtype=float)
    for index, (direction, z_value) in enumerate(zip(radial_directions, axial)):
        row = index * 2
        design[row, 0] = 1.0
        design[row + 1, 1] = 1.0
        design[row, 2] = direction[0]
        design[row + 1, 2] = direction[1]
        if cone:
            design[row, 3] = direction[0] * z_value
            design[row + 1, 3] = direction[1] * z_value
    return design, values


def _angle_interval(angles: np.ndarray) -> tuple[float, float, float, str]:
    ordered = np.sort(np.mod(angles, 2.0 * math.pi))
    if len(ordered) < 2:
        return 0.0, 0.0, 2.0 * math.pi, "partial_arc"
    gaps = np.diff(np.r_[ordered, ordered[0] + 2.0 * math.pi])
    gap_index = int(np.argmax(gaps))
    largest_gap = float(gaps[gap_index])
    start = float(ordered[(gap_index + 1) % len(ordered)])
    span = 2.0 * math.pi - largest_gap
    other_gaps = np.delete(gaps, gap_index)
    other_gaps = other_gaps[other_gaps > math.radians(0.05)]
    typical = float(np.median(other_gaps)) if len(other_gaps) else largest_gap
    closure_limit = max(math.radians(12.0), 2.8 * typical)
    # A closed coarse ring legitimately has a gap equal to its normal facet
    # step; comparing the largest gap with the other steps is more stable than
    # demanding an arbitrary number of occupied bins.
    full = len(ordered) >= 6 and largest_gap <= closure_limit
    return start, (2.0 * math.pi if full else span), largest_gap, ("full_rotation" if full else "partial_arc")


def _fit_sparse_circumference(points: np.ndarray, normals: np.ndarray,
                              thresholds: FitThresholds):
    """Fit a broad, axially narrow ring without letting its axis tilt away."""
    if len(points) < 6:
        return None
    origin = np.mean(points, axis=0)
    centered = points - origin
    values, vectors = np.linalg.eigh(centered.T @ centered)
    order = np.argsort(values)
    smallest, middle, largest = (float(values[index]) for index in order)
    if largest <= EPSILON:
        return None
    # This path is only for a well-spread ring in one source-derived plane.
    if math.sqrt(max(smallest, 0.0) / max(middle, EPSILON)) > 0.22:
        return None
    if math.sqrt(max(middle, 0.0) / largest) < 0.42:
        return None
    axis = _canonical_axis(vectors[:, order[0]])
    if axis is None:
        return None
    basis_x, basis_y = _basis(axis)
    plane = np.column_stack((centered @ basis_x, centered @ basis_y))
    circle_design = np.column_stack((2.0 * plane[:, 0], 2.0 * plane[:, 1], np.ones(len(points))))
    circle_values = np.sum(np.square(plane), axis=1)
    circle, _residuals, rank, singular = np.linalg.lstsq(circle_design, circle_values, rcond=None)
    if rank < 3:
        return None
    center_2d = circle[:2]
    radius_squared = float(circle[2] + center_2d @ center_2d)
    if radius_squared <= EPSILON:
        return None
    radius = math.sqrt(radius_squared)
    radial_2d = plane - center_2d
    radial_size = np.linalg.norm(radial_2d, axis=1)
    geometry_direction_2d = radial_2d / np.maximum(radial_size[:, None], EPSILON)
    angles = np.arctan2(geometry_direction_2d[:, 1], geometry_direction_2d[:, 0])
    start, span, largest_gap, coverage_mode = _angle_interval(angles)
    # A broad partial circumference still determines its circle plane and
    # center reliably, but it must remain partial instead of inventing the
    # unmarked closing sector.
    if coverage_mode != "full_rotation" and span < math.radians(180.0):
        return None

    unit_normals = normals / np.maximum(np.linalg.norm(normals, axis=1)[:, None], EPSILON)
    normal_axial = unit_normals @ axis
    normal_radial_3d = unit_normals - normal_axial[:, None] * axis
    normal_radial_length = np.linalg.norm(normal_radial_3d, axis=1)
    if float(np.quantile(normal_radial_length, 0.25)) < 0.30:
        return None
    geometry_direction_3d = (
        geometry_direction_2d[:, 0, None] * basis_x
        + geometry_direction_2d[:, 1, None] * basis_y
    )
    radial_alignment = np.sum(normal_radial_3d * geometry_direction_3d, axis=1)
    orientation = 1.0 if float(np.median(radial_alignment)) >= 0.0 else -1.0
    if float(np.quantile(np.abs(radial_alignment) / normal_radial_length, 0.25)) < 0.72:
        return None
    slope_samples = -normal_axial / np.maximum(normal_radial_length, EPSILON)
    signed_slope = float(np.median(slope_samples))
    slope_deviation = float(np.quantile(np.abs(slope_samples - signed_slope), 0.90))
    if slope_deviation > max(0.08, abs(signed_slope) * 0.20):
        return None
    cone = abs(signed_slope) >= 0.04
    if not cone:
        signed_slope = 0.0
    predicted = orientation * geometry_direction_3d - signed_slope * axis
    predicted /= np.maximum(np.linalg.norm(predicted, axis=1)[:, None], EPSILON)
    normal_error = np.degrees(np.arccos(np.clip(
        np.sum(predicted * unit_normals, axis=1), -1.0, 1.0
    )))
    radial_residual = np.abs(radial_size - radius)
    p50 = float(np.quantile(radial_residual, 0.50))
    p90 = float(np.quantile(radial_residual, 0.90))
    relative_p90 = p90 / max(radius, EPSILON)
    normal_p90 = float(np.quantile(normal_error, 0.90))
    condition = float("inf") if singular[-1] <= EPSILON else float(singular[0] / singular[-1])
    score = relative_p90 + normal_p90 / 90.0 + math.log1p(condition) / 40.0
    axial = centered @ axis
    center_world = origin + center_2d[0] * basis_x + center_2d[1] * basis_y
    return {
        "cone": cone,
        "solution": np.asarray((center_2d[0], center_2d[1], orientation * radius, signed_slope)),
        "residual": radial_residual,
        "condition": condition,
        "p50": p50,
        "p90": p90,
        "relative_p90": relative_p90,
        "normal_p90": normal_p90,
        "score": score,
        "start": start,
        "span": span,
        "largest_gap": largest_gap,
        "coverage_mode": coverage_mode,
        "center_2d": center_2d,
        "normal_constrained": cone,
        "normal_slope_deviation": slope_deviation,
        "axis": axis,
        "origin": center_world,
        "basis_x": basis_x,
        "basis_y": basis_y,
        "signed_radius": orientation * radius,
        "signed_slope": signed_slope,
        "axial_min": float(np.min(axial)),
        "axial_max": float(np.max(axial)),
    }


def _fit_one_axis(axis: np.ndarray, points: np.ndarray, normals: np.ndarray,
                  thresholds: FitThresholds):
    origin = np.mean(points, axis=0)
    basis_x, basis_y = _basis(axis)
    relative = points - origin
    axial = relative @ axis
    plane_points = np.column_stack((relative @ basis_x, relative @ basis_y))
    normal_length = np.linalg.norm(normals, axis=1)
    unit_normals = normals / np.maximum(normal_length[:, None], EPSILON)
    normal_axial = unit_normals @ axis
    radial_3d = unit_normals - normal_axial[:, None] * axis
    radial_length = np.linalg.norm(radial_3d, axis=1)
    if float(np.quantile(radial_length, 0.25)) < 0.30:
        return None
    radial_3d /= np.maximum(radial_length[:, None], EPSILON)
    directions = np.column_stack((radial_3d @ basis_x, radial_3d @ basis_y))

    fits = []
    for cone in (False, True):
        design, values = _design(directions, axial, cone)
        values[0::2] = plane_points[:, 0]
        values[1::2] = plane_points[:, 1]
        solution, residual, rank, condition = _robust_linear(
            design, values, len(points), thresholds.huber_iterations
        )
        normal_constrained = False
        normal_slope_deviation = float("inf")
        expected_rank = 4 if cone else 3
        if cone:
            # A complete marked circumference can be axially narrow: its
            # points determine the axis/circle while its normals determine the
            # local cone slope.  A free four-parameter cone is rank-deficient
            # in that case and used to drift onto an oblique false axis.
            radial_scale = max(
                float(np.median(np.linalg.norm(
                    plane_points - np.mean(plane_points, axis=0), axis=1
                ))), EPSILON
            )
            slope_samples = -normal_axial / np.maximum(radial_length, EPSILON)
            normal_slope = float(np.median(slope_samples))
            normal_slope_deviation = float(np.quantile(
                np.abs(slope_samples - normal_slope), 0.90
            ))
            slope_limit = max(0.08, abs(normal_slope) * 0.20)
            if (
                float(np.ptp(axial)) / radial_scale < thresholds.cone_minimum_axial_ratio
                and abs(normal_slope) >= 0.04
                and normal_slope_deviation <= slope_limit
            ):
                design, adjusted = _design(directions, axial, False)
                corrected = plane_points - (
                    normal_slope * axial[:, None] * directions
                )
                adjusted[0::2] = corrected[:, 0]
                adjusted[1::2] = corrected[:, 1]
                fixed, residual, rank, condition = _robust_linear(
                    design, adjusted, len(points), thresholds.huber_iterations
                )
                solution = np.r_[fixed, normal_slope]
                expected_rank = 3
                normal_constrained = True
        if rank < expected_rank:
            continue
        signed_radius = float(solution[2])
        signed_slope = float(solution[3]) if cone else 0.0
        radii = signed_radius + signed_slope * axial
        if np.min(np.abs(radii)) <= EPSILON or np.any(np.sign(radii) != np.sign(signed_radius)):
            continue
        center_2d = solution[:2]
        radial_from_center = plane_points - center_2d
        radial_size = np.linalg.norm(radial_from_center, axis=1)
        geometry_direction = radial_from_center / np.maximum(radial_size[:, None], EPSILON)
        orientation = 1.0 if signed_radius >= 0.0 else -1.0
        predicted_3d = (
            geometry_direction[:, 0, None] * basis_x
            + geometry_direction[:, 1, None] * basis_y
            - (orientation * signed_slope) * axis
        )
        predicted_3d *= orientation
        predicted_3d /= np.maximum(np.linalg.norm(predicted_3d, axis=1)[:, None], EPSILON)
        dots = np.clip(np.sum(predicted_3d * unit_normals, axis=1), -1.0, 1.0)
        normal_error = np.degrees(np.arccos(dots))
        angles = np.arctan2(radial_from_center[:, 1], radial_from_center[:, 0])
        start, span, largest_gap, coverage_mode = _angle_interval(angles)
        p50 = float(np.quantile(residual, 0.50))
        p90 = float(np.quantile(residual, 0.90))
        scale_radius = max(float(np.median(np.abs(radii))), EPSILON)
        relative_p90 = p90 / scale_radius
        normal_p90 = float(np.quantile(normal_error, 0.90))
        score = relative_p90 + normal_p90 / 90.0 + math.log1p(condition) / 40.0
        fits.append({
            "cone": cone, "solution": solution, "residual": residual,
            "condition": condition, "p50": p50, "p90": p90,
            "relative_p90": relative_p90, "normal_p90": normal_p90,
            "score": score, "start": start, "span": span,
            "largest_gap": largest_gap, "coverage_mode": coverage_mode,
            "center_2d": center_2d,
            "normal_constrained": normal_constrained,
            "normal_slope_deviation": normal_slope_deviation,
        })
    if not fits:
        return None
    cylinder = next((item for item in fits if not item["cone"]), None)
    cone = next((item for item in fits if item["cone"]), None)
    chosen = cylinder or cone
    if cylinder is not None and cone is not None:
        axial_span = float(np.ptp(axial))
        radius = max(abs(float(cone["solution"][2])), EPSILON)
        improvement = (cylinder["score"] - cone["score"]) / max(cylinder["score"], EPSILON)
        profile_change = abs(float(cone["solution"][3])) * axial_span
        noise = max(cone["p90"], EPSILON)
        standard_cone_supported = (
            axial_span / radius >= thresholds.cone_minimum_axial_ratio
            and improvement >= thresholds.cone_minimum_improvement
            and profile_change >= 2.5 * noise
        )
        circumference_cone_supported = (
            cone["normal_constrained"]
            and cone["coverage_mode"] == "full_rotation"
            and improvement >= thresholds.cone_minimum_improvement
            and cone["normal_p90"] <= thresholds.maximum_normal_p90_degrees
        )
        cone_supported = standard_cone_supported or circumference_cone_supported
        chosen = cone if cone_supported else cylinder

    center_world = origin + chosen["center_2d"][0] * basis_x + chosen["center_2d"][1] * basis_y
    signed_radius = float(chosen["solution"][2])
    signed_slope = float(chosen["solution"][3]) if chosen["cone"] else 0.0
    # Moving the axis origin onto the fitted center leaves axial coordinates unchanged.
    return {
        **chosen,
        "axis": axis,
        "origin": center_world,
        "basis_x": basis_x,
        "basis_y": basis_y,
        "signed_radius": signed_radius,
        "signed_slope": signed_slope,
        "axial_min": float(np.min(axial)),
        "axial_max": float(np.max(axial)),
    }


def fit_rotational_surface(points: Iterable[Iterable[float]], normals: Iterable[Iterable[float]],
                           thresholds: FitThresholds | None = None) -> RotationalFit:
    thresholds = thresholds or FitThresholds()
    point_rows = _as_rows(points, "points")
    normal_rows = _as_rows(normals, "normals")
    if len(point_rows) != len(normal_rows):
        raise ValueError("points and normals must have equal length")
    if len(point_rows) < thresholds.minimum_samples:
        return _failed("至少需要 4 个当前源表面样本", len(point_rows))
    axes = candidate_axes(point_rows, normal_rows, thresholds.maximum_candidates)
    fits = [
        fit for fit in (
            _fit_one_axis(axis, point_rows, normal_rows, thresholds) for axis in axes
        ) if fit is not None
    ]
    circumference = _fit_sparse_circumference(point_rows, normal_rows, thresholds)
    if circumference is not None:
        fits.append(circumference)
    if not fits:
        return _failed("标记法线不足以建立稳定旋转轴", len(point_rows))
    best = min(fits, key=lambda item: item["score"])
    reasons = []
    if best["condition"] > thresholds.maximum_condition:
        reasons.append("局部圆弧条件数过高")
    if best["relative_p90"] > thresholds.maximum_relative_p90:
        reasons.append("点到旋转曲面的误差过大")
    if best["normal_p90"] > thresholds.maximum_normal_p90_degrees:
        reasons.append("源面法线与旋转曲面不一致")
    if best["span"] < math.radians(thresholds.minimum_angular_span_degrees):
        reasons.append("圆周方向证据太窄")
    ready = not reasons
    confidence = max(0.0, min(1.0,
        1.0
        - 1.4 * best["relative_p90"]
        - best["normal_p90"] / 120.0
        - min(math.log10(max(best["condition"], 1.0)) / 12.0, 0.25)
    ))
    return RotationalFit(
        status="candidate_ready" if ready else "needs_more_evidence",
        reason="；".join(reasons) if reasons else "当前标记支持稳定的旋转曲面候选",
        profile_kind="cone" if best["cone"] else "cylinder",
        surface_side="outer" if best["signed_radius"] >= 0.0 else "inner",
        axis=tuple(float(value) for value in best["axis"]),
        axis_origin=tuple(float(value) for value in best["origin"]),
        basis_x=tuple(float(value) for value in best["basis_x"]),
        basis_y=tuple(float(value) for value in best["basis_y"]),
        signed_radius_at_origin=float(best["signed_radius"]),
        signed_slope=float(best["signed_slope"]),
        axial_min=float(best["axial_min"]), axial_max=float(best["axial_max"]),
        angular_start=float(best["start"]), angular_span=float(best["span"]),
        angular_largest_gap=float(best["largest_gap"]),
        coverage_mode=str(best["coverage_mode"]),
        point_residual_p50=float(best["p50"]), point_residual_p90=float(best["p90"]),
        relative_residual_p90=float(best["relative_p90"]),
        normal_error_p90_degrees=float(best["normal_p90"]),
        condition_number=float(best["condition"]), confidence=confidence,
        sample_count=len(point_rows),
    )


def fit_rotational_boundary_rings(
    first_ring: Iterable[Iterable[float]],
    second_ring: Iterable[Iterable[float]],
    surface_points: Iterable[Iterable[float]],
    surface_normals: Iterable[Iterable[float]],
) -> RotationalFit:
    """Fit a frustum strip from its two source-derived circumferential boundaries.

    Unlike the generic normal-only fitter, this path has a topological proof of
    the axial direction: both ordered boundary chains lie in planes normal to
    the rotational axis.  It is therefore stable for partial cone arcs.
    """
    ring_a = _as_rows(first_ring, "first_ring")
    ring_b = _as_rows(second_ring, "second_ring")
    points = _as_rows(surface_points, "surface_points")
    normals = _as_rows(surface_normals, "surface_normals")
    if len(ring_a) < 4 or len(ring_b) < 4 or len(points) < 8 or len(normals) < 4:
        return _failed("上下圆周边界证据不足", len(points))

    tangents = np.vstack((np.diff(ring_a, axis=0), np.diff(ring_b, axis=0)))
    tangent_lengths = np.linalg.norm(tangents, axis=1)
    tangents = tangents[tangent_lengths > EPSILON]
    if len(tangents) < 6:
        return _failed("圆周边界连续边不足", len(points))
    tangent_covariance = tangents.T @ tangents
    tangent_values, tangent_vectors = np.linalg.eigh(tangent_covariance)
    axis = _canonical_axis(tangent_vectors[:, int(np.argmin(tangent_values))])
    if axis is None:
        return _failed("无法从两条圆周边界确定旋转轴", len(points))
    plane_condition = float(tangent_values[1] / max(tangent_values[0], EPSILON))
    if plane_condition < 12.0:
        return _failed("圆周边界不足以唯一确定旋转轴", len(points))

    basis_x, basis_y = _basis(axis)
    reference = np.mean(np.vstack((ring_a, ring_b)), axis=0)

    def circle(rows):
        relative = rows - reference
        x = relative @ basis_x
        y = relative @ basis_y
        design = np.column_stack((2.0 * x, 2.0 * y, np.ones(len(rows))))
        values = x * x + y * y
        solution, _residuals, rank, singular = np.linalg.lstsq(design, values, rcond=None)
        if rank < 3 or singular[-1] <= EPSILON:
            return None
        cx, cy, constant = (float(value) for value in solution)
        radius_squared = constant + cx * cx + cy * cy
        if radius_squared <= EPSILON:
            return None
        axial = float(np.mean(relative @ axis))
        center = reference + cx * basis_x + cy * basis_y + axial * axis
        radius = math.sqrt(radius_squared)
        residual = np.abs(np.hypot(x - cx, y - cy) - radius)
        return center, radius, axial, residual, float(singular[0] / singular[-1])

    circle_a, circle_b = circle(ring_a), circle(ring_b)
    if circle_a is None or circle_b is None:
        return _failed("局部圆周边界无法稳定拟圆", len(points))
    center_a, radius_a, axial_a, residual_a, condition_a = circle_a
    center_b, radius_b, axial_b, residual_b, condition_b = circle_b
    axial_delta = axial_b - axial_a
    if abs(axial_delta) <= EPSILON:
        return _failed("两条圆周边界没有可测轴向间距", len(points))
    if axial_delta < 0.0:
        axis = -axis
        basis_y = -basis_y
        axial_a, axial_b = -axial_a, -axial_b
        axial_delta = -axial_delta

    lateral_center = 0.5 * (
        center_a - axis * float((center_a - reference) @ axis)
        + center_b - axis * float((center_b - reference) @ axis)
    )
    axial_middle = 0.5 * (axial_a + axial_b)
    origin = lateral_center + axis * axial_middle
    signed_slope = (radius_b - radius_a) / axial_delta
    radius_at_origin = 0.5 * (radius_a + radius_b)

    relative = points - origin
    axial = relative @ axis
    radial_vectors = relative - axial[:, None] * axis[None, :]
    radii = np.linalg.norm(radial_vectors, axis=1)
    predicted = radius_at_origin + signed_slope * axial
    residuals = np.abs(radii - predicted)
    relative_p90 = float(np.quantile(residuals, 0.90) / max(radius_at_origin, EPSILON))

    normalized_normals = normals / np.maximum(np.linalg.norm(normals, axis=1)[:, None], EPSILON)
    radial_unit = radial_vectors / np.maximum(radii[:, None], EPSILON)
    expected = radial_unit - signed_slope * axis[None, :]
    expected /= np.maximum(np.linalg.norm(expected, axis=1)[:, None], EPSILON)
    orientation = 1.0 if float(np.mean(np.sum(expected * normalized_normals, axis=1))) >= 0.0 else -1.0
    dots = np.clip(np.sum((orientation * expected) * normalized_normals, axis=1), -1.0, 1.0)
    normal_errors = np.degrees(np.arccos(dots))

    x = relative @ basis_x
    y = relative @ basis_y
    angles = np.sort(np.mod(np.arctan2(y, x), 2.0 * math.pi))
    gaps = np.diff(np.r_[angles, angles[0] + 2.0 * math.pi])
    gap_index = int(np.argmax(gaps))
    angular_start = float(angles[(gap_index + 1) % len(angles)])
    angular_span = float(2.0 * math.pi - gaps[gap_index])
    coverage_mode = "full_rotation" if angular_span >= 0.96 * 2.0 * math.pi else "partial_arc"
    if coverage_mode == "full_rotation":
        angular_span = 2.0 * math.pi

    ring_p90 = float(np.quantile(np.r_[residual_a, residual_b], 0.90))
    normal_p90 = float(np.quantile(normal_errors, 0.90))
    reasons = []
    if relative_p90 > 0.08 or ring_p90 / max(radius_at_origin, EPSILON) > 0.05:
        reasons.append("两条源圆周边界的拟圆残差过大")
    if normal_p90 > 22.0:
        reasons.append("源面法线与边界确定的旋转面不一致")
    ready = not reasons
    condition = max(condition_a, condition_b, 1.0 / max(plane_condition, EPSILON))
    confidence = max(0.0, min(1.0, 1.0 - 2.0 * relative_p90 - normal_p90 / 90.0))
    return RotationalFit(
        status="candidate_ready" if ready else "needs_more_evidence",
        reason="；".join(reasons) if reasons else "两条源圆周边界共同确定了旋转轴和尺寸",
        profile_kind="cone" if abs(signed_slope) * axial_delta > 2.5 * ring_p90 else "cylinder",
        surface_side="outer" if orientation > 0.0 else "inner",
        axis=tuple(float(value) for value in axis),
        axis_origin=tuple(float(value) for value in origin),
        basis_x=tuple(float(value) for value in basis_x),
        basis_y=tuple(float(value) for value in basis_y),
        signed_radius_at_origin=float(orientation * radius_at_origin),
        signed_slope=float(orientation * signed_slope),
        axial_min=float(np.min(axial)), axial_max=float(np.max(axial)),
        angular_start=angular_start, angular_span=angular_span,
        angular_largest_gap=float(gaps[gap_index]), coverage_mode=coverage_mode,
        point_residual_p50=float(np.quantile(residuals, 0.50)),
        point_residual_p90=float(np.quantile(residuals, 0.90)),
        relative_residual_p90=relative_p90,
        normal_error_p90_degrees=normal_p90,
        condition_number=condition, confidence=confidence, sample_count=len(points),
    )


def _failed(reason: str, count: int) -> RotationalFit:
    return RotationalFit(
        status="needs_more_evidence", reason=reason, profile_kind="unknown",
        surface_side="unknown", axis=(0.0, 0.0, 1.0), axis_origin=(0.0, 0.0, 0.0),
        basis_x=(1.0, 0.0, 0.0), basis_y=(0.0, 1.0, 0.0),
        signed_radius_at_origin=0.0, signed_slope=0.0,
        axial_min=0.0, axial_max=0.0, angular_start=0.0, angular_span=0.0,
        angular_largest_gap=2.0 * math.pi, coverage_mode="partial_arc",
        point_residual_p50=float("inf"), point_residual_p90=float("inf"),
        relative_residual_p90=float("inf"), normal_error_p90_degrees=180.0,
        condition_number=float("inf"), confidence=0.0, sample_count=count,
    )
