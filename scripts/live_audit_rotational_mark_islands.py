"""Read-only audit of disconnected green rotational face islands."""

import json
from collections import defaultdict, deque

import bpy
import numpy as np

from semantic_mesh_marker_next.constants import TARGET_ROLE
from semantic_mesh_marker_next.storage import load_all_marks
from semantic_mesh_marker_next.rotational_fit import fit_rotational_surface


scene = bpy.context.scene
records = [item for item in load_all_marks(scene) if item.role == TARGET_ROLE]
source_names = {item.source_object_name for item in records}
source = bpy.data.objects.get(next(iter(source_names))) if len(source_names) == 1 else None
if source is None or source.type != "MESH":
    raise RuntimeError("marked source is missing or ambiguous")
faces = {int(item.face_index) for item in records}

edge_faces = defaultdict(list)
edge_lengths = []
for face_index in faces:
    polygon = source.data.polygons[face_index]
    for edge in polygon.edge_keys:
        key = tuple(sorted(edge))
        edge_faces[key].append(face_index)
        a = source.matrix_world @ source.data.vertices[key[0]].co
        b = source.matrix_world @ source.data.vertices[key[1]].co
        edge_lengths.append((b - a).length)
neighbors = defaultdict(set)
for linked in edge_faces.values():
    for first in linked:
        neighbors[first].update(second for second in linked if second != first)

remaining = set(faces)
components = []
while remaining:
    seed = remaining.pop()
    component = {seed}
    queue = deque((seed,))
    while queue:
        current = queue.popleft()
        for other in neighbors[current] & remaining:
            remaining.remove(other)
            component.add(other)
            queue.append(other)
    components.append(component)
components.sort(key=lambda item: (-len(item), min(item)))


def component_points(component):
    vertex_ids = {index for face_index in component for index in source.data.polygons[face_index].vertices}
    return np.asarray([
        tuple(source.matrix_world @ source.data.vertices[index].co)
        for index in sorted(vertex_ids)
    ], dtype=float)


point_sets = [component_points(component) for component in components]

fit_points = []
fit_normals = []
normal_matrix = source.matrix_world.to_3x3().inverted_safe().transposed()
for face_index in sorted(faces):
    polygon = source.data.polygons[face_index]
    fit_points.append(tuple(source.matrix_world @ polygon.center))
    normal = normal_matrix @ polygon.normal
    normal.normalize()
    fit_normals.append(tuple(normal))
fallback_fit = fit_rotational_surface(fit_points, fit_normals)
pairs = []
for first in range(len(components)):
    for second in range(first + 1, len(components)):
        delta = point_sets[first][:, None, :] - point_sets[second][None, :, :]
        distances = np.linalg.norm(delta, axis=2)
        pairs.append({
            "first": first,
            "second": second,
            "minimum_vertex_distance": round(float(np.min(distances)), 8),
            "p10_vertex_distance": round(float(np.quantile(distances, 0.10)), 6),
        })

payload = {
    "source": source.name,
    "marks": len(records),
    "unique_faces": len(faces),
    "components": [{
        "index": index,
        "faces": len(component),
        "vertices": len(point_sets[index]),
        "bounds_min": [round(value, 6) for value in np.min(point_sets[index], axis=0).tolist()],
        "bounds_max": [round(value, 6) for value in np.max(point_sets[index], axis=0).tolist()],
    } for index, component in enumerate(components)],
    "component_pairs": pairs,
    "median_selected_edge_length": round(float(np.median(edge_lengths)), 6),
    "broad_arc_fallback_fit": fallback_fit.to_dict(),
    "whole_vehicle_search": False,
}
print("SMRN_ROTATIONAL_ISLANDS=" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
