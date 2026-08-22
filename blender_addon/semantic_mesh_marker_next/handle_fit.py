"""Source-independent fitting for one open tubular grab handle.

The final coordinate frame is solved before any path parameters are measured.
This avoids the legacy failure where axes were rotated after span, baseline and
rise had already been fitted in a different frame.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np


EPSILON = 1.0e-10


@dataclass(frozen=True)
class HandleFitThresholds:
    minimum_target_samples: int = 7
    minimum_support_samples: int = 2
    maximum_support_angle_degrees: float = 28.0
    maximum_relative_path_p90: float = 0.16
    maximum_plane_thickness_ratio: float = 0.42
    minimum_span_to_section: float = 4.0
    minimum_rise_to_section: float = 1.25
    minimum_corridor_retention: float = 0.80


@dataclass(frozen=True)
class HandleFit:
    status: str
    reason: str
    path_kind: str
    origin: tuple[float, float, float]
    span_axis: tuple[float, float, float]
    rise_axis: tuple[float, float, float]
    plane_normal: tuple[float, float, float]
    half_span: float
    rise: float
    corner_radius: float
    radius_hint: float
    path_residual_p50: float
    path_residual_p90: float
    relative_path_p90: float
    corridor_retention: float
    plane_thickness_ratio: float
    longitudinal_ratio: float
    support_angle_before_signed_degrees: float | None
    support_angle_after_degrees: float | None
    support_used: bool
    confidence: float
    sample_count: int
    support_sample_count: int

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "path_kind": self.path_kind,
            "origin": list(self.origin),
            "span_axis": list(self.span_axis),
            "rise_axis": list(self.rise_axis),
            "plane_normal": list(self.plane_normal),
            "half_span": self.half_span,
            "rise": self.rise,
            "corner_radius": self.corner_radius,
            "radius_hint": self.radius_hint,
            "path_residual_p50": self.path_residual_p50,
            "path_residual_p90": self.path_residual_p90,
            "relative_path_p90": self.relative_path_p90,
            "corridor_retention": self.corridor_retention,
            "plane_thickness_ratio": self.plane_thickness_ratio,
            "longitudinal_ratio": self.longitudinal_ratio,
            "support_angle_before_signed_degrees": self.support_angle_before_signed_degrees,
            "support_angle_after_degrees": self.support_angle_after_degrees,
            "support_used": self.support_used,
            "confidence": self.confidence,
            "sample_count": self.sample_count,
            "support_sample_count": self.support_sample_count,
        }


def _rows(values: Iterable[Iterable[float]], name: str) -> np.ndarray:
    rows = tuple(tuple(value) for value in values)
    if not rows:
        return np.empty((0, 3), dtype=float)
    result = np.asarray(rows, dtype=float)
    if result.ndim != 2 or result.shape[1] != 3 or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must be a finite N by 3 array")
    return result


def _unit(value: np.ndarray) -> np.ndarray | None:
    length = float(np.linalg.norm(value))
    return None if length <= EPSILON else value / length


def _canonical(value: np.ndarray) -> np.ndarray:
    result = _unit(value)
    if result is None:
        raise ValueError("zero-length axis")
    pivot = int(np.argmax(np.abs(result)))
    return -result if result[pivot] < 0.0 else result


def _principal(rows: np.ndarray):
    centered = rows - np.mean(rows, axis=0)
    values, vectors = np.linalg.eigh(centered.T @ centered / max(1, len(rows) - 1))
    return values, vectors


def _point_segment_distances(points: np.ndarray, first: np.ndarray, second: np.ndarray):
    direction = second - first
    denominator = float(direction @ direction)
    if denominator <= EPSILON:
        return np.linalg.norm(points - first, axis=1)
    factor = np.clip(((points - first) @ direction) / denominator, 0.0, 1.0)
    nearest = first + factor[:, None] * direction
    return np.linalg.norm(points - nearest, axis=1)


def _polyline_distances(points: np.ndarray, path: np.ndarray):
    result = np.full(len(points), np.inf, dtype=float)
    for first, second in zip(path[:-1], path[1:]):
        result = np.minimum(result, _point_segment_distances(points, first, second))
    return result


def polyline_nearest(points: np.ndarray, path: np.ndarray):
    """Return nearest points, unit tangents and distances for a 3D polyline."""
    values = np.asarray(points, dtype=float)
    line = np.asarray(path, dtype=float)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError("points must be an N by 3 array")
    if line.ndim != 2 or line.shape[1] != 3 or len(line) < 2:
        raise ValueError("path must contain at least two 3D points")
    best_squared = np.full(len(values), np.inf, dtype=float)
    nearest = np.zeros_like(values)
    tangents = np.zeros_like(values)
    for first, second in zip(line[:-1], line[1:]):
        direction = second - first
        denominator = float(direction @ direction)
        if denominator <= EPSILON:
            continue
        factor = np.clip(((values - first) @ direction) / denominator, 0.0, 1.0)
        candidate = first + factor[:, None] * direction
        squared = np.sum(np.square(values - candidate), axis=1)
        replace = squared < best_squared
        best_squared[replace] = squared[replace]
        nearest[replace] = candidate[replace]
        tangents[replace] = direction / math.sqrt(denominator)
    return nearest, tangents, np.sqrt(best_squared)


def _circle_from_three(a: np.ndarray, b: np.ndarray, c: np.ndarray):
    """Circumcircle for three points, or None when they are collinear."""
    twice_area = 2.0 * float(np.cross(b - a, c - a))
    if abs(twice_area) <= EPSILON:
        return None
    aa, bb, cc = float(a @ a), float(b @ b), float(c @ c)
    center = np.asarray((
        (aa * (b[1] - c[1]) + bb * (c[1] - a[1]) + cc * (a[1] - b[1])) / twice_area,
        (aa * (c[0] - b[0]) + bb * (a[0] - c[0]) + cc * (b[0] - a[0])) / twice_area,
    ))
    return center, float(np.linalg.norm(center - a))


def minimum_enclosing_circle(points: np.ndarray):
    """Deterministic smallest circle enclosing finite 2D evidence points.

    A fixed pseudo-random order keeps the expected incremental complexity low
    while producing byte-for-byte stable results for the same evidence.
    """
    values = np.asarray(points, dtype=float)
    if values.ndim != 2 or values.shape[1] != 2 or not len(values):
        raise ValueError("points must be a non-empty N by 2 array")
    if not np.all(np.isfinite(values)):
        raise ValueError("points must be finite")
    order = np.random.default_rng(0).permutation(len(values))
    rows = values[order]
    center = rows[0].copy()
    radius = 0.0
    tolerance = 1.0e-10
    for i, point in enumerate(rows):
        if float(np.linalg.norm(point - center)) <= radius + tolerance:
            continue
        center, radius = point.copy(), 0.0
        for j in range(i):
            other = rows[j]
            if float(np.linalg.norm(other - center)) <= radius + tolerance:
                continue
            center = (point + other) * 0.5
            radius = float(np.linalg.norm(point - other)) * 0.5
            for k in range(j):
                third = rows[k]
                if float(np.linalg.norm(third - center)) <= radius + tolerance:
                    continue
                circle = _circle_from_three(point, other, third)
                if circle is not None:
                    center, radius = circle
    # Numerical guard: never report a radius smaller than an input distance.
    radius = max(radius, float(np.max(np.linalg.norm(values - center, axis=1))))
    return center, radius


def path_points_2d(path_kind: str, half_span: float, rise: float,
                   corner_radius: float = 0.0, samples: int = 96) -> np.ndarray:
    """Return an endpoint-to-endpoint centerline in the fitted local frame."""
    if path_kind == "semi_ellipse":
        theta = np.linspace(math.pi, 0.0, max(16, samples) + 1)
        return np.column_stack((half_span * np.cos(theta), rise * np.sin(theta)))
    if path_kind != "flat_top":
        raise ValueError(f"unsupported handle path: {path_kind}")
    corner = min(max(corner_radius, EPSILON), half_span * 0.48, rise * 0.80)
    leg_count = max(5, samples // 8)
    corner_count = max(8, samples // 6)
    top_count = max(12, samples // 3)
    result = []
    for value in np.linspace(0.0, rise - corner, leg_count, endpoint=False):
        result.append((-half_span, value))
    center_y = rise - corner
    for angle in np.linspace(math.pi, math.pi * 0.5, corner_count, endpoint=False):
        result.append((-half_span + corner + corner * math.cos(angle),
                       center_y + corner * math.sin(angle)))
    for value in np.linspace(-half_span + corner, half_span - corner, top_count, endpoint=False):
        result.append((value, rise))
    for angle in np.linspace(math.pi * 0.5, 0.0, corner_count, endpoint=False):
        result.append((half_span - corner + corner * math.cos(angle),
                       center_y + corner * math.sin(angle)))
    for value in np.linspace(rise - corner, 0.0, leg_count):
        result.append((half_span, value))
    return np.asarray(result, dtype=float)


def path_points_world(fit: HandleFit, samples: int = 96,
                      endpoint_penetrations=(0.0, 0.0)) -> np.ndarray:
    local = path_points_2d(
        fit.path_kind, fit.half_span, fit.rise, fit.corner_radius, samples
    )
    left, right = (float(endpoint_penetrations[0]), float(endpoint_penetrations[1]))
    if left > 0.0:
        local = np.vstack(((-fit.half_span, -left), local))
    if right > 0.0:
        local = np.vstack((local, (fit.half_span, -right)))
    origin = np.asarray(fit.origin, dtype=float)
    span = np.asarray(fit.span_axis, dtype=float)
    rise = np.asarray(fit.rise_axis, dtype=float)
    return origin + local[:, :1] * span + local[:, 1:] * rise


def _fit_path(local: np.ndarray, radius_hint: float):
    u, v = local[:, 0], local[:, 1]
    minimum_u, maximum_u = np.quantile(u, (0.04, 0.96))
    center_u = float((minimum_u + maximum_u) * 0.5)
    half_span = float((maximum_u - minimum_u) * 0.5)
    if half_span <= EPSILON:
        return None
    centered_u = u - center_u
    terminals = np.abs(centered_u) >= half_span * 0.62
    middle = np.abs(centered_u) <= half_span * 0.58
    # A low-poly flat top can be one long source face while both legs and
    # corners are split into dozens of small faces.  In that valid case the
    # semantic marks contain only one central path sample.  Requiring two
    # central faces rejects good marking purely because of tessellation.
    # One central sample is sufficient to propose the top envelope; the
    # downstream path residual, plane, span/rise, and corridor gates still
    # have to validate the complete handle before it can become a candidate.
    if np.sum(terminals) < 2 or np.sum(middle) < 1:
        return None
    # Terminal samples contain both the feet and the rising corner/leg.  A
    # central quantile therefore pulls the installation baseline upward when
    # marks are sparse.  Use the low terminal envelope and the high middle
    # envelope; these remain robust to one stray sample without shortening the
    # recovered handle.
    baseline = float(np.quantile(v[terminals], 0.10))
    top = float(np.quantile(v[middle], 0.90))
    height = top - baseline
    if height <= EPSILON:
        return None
    points = np.column_stack((centered_u, v - baseline))
    candidates = []
    for kind, corner_fraction in (
        ("semi_ellipse", 0.0),
        ("flat_top", 0.16), ("flat_top", 0.24),
        ("flat_top", 0.32), ("flat_top", 0.40),
    ):
        corner = min(half_span, height) * corner_fraction
        path = path_points_2d(kind, half_span, height, corner, 128)
        residual = _polyline_distances(points, path)
        median = float(np.quantile(residual, 0.50))
        p90 = float(np.quantile(residual, 0.90))
        scale = max(half_span, height, radius_hint, EPSILON)
        score = p90 / scale + 0.20 * median / scale
        candidates.append((score, kind, corner, median, p90, residual))
    score, kind, corner, median, p90, residual = min(candidates, key=lambda item: item[0])
    corridor = max(radius_hint * 1.65, median + max(radius_hint * 0.65, 4.5 * float(
        np.median(np.abs(residual - median))
    )))
    retained = float(np.mean(residual <= corridor))
    return {
        "path_kind": kind, "center_u": center_u, "baseline": baseline,
        "half_span": half_span, "rise": height, "corner_radius": corner,
        "p50": median, "p90": p90, "relative_p90": p90 / scale,
        "retention": retained, "score": score,
    }


def _signed_angle(first: np.ndarray, second: np.ndarray, normal: np.ndarray) -> float:
    first = _unit(first)
    second = _unit(second)
    if first is None or second is None:
        return 0.0
    if float(first @ second) < 0.0:
        first = -first
    return math.degrees(math.atan2(float(normal @ np.cross(first, second)),
                                   float(np.clip(first @ second, -1.0, 1.0))))


def endpoint_support_indices(fit: HandleFit,
                             support_points: Iterable[Iterable[float]],
                             tolerance_ratio: float = 0.38):
    """Select support marks that independently constrain both handle feet.

    Red marks are optional installation evidence, not a replacement for the
    green tube path.  A continuous background strip or a cluster near only one
    foot must therefore not be allowed to rotate the fitted handle frame.
    """
    support_rows = _rows(support_points, "support_points")
    if fit.status != "candidate_ready" or fit.half_span <= EPSILON or not len(support_rows):
        return (), {
            "provided": int(len(support_rows)), "usable": 0,
            "left": 0, "right": 0, "bilateral": False,
            "reason": "绿色管体尚未形成可验证的双端基准" if len(support_rows) else "未提供红色安装面",
        }
    origin = np.asarray(fit.origin, dtype=float)
    span = np.asarray(fit.span_axis, dtype=float)
    projected = (support_rows - origin) @ span
    tolerance = max(fit.half_span * float(tolerance_ratio), fit.radius_hint * 2.0)
    left = np.flatnonzero(np.abs(projected + fit.half_span) <= tolerance)
    right = np.flatnonzero(np.abs(projected - fit.half_span) <= tolerance)
    bilateral = bool(len(left) and len(right))
    selected = tuple(sorted(set(left.tolist() + right.tolist()))) if bilateral else ()
    if bilateral:
        reason = "红色标记分别约束左右安装端"
    elif len(left) or len(right):
        reason = "红色标记只约束到一个安装端，已忽略以防带偏主体角度"
    else:
        reason = "红色标记未落在绿色拟合的两个安装端附近，已忽略以防带偏主体角度"
    return selected, {
        "provided": int(len(support_rows)), "usable": int(len(selected)),
        "left": int(len(left)), "right": int(len(right)), "bilateral": bilateral,
        "tolerance": float(tolerance), "reason": reason,
    }


def fit_handle(points: Iterable[Iterable[float]], normals: Iterable[Iterable[float]],
               support_points: Iterable[Iterable[float]] = (),
               support_normals: Iterable[Iterable[float]] = (),
               radius_hint: float = 0.0,
               thresholds: HandleFitThresholds | None = None) -> HandleFit:
    thresholds = thresholds or HandleFitThresholds()
    point_rows = _rows(points, "points")
    normal_rows = _rows(normals, "normals")
    support_rows = _rows(support_points, "support_points")
    support_normal_rows = _rows(support_normals, "support_normals")
    count = len(point_rows)
    if count != len(normal_rows):
        raise ValueError("points and normals must have equal length")
    if len(support_rows) != len(support_normal_rows):
        raise ValueError("support points and normals must have equal length")
    if count < thresholds.minimum_target_samples:
        return _failed(f"扶手路径至少需要 {thresholds.minimum_target_samples} 个绿色表面标记", count, len(support_rows))
    lengths = np.linalg.norm(normal_rows, axis=1)
    if np.any(lengths <= EPSILON):
        return _failed("绿色标记包含无效表面法线", count, len(support_rows))
    unit_normals = normal_rows / lengths[:, None]
    if radius_hint <= EPSILON:
        nearest = []
        for index, point in enumerate(point_rows):
            distance = np.linalg.norm(point_rows - point, axis=1)
            distance[index] = np.inf
            nearest.append(float(np.min(distance)))
        radius_hint = max(float(np.quantile(nearest, 0.25)) * 0.35, 1.0e-4)
    medial = point_rows - unit_normals * radius_hint
    values, vectors = _principal(medial)
    raw_span = _canonical(vectors[:, -1])
    longitudinal_ratio = float(values[-1] / max(values[-2], EPSILON))

    support_used = len(support_rows) >= thresholds.minimum_support_samples
    support_angle = None
    frame_candidates = []
    if support_used:
        support_values, support_vectors = _principal(support_rows)
        span = _canonical(support_vectors[:, -1])
        mean_support_normal = _unit(np.mean(
            support_normal_rows / np.maximum(np.linalg.norm(support_normal_rows, axis=1)[:, None], EPSILON),
            axis=0,
        ))
        if mean_support_normal is None:
            return _failed("红色安装面法线互相冲突", count, len(support_rows))
        rise = mean_support_normal - span * float(mean_support_normal @ span)
        rise = _unit(rise)
        if rise is None:
            return _failed("红色安装切线与安装面法线退化", count, len(support_rows))
        if float((np.mean(medial, axis=0) - np.mean(support_rows, axis=0)) @ rise) < 0.0:
            rise = -rise
        plane = _unit(np.cross(span, rise))
        rise = _unit(np.cross(plane, span))
        if float((np.mean(medial, axis=0) - np.mean(support_rows, axis=0)) @ rise) < 0.0:
            rise, plane = -rise, -plane
        support_angle = _signed_angle(raw_span, span, plane)
        if abs(support_angle) > thresholds.maximum_support_angle_degrees:
            return _failed(
                f"红色安装切线与绿色扶手跨度相差 {abs(support_angle):.2f}°，疑似不是同一结构",
                count, len(support_rows), support_angle,
            )
        frame_candidates.append((span, rise, plane))
    else:
        plane = _canonical(vectors[:, 0])
        span = raw_span - plane * float(raw_span @ plane)
        span = _canonical(span)
        rise = _unit(np.cross(plane, span))
        frame_candidates.extend(((span, rise, plane), (span, -rise, -plane)))

    centroid = np.mean(medial, axis=0)
    fitted = []
    for span, rise, plane in frame_candidates:
        relative = medial - centroid
        local = np.column_stack((relative @ span, relative @ rise))
        path_fit = _fit_path(local, radius_hint)
        if path_fit is None:
            continue
        depth = relative @ plane
        in_plane_scale = max(float(np.std(local[:, 1])), radius_hint, EPSILON)
        thickness_ratio = float(np.std(depth) / in_plane_scale)
        fitted.append((path_fit["score"] + 0.15 * thickness_ratio,
                       span, rise, plane, thickness_ratio, path_fit))
    if not fitted:
        return _failed("绿色标记没有形成两端、两腿和顶部连续的单个扶手路径", count, len(support_rows), support_angle)
    _score, span, rise, plane, thickness_ratio, model = min(fitted, key=lambda item: item[0])
    origin = (centroid + span * model["center_u"] + rise * model["baseline"])
    reasons = []
    if model["half_span"] / radius_hint < thresholds.minimum_span_to_section:
        reasons.append("跨度与管径证据无法区分")
    if model["rise"] / radius_hint < thresholds.minimum_rise_to_section:
        reasons.append("抬升高度证据不足")
    if model["relative_p90"] > thresholds.maximum_relative_path_p90:
        reasons.append("绿色标记到扶手中心路径的误差过大")
    if thickness_ratio > thresholds.maximum_plane_thickness_ratio:
        reasons.append("标记没有形成稳定的单一扶手中面")
    if model["retention"] < thresholds.minimum_corridor_retention:
        reasons.append("连续管体走廊覆盖不足")
    if support_used:
        support_u = (support_rows - origin) @ span
        left = np.any(np.abs(support_u + model["half_span"]) <= model["half_span"] * 0.38)
        right = np.any(np.abs(support_u - model["half_span"]) <= model["half_span"] * 0.38)
        if not (left and right):
            reasons.append("红色安装标记没有分别约束左右两个端点")
    ready = not reasons
    confidence = max(0.0, min(1.0,
        1.0 - 2.2 * model["relative_p90"] - 0.45 * thickness_ratio
        - 0.30 * (1.0 - model["retention"])
    ))
    return HandleFit(
        status="candidate_ready" if ready else "needs_more_evidence",
        reason="；".join(reasons) if reasons else (
            "当前标记支持一个有双端安装证据的连续扶手候选"
            if support_used else "当前绿色管体标记支持自动推断双端安装的连续扶手候选"
        ),
        path_kind=model["path_kind"], origin=tuple(float(v) for v in origin),
        span_axis=tuple(float(v) for v in span), rise_axis=tuple(float(v) for v in rise),
        plane_normal=tuple(float(v) for v in plane), half_span=float(model["half_span"]),
        rise=float(model["rise"]), corner_radius=float(model["corner_radius"]),
        radius_hint=float(radius_hint), path_residual_p50=float(model["p50"]),
        path_residual_p90=float(model["p90"]), relative_path_p90=float(model["relative_p90"]),
        corridor_retention=float(model["retention"]), plane_thickness_ratio=thickness_ratio,
        longitudinal_ratio=longitudinal_ratio,
        support_angle_before_signed_degrees=support_angle,
        support_angle_after_degrees=0.0 if support_used else None,
        support_used=support_used, confidence=confidence,
        sample_count=count, support_sample_count=len(support_rows),
    )


def _failed(reason: str, count: int, support_count: int,
            support_angle: float | None = None) -> HandleFit:
    return HandleFit(
        status="needs_more_evidence", reason=reason, path_kind="unknown",
        origin=(0.0, 0.0, 0.0), span_axis=(1.0, 0.0, 0.0),
        rise_axis=(0.0, 1.0, 0.0), plane_normal=(0.0, 0.0, 1.0),
        half_span=0.0, rise=0.0, corner_radius=0.0, radius_hint=0.0,
        path_residual_p50=float("inf"), path_residual_p90=float("inf"),
        relative_path_p90=float("inf"), corridor_retention=0.0,
        plane_thickness_ratio=float("inf"), longitudinal_ratio=0.0,
        support_angle_before_signed_degrees=support_angle,
        support_angle_after_degrees=None, support_used=False,
        confidence=0.0, sample_count=count, support_sample_count=support_count,
    )
