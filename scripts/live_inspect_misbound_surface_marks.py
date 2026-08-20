"""Read-only audit of marks that accidentally hit a visible working candidate."""

import json
from collections import Counter
from statistics import median

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from semantic_mesh_marker_next.constants import SOURCE_NAME_KEY
from semantic_mesh_marker_next.storage import load_all_marks


scene = bpy.context.scene
source_name = str(scene.get(SOURCE_NAME_KEY, ""))
records = load_all_marks(scene)
by_role_object = Counter((record.role, record.hit_object_name) for record in records)
objects = {}
for name in sorted({record.hit_object_name for record in records} | {source_name}):
    obj = bpy.data.objects.get(name)
    objects[name] = None if obj is None else {
        "type": obj.type,
        "vertices": len(obj.data.vertices) if obj.type == "MESH" else None,
        "faces": len(obj.data.polygons) if obj.type == "MESH" else None,
        "collections": [collection.name for collection in obj.users_collection],
        "source_name_property": str(obj.get("smrn_source_name", "")),
        "surface_role": str(obj.get("smrn_surface_role", "")),
        "visible": bool(obj.visible_get()),
    }

distance_rows = []
source = bpy.data.objects.get(source_name)
if source is not None and source.type == "MESH":
    vertices = [vertex.co.copy() for vertex in source.data.vertices]
    polygons = [tuple(polygon.vertices) for polygon in source.data.polygons]
    bvh = BVHTree.FromPolygons(vertices, polygons, all_triangles=False)
    source_inverse = source.matrix_world.inverted_safe()
    world_normal_matrix = source.matrix_world.to_3x3().inverted_safe().transposed()
    for record in records:
        if record.role != "target" or record.hit_object_name == source_name:
            continue
        local_query = source_inverse @ Vector(record.world_location)
        nearest, local_normal, face_index, distance = bvh.find_nearest(local_query)
        if nearest is None or face_index is None:
            distance_rows.append({"id": record.id, "valid": False})
            continue
        polygon = source.data.polygons[int(face_index)]
        edge_lengths = []
        polygon_vertices = list(polygon.vertices)
        for index, vertex_index in enumerate(polygon_vertices):
            next_index = polygon_vertices[(index + 1) % len(polygon_vertices)]
            edge_lengths.append((vertices[vertex_index] - vertices[next_index]).length)
        face_scale = median(edge_lengths) if edge_lengths else 0.0
        mapped_world_normal = world_normal_matrix @ local_normal
        if mapped_world_normal.length_squared:
            mapped_world_normal.normalize()
        record_normal = Vector(record.world_normal)
        if record_normal.length_squared:
            record_normal.normalize()
        angle_degrees = 0.0
        if record_normal.length_squared and mapped_world_normal.length_squared:
            angle_degrees = record_normal.angle(mapped_world_normal, 0.0) * 57.29577951308232
        distance_rows.append({
            "id": record.id,
            "valid": True,
            "source_face": int(face_index),
            "distance": float(distance),
            "face_scale": float(face_scale),
            "distance_face_ratio": float(distance / face_scale) if face_scale > 1.0e-12 else None,
            "normal_angle_degrees": float(angle_degrees),
        })


def distribution(values):
    values = sorted(float(value) for value in values if value is not None)
    if not values:
        return None
    percentile_95 = values[min(len(values) - 1, int(round((len(values) - 1) * 0.95)))]
    return {"min": values[0], "median": median(values), "p95": percentile_95, "max": values[-1]}

print("SMRN_MISBOUND_MARK_AUDIT=" + json.dumps({
    "source": source_name,
    "counts": [
        {"role": role, "object": name, "count": count}
        for (role, name), count in sorted(by_role_object.items())
    ],
    "objects": objects,
    "surface_settings": {
        "height_mode": str(getattr(scene, "smrn_surface_height_mode", "")),
        "normal_mode": str(getattr(scene, "smrn_surface_normal_mode", "")),
    },
    "candidate_to_source_projection": {
        "valid": sum(1 for row in distance_rows if row.get("valid")),
        "invalid": sum(1 for row in distance_rows if not row.get("valid")),
        "unique_source_faces": len({row["source_face"] for row in distance_rows if row.get("valid")}),
        "distance": distribution([row.get("distance") for row in distance_rows]),
        "distance_face_ratio": distribution([row.get("distance_face_ratio") for row in distance_rows]),
        "normal_angle_degrees": distribution([row.get("normal_angle_degrees") for row in distance_rows]),
        "rows": distance_rows,
    },
}, ensure_ascii=False, separators=(",", ":")))
