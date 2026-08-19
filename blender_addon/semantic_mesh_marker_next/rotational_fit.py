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
        expected_rank = 4 if cone else 3
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
        cone_supported = (
            axial_span / radius >= thresholds.cone_minimum_axial_ratio
            and improvement >= thresholds.cone_minimum_improvement
            and profile_change >= 2.5 * noise
        )
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
