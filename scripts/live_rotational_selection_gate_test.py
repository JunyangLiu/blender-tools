"""Exercise exact selected-face rotational rebuild math without touching the scene."""

import json
import math

import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next import rotational_blender as adapter


segments = 16
radius = 2.0
half_length = 1.5
vertices = []
for axial in (-half_length, half_length):
    for index in range(segments):
        angle = 2.0 * math.pi * index / segments
        vertices.append((axial, radius * math.cos(angle), radius * math.sin(angle)))
faces = []
for index in range(segments):
    following = (index + 1) % segments
    faces.append((index, following, segments + following, segments + index))

mesh = bpy.data.meshes.new("SMRN_SELECTION_GATE_MESH")
source = bpy.data.objects.new("SMRN_SELECTION_GATE_SOURCE", mesh)
try:
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    before = source_snapshot(source)["fingerprint"]
    selected = set(range(segments))
    fit, context_report = adapter.analyze_selected_faces(source, selected)
    if fit.status != "candidate_ready":
        raise RuntimeError("fit rejected: " + fit.reason)
    domain = adapter._expanded_domain(fit, source, (), selected)
    axial_min, axial_max, angle_start, angle_span, fitted_clearance, _points = domain
    dense = adapter._dense_triangle_samples(source, (), face_indices=selected)
    clearance = max(fitted_clearance, adapter._required_clearance(fit, dense))
    thickness = adapter._auto_thickness(fit, axial_min, axial_max)
    candidate_vertices, candidate_faces, output_segments = adapter._candidate_geometry(
        fit, axial_min, axial_max, angle_start, angle_span,
        thickness, clearance, 64,
    )
    topology = adapter._topology_report(candidate_vertices, candidate_faces)
    coverage = adapter._coverage_report(
        fit, dense, axial_min, axial_max, angle_start, angle_span, clearance
    )
    after = source_snapshot(source)["fingerprint"]
    result = {
        "fit": fit.profile_kind,
        "coverage_mode": "full_rotation" if angle_span >= 2.0 * math.pi - 1.0e-7 else "partial_arc",
        "selected_faces": context_report["selection_qa"]["selected_faces"],
        "expanded_faces": 0,
        "whole_vehicle_search": context_report["selection_qa"]["whole_vehicle_search"],
        "dense_samples": coverage["samples"],
        "uncovered": coverage["uncovered"],
        "topology_passed": topology["passed"],
        "nonmanifold_edges": topology["nonmanifold_edges"],
        "output_segments": output_segments,
        "source_unchanged": before == after,
    }
    if not (coverage["passed"] and topology["passed"] and before == after):
        raise RuntimeError("selection rebuild gate failed: " + repr(result))
    print("SMRN_SELECTION_GATE=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
finally:
    bpy.data.objects.remove(source, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)
