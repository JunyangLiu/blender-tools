"""Audit marked rotational faces for bridge vertices and local slope regimes."""

import json
import math

import bpy
import numpy as np

from semantic_mesh_marker_next.rotational_blender import (
    _coordinates,
    _current_anchor,
    _source_for_targets,
    _semantic_rotational_faces,
    _task_records,
    analyze_scene,
)


scene = bpy.context.scene
fit, source, targets, _excludes, _context = analyze_scene(scene)
source, _snapshot = _source_for_targets(scene, targets)
anchor_points = [tuple(_current_anchor(item, source)[0]) for item in targets]
anchor_axial, anchor_radius, _anchor_angle = _coordinates(anchor_points, fit)

edge_faces = {}
for polygon in source.data.polygons:
    vertices = list(polygon.vertices)
    for index, first in enumerate(vertices):
        edge = tuple(sorted((first, vertices[(index + 1) % len(vertices)])))
        edge_faces.setdefault(edge, []).append(polygon.index)


def world_vertices(polygon):
    return [tuple(source.matrix_world @ source.data.vertices[index].co) for index in polygon.vertices]


def face_row(face_index, marked):
    polygon = source.data.polygons[face_index]
    points = world_vertices(polygon)
    axial, radius, angle = _coordinates(points, fit)
    predicted = np.abs(fit.signed_radius_at_origin + fit.signed_slope * axial)
    normal = source.matrix_world.to_3x3().inverted_safe().transposed() @ polygon.normal
    normal.normalize()
    axis = np.asarray(fit.axis, dtype=float)
    normal_array = np.asarray(tuple(normal), dtype=float)
    normal_axial = float(normal_array @ axis)
    normal_radial = float(np.linalg.norm(normal_array - normal_axial * axis))
    slope = -normal_axial / max(normal_radial, 1.0e-9)
    return {
        "face": face_index,
        "marked": marked,
        "vertices": len(points),
        "axial": [round(float(value), 6) for value in axial],
        "radius": [round(float(value), 6) for value in radius],
        "profile_error": [round(float(value), 6) for value in radius - predicted],
        "angle_degrees": [round(math.degrees(float(value)), 3) for value in angle],
        "axial_span": round(float(np.ptp(axial)), 6),
        "radius_span": round(float(np.ptp(radius)), 6),
        "face_slope": round(float(slope), 6),
    }


marked_indices = sorted({item.face_index for item in targets})
neighbor_indices = set()
for face_index in marked_indices:
    polygon = source.data.polygons[face_index]
    vertices = list(polygon.vertices)
    for index, first in enumerate(vertices):
        edge = tuple(sorted((first, vertices[(index + 1) % len(vertices)])))
        neighbor_indices.update(edge_faces.get(edge, ()))
neighbor_indices.difference_update(marked_indices)

result = {
    "fit": {
        "axis": fit.axis,
        "origin": fit.axis_origin,
        "radius": fit.radius_at_axial(0.0),
        "slope": fit.signed_slope,
        "profile": fit.profile_kind,
    },
    "anchor_axial": [round(float(value), 6) for value in anchor_axial],
    "anchor_radius": [round(float(value), 6) for value in anchor_radius],
    "anchor_axial_span": round(float(np.ptp(anchor_axial)), 6),
    "marked": [face_row(index, True) for index in marked_indices],
    "neighbors": [face_row(index, False) for index in sorted(neighbor_indices)],
}
surface_faces, expansion = _semantic_rotational_faces(fit, source, targets)
surface_points = []
for face_index in surface_faces:
    surface_points.extend(world_vertices(source.data.polygons[face_index]))
_surface_axial, _surface_radius, surface_angle = _coordinates(surface_points, fit)
unique_angles = np.unique(np.round(np.mod(surface_angle, 2.0 * math.pi), 7))
ordered_angles = np.sort(unique_angles)
angle_gaps = np.diff(np.r_[ordered_angles, ordered_angles[0] + 2.0 * math.pi])
gap_order = np.argsort(angle_gaps)[::-1]
result["semantic"] = {
    **expansion,
    "face_ids": sorted(surface_faces),
    "largest_gaps": [
        {
            "start": round(math.degrees(float(ordered_angles[index])), 3),
            "end": round(math.degrees(float(ordered_angles[(index + 1) % len(ordered_angles)])), 3),
            "gap": round(math.degrees(float(angle_gaps[index])), 3),
        }
        for index in gap_order[:8]
    ],
}
print("SMRN_PROFILE_AUDIT=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
