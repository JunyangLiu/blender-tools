"""Recover marks intercepted by a visible unaccepted candidate.

The script validates every affected anchor against the authoritative source,
creates a .blend checkpoint, then rewrites only the proven candidate-bound
records.  It never scans unrelated model objects.
"""

import json
import math
from datetime import datetime
from pathlib import Path
from statistics import median

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from semantic_mesh_marker_next.anchors import enrich_hit_anchor, source_snapshot
from semantic_mesh_marker_next.constants import CANDIDATE_COLLECTION_NAME, SOURCE_NAME_KEY
from semantic_mesh_marker_next.records import MarkRecord
from semantic_mesh_marker_next.storage import load_all_marks, rewrite_all_marks


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get(SOURCE_NAME_KEY, "")))
if source is None or source.type != "MESH":
    raise RuntimeError("当前语义源不存在或不是网格")

records = load_all_marks(scene)
affected = []
for record in records:
    if record.hit_object_name == source.name:
        continue
    candidate = bpy.data.objects.get(record.hit_object_name)
    if candidate is None or candidate.type != "MESH":
        continue
    is_working_candidate = (
        str(candidate.get("smrn_source_name", "")) == source.name
        and not bool(candidate.get("smrn_accepted", False))
        and any(
            owner.name == CANDIDATE_COLLECTION_NAME
            or str(owner.get("smrn_collection_role", "")) == "working_candidates"
            for owner in candidate.users_collection
        )
    )
    if is_working_candidate:
        affected.append(record)

if not affected:
    print("SMRN_MARK_REBIND=" + json.dumps({"status": "nothing_to_rebind"}, ensure_ascii=False))
else:
    vertices = [vertex.co.copy() for vertex in source.data.vertices]
    polygons = [tuple(polygon.vertices) for polygon in source.data.polygons]
    bvh = BVHTree.FromPolygons(vertices, polygons, all_triangles=False)
    inverse = source.matrix_world.inverted_safe()
    world_normal_matrix = source.matrix_world.to_3x3().inverted_safe().transposed()
    fingerprint = source_snapshot(source)["fingerprint"]
    replacements = {}
    audit = []

    for record in affected:
        local_query = inverse @ Vector(record.world_location)
        nearest, local_normal, face_index, distance = bvh.find_nearest(local_query)
        if nearest is None or face_index is None:
            raise RuntimeError(f"标记 {record.id} 无法投影回当前语义源")
        polygon = source.data.polygons[int(face_index)]
        polygon_indices = list(polygon.vertices)
        edge_lengths = [
            (vertices[polygon_indices[index]] - vertices[polygon_indices[(index + 1) % len(polygon_indices)]]).length
            for index in range(len(polygon_indices))
        ]
        face_scale = median(edge_lengths) if edge_lengths else 0.0
        distance_ratio = float(distance / face_scale) if face_scale > 1.0e-12 else math.inf
        mapped_world_normal = world_normal_matrix @ local_normal
        if mapped_world_normal.length_squared:
            mapped_world_normal.normalize()
        original_normal = Vector(record.world_normal)
        if original_normal.length_squared:
            original_normal.normalize()
        angle_degrees = math.degrees(original_normal.angle(mapped_world_normal, 0.0))
        # Relative gates make the decision local to this model and surface.
        if distance_ratio > 0.01 or angle_degrees > 15.0:
            raise RuntimeError(
                f"标记 {record.id} 回绑证据不足：距离/面尺度={distance_ratio:.6f}，法向差={angle_degrees:.2f}°"
            )

        mapped_world = source.matrix_world @ nearest
        hit = {
            "world_location": mapped_world,
            "world_normal": mapped_world_normal,
            "face_index": int(face_index),
        }
        enrich_hit_anchor(hit, source, fingerprint)
        payload = record.to_dict()
        previous_object = record.hit_object_name
        payload["hit_object_name"] = source.name
        payload["source_object_name"] = source.name
        payload["anchor"].update({
            "face_index": int(face_index),
            "world_location": list(mapped_world),
            "world_normal": list(mapped_world_normal),
            "local_location": list(hit["local_location"]),
            "local_normal": list(hit["local_normal"]),
            "triangle_vertex_indices": (
                list(hit["triangle_vertex_indices"]) if hit["triangle_vertex_indices"] else None
            ),
            "barycentric": list(hit["barycentric"]) if hit["barycentric"] else None,
            "source_fingerprint": fingerprint,
        })
        extensions = dict(payload.get("extensions", {}))
        extensions["candidate_rebind"] = {
            "from_object": previous_object,
            "distance_local": float(distance),
            "distance_face_ratio": distance_ratio,
            "normal_angle_degrees": angle_degrees,
        }
        payload["extensions"] = extensions
        replacements[record.id] = MarkRecord.from_mapping(payload)
        audit.append({
            "id": record.id,
            "from": previous_object,
            "source_face": int(face_index),
            "distance_face_ratio": distance_ratio,
            "normal_angle_degrees": angle_degrees,
        })

    current_path = Path(bpy.data.filepath)
    if not current_path:
        raise RuntimeError("当前 .blend 尚未保存，无法建立回绑检查点")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    checkpoint = current_path.with_name(f"{current_path.stem}_before_mark_rebind_{stamp}{current_path.suffix}")
    bpy.ops.wm.save_as_mainfile(filepath=str(checkpoint), copy=True)

    rebound = [replacements.get(record.id, record) for record in records]
    rewrite_all_marks(scene, rebound)
    for record in replacements.values():
        overlay = bpy.data.objects.get(record.overlay_object_name)
        if overlay is not None:
            overlay["smrn_hit_object_name"] = source.name
            overlay["smrn_source_object_name"] = source.name
            overlay["smrn_face_index"] = record.face_index
            overlay["smrn_world_location"] = list(record.world_location)
            overlay["smrn_world_normal"] = list(record.world_normal)
    bpy.ops.wm.save_mainfile()
    print("SMRN_MARK_REBIND=" + json.dumps({
        "status": "rebound",
        "count": len(replacements),
        "source": source.name,
        "checkpoint": str(checkpoint),
        "max_distance_face_ratio": max(row["distance_face_ratio"] for row in audit),
        "max_normal_angle_degrees": max(row["normal_angle_degrees"] for row in audit),
    }, ensure_ascii=False, separators=(",", ":")))
