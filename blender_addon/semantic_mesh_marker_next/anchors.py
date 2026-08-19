"""Bounded-cost source fingerprints and surface-anchor enrichment."""

from __future__ import annotations

import hashlib
import json
import bpy
from mathutils import Vector

from .constants import SOURCE_NAME_KEY
from .records import MarkRecord
from .storage import document_summary, load_all_marks, rewrite_all_marks, set_active_source


def source_snapshot(obj):
    mesh = obj.data
    vertices = mesh.vertices
    step = max(1, len(vertices) // 32)
    sample = [[round(axis, 6) for axis in vertices[index].co] for index in range(0, len(vertices), step)][:32]
    bounds = [axis for corner in obj.bound_box for axis in corner]
    minima = [min(bounds[index::3]) for index in range(3)]
    maxima = [max(bounds[index::3]) for index in range(3)]
    identity = {
        "mesh": mesh.name, "vertices": len(vertices), "polygons": len(mesh.polygons),
        "sample": sample, "bounds": minima + maxima,
    }
    fingerprint = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()[:20]
    return {
        "object_name": obj.name, "mesh_name": mesh.name,
        "vertex_count": len(vertices), "polygon_count": len(mesh.polygons),
        "matrix_world": [float(value) for row in obj.matrix_world for value in row],
        "bounds_local": minima + maxima, "fingerprint": fingerprint,
    }


def enrich_hit_anchor(hit, source_obj, fingerprint=""):
    inverse = source_obj.matrix_world.inverted_safe()
    local_location = inverse @ hit["world_location"]
    normal_matrix = source_obj.matrix_world.to_3x3().inverted_safe().transposed()
    local_normal = normal_matrix.inverted_safe() @ hit["world_normal"]
    if local_normal.length_squared:
        local_normal.normalize()
    hit["local_location"] = tuple(float(value) for value in local_location)
    hit["local_normal"] = tuple(float(value) for value in local_normal)
    hit["source_fingerprint"] = fingerprint
    hit["triangle_vertex_indices"] = None
    hit["barycentric"] = None
    polygon = source_obj.data.polygons[hit["face_index"]] if hit["face_index"] < len(source_obj.data.polygons) else None
    if polygon is not None and len(polygon.vertices) == 3:
        indices = tuple(int(value) for value in polygon.vertices)
        a, b, c = (source_obj.data.vertices[index].co for index in indices)
        v0, v1, v2 = b - a, c - a, local_location - a
        d00, d01, d11 = v0.dot(v0), v0.dot(v1), v1.dot(v1)
        d20, d21 = v2.dot(v0), v2.dot(v1)
        denominator = d00 * d11 - d01 * d01
        if abs(denominator) > 1e-15:
            v = (d11 * d20 - d01 * d21) / denominator
            w = (d00 * d21 - d01 * d20) / denominator
            hit["triangle_vertex_indices"] = indices
            hit["barycentric"] = (1.0 - v - w, v, w)
    return hit


def migrate_scene_anchors(scene):
    """Migrate v1 records and backfill local anchors against current hit meshes."""
    summary = document_summary(scene)
    source = bpy.data.objects.get(str(scene.get(SOURCE_NAME_KEY, "")))
    if source is not None and source.type == "MESH" and not summary.get("source"):
        set_active_source(scene, source_snapshot(source))
    records = load_all_marks(scene)
    migrated = []
    changed = False
    fingerprints = {}
    for record in records:
        hit_object = bpy.data.objects.get(record.hit_object_name)
        if hit_object is None or hit_object.type != "MESH":
            migrated.append(record)
            continue
        if hit_object.name not in fingerprints:
            fingerprints[hit_object.name] = source_snapshot(hit_object)["fingerprint"]
        fingerprint = fingerprints[hit_object.name]
        if record.local_location is not None:
            migrated.append(record)
            continue
        hit = {
            "world_location": Vector(record.world_location),
            "world_normal": Vector(record.world_normal),
            "face_index": record.face_index,
        }
        enrich_hit_anchor(hit, hit_object, fingerprint)
        value = record.to_dict()
        value["anchor"].update({
            "local_location": list(hit["local_location"]),
            "local_normal": list(hit["local_normal"]),
            "triangle_vertex_indices": (list(hit["triangle_vertex_indices"])
                                        if hit["triangle_vertex_indices"] else None),
            "barycentric": list(hit["barycentric"]) if hit["barycentric"] else None,
            "source_fingerprint": fingerprint,
        })
        migrated.append(MarkRecord.from_mapping(value))
        changed = True
    if changed:
        rewrite_all_marks(scene, migrated)
    return {"count": len(migrated), "anchors_backfilled": sum(item.local_location is not None for item in migrated)}
