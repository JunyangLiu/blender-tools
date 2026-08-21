"""Diagnose the persisted local flatten region without scanning the vehicle."""

import json
import math

import bpy
from mathutils import Vector


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
if source is None or source.type != "MESH":
    raise RuntimeError("Current semantic source is unavailable")

mesh = source.data
attribute = mesh.attributes.get("smrn_rebuild_region")
if attribute is None or attribute.domain != "FACE":
    raise RuntimeError("Source has no persisted local rebuild region")

region_faces = [
    polygon for polygon, item in zip(mesh.polygons, attribute.data)
    if int(item.value) == 1
]
region_indices = {polygon.index for polygon in region_faces}
region_vertices = sorted({index for polygon in region_faces for index in polygon.vertices})
if len(region_vertices) < 3:
    raise RuntimeError("Persisted region has too few vertices")

# Fit only the persisted ROI. This is intentionally not a whole-model scan.
coords = [mesh.vertices[index].co.copy() for index in region_vertices]
center = sum(coords, Vector()) / len(coords)
xx = xy = xz = yy = yz = zz = 0.0
for coordinate in coords:
    delta = coordinate - center
    xx += delta.x * delta.x
    xy += delta.x * delta.y
    xz += delta.x * delta.z
    yy += delta.y * delta.y
    yz += delta.y * delta.z
    zz += delta.z * delta.z

# Jacobi eigensolver for the smallest covariance eigenvector.
matrix = [[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]]
vectors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
for _ in range(32):
    p, q = max(((0, 1), (0, 2), (1, 2)), key=lambda pair: abs(matrix[pair[0]][pair[1]]))
    if abs(matrix[p][q]) < 1.0e-15:
        break
    angle = 0.5 * math.atan2(2.0 * matrix[p][q], matrix[q][q] - matrix[p][p])
    cosine, sine = math.cos(angle), math.sin(angle)
    for row in range(3):
        mp, mq = matrix[row][p], matrix[row][q]
        matrix[row][p] = cosine * mp - sine * mq
        matrix[row][q] = sine * mp + cosine * mq
    for column in range(3):
        mp, mq = matrix[p][column], matrix[q][column]
        matrix[p][column] = cosine * mp - sine * mq
        matrix[q][column] = sine * mp + cosine * mq
    for row in range(3):
        vp, vq = vectors[row][p], vectors[row][q]
        vectors[row][p] = cosine * vp - sine * vq
        vectors[row][q] = sine * vp + cosine * vq

smallest = min(range(3), key=lambda index: matrix[index][index])
normal = Vector((vectors[0][smallest], vectors[1][smallest], vectors[2][smallest])).normalized()
average_normal = sum((polygon.normal for polygon in region_faces), Vector()).normalized()
if normal.dot(average_normal) < 0.0:
    normal.negate()

deviations = [(coordinate - center).dot(normal) for coordinate in coords]
projected = {
    index: mesh.vertices[index].co - normal * ((mesh.vertices[index].co - center).dot(normal))
    for index in region_vertices
}

# Boundary/shared vertices quantify the exact local transition, not the whole mesh.
shared_vertices = set()
adjacent_unmarked_faces = set()
vertex_faces = {index: [] for index in region_vertices}
for polygon in mesh.polygons:
    for index in polygon.vertices:
        if index in vertex_faces:
            vertex_faces[index].append(polygon.index)
for index, linked_faces in vertex_faces.items():
    outside = [face_index for face_index in linked_faces if face_index not in region_indices]
    if outside:
        shared_vertices.add(index)
        adjacent_unmarked_faces.update(outside)

movements = [(projected[index] - mesh.vertices[index].co).length for index in region_vertices]
candidate_names = [
    obj.name for obj in bpy.data.objects
    if obj.name.startswith("SMRN_SURFACE_CANDIDATE_")
]
working_names = [
    obj.name for obj in bpy.data.objects
    if obj.name.startswith("SMRN_SURFACE_WORKING_FULL_")
]

result = {
    "source": source.name,
    "source_visible": not source.hide_get() and not source.hide_viewport,
    "region_faces": len(region_faces),
    "region_vertices": len(region_vertices),
    "shared_boundary_vertices": len(shared_vertices),
    "adjacent_unmarked_faces": len(adjacent_unmarked_faces),
    "fit_center_local": list(center),
    "fit_normal_local": list(normal),
    "before_rms": math.sqrt(sum(value * value for value in deviations) / len(deviations)),
    "before_max_abs": max(abs(value) for value in deviations),
    "exact_projection_max_move": max(movements),
    "exact_projection_mean_move": sum(movements) / len(movements),
    "candidate_names": candidate_names,
    "working_names": working_names,
    "scene_status": str(scene.get("smrn_status", "")),
    "candidate_report_mode": str(scene.get("smrn_candidate_report_mode", "")),
    "whole_vehicle_scan": False,
}
print("SMRN_EXACT_FLATTEN_DIAG_V0619=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
