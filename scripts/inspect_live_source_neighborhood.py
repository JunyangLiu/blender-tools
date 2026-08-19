"""Read-only topology diagnostics around current rotational target faces."""

import json
from collections import defaultdict, deque

import bpy
from mathutils import Vector


scene = bpy.context.scene
document = json.loads(str(scene.get("smrn_document_json", "{}") or "{}"))
records = []
for key in document.get("chunks", []):
    payload = json.loads(str(scene.get(key, "{}") or "{}"))
    records.extend(payload.get("records", []))
targets = [item for item in records if item.get("role") == "target"]
source_name = targets[-1].get("source_object_name") or targets[-1].get("hit_object_name")
source = bpy.data.objects[source_name]
mesh = source.data
seed_faces = {int(item["anchor"]["face_index"]) for item in targets}

edge_faces = defaultdict(list)
for polygon in mesh.polygons:
    for edge_key in polygon.edge_keys:
        edge_faces[tuple(sorted(edge_key))].append(polygon.index)
neighbors = defaultdict(set)
for linked in edge_faces.values():
    if len(linked) == 2:
        a, b = linked
        neighbors[a].add(b)
        neighbors[b].add(a)


def flood(max_angle_degrees=None, max_faces=200000):
    seen = set(seed_faces)
    queue = deque(seed_faces)
    cosine = None
    if max_angle_degrees is not None:
        import math
        cosine = math.cos(math.radians(max_angle_degrees))
    while queue and len(seen) < max_faces:
        current = queue.popleft()
        normal = mesh.polygons[current].normal
        for other in neighbors[current]:
            if other in seen:
                continue
            if cosine is not None and normal.dot(mesh.polygons[other].normal) < cosine:
                continue
            seen.add(other)
            queue.append(other)
    return seen


def summarize(face_ids):
    points = []
    total_area = 0.0
    for face_id in face_ids:
        polygon = mesh.polygons[face_id]
        points.append(source.matrix_world @ polygon.center)
        total_area += polygon.area
    return {
        "faces": len(face_ids),
        "bbox_min": [round(min(point[i] for point in points), 5) for i in range(3)],
        "bbox_max": [round(max(point[i] for point in points), 5) for i in range(3)],
        "area_local": round(total_area, 5),
    }


seed_details = []
for face_id in sorted(seed_faces):
    polygon = mesh.polygons[face_id]
    seed_details.append({
        "face": face_id,
        "vertices": list(polygon.vertices),
        "center": [round(value, 6) for value in (source.matrix_world @ polygon.center)],
        "normal": [round(value, 6) for value in (source.matrix_world.to_3x3() @ polygon.normal).normalized()],
        "area_local": round(polygon.area, 7),
        "neighbors": sorted(neighbors[face_id]),
    })

result = {
    "source": source_name,
    "seed_faces": sorted(seed_faces),
    "seed_details": seed_details,
    "flood_12": summarize(flood(12.0)),
    "flood_25": summarize(flood(25.0)),
    "flood_45": summarize(flood(45.0)),
    "connected": summarize(flood(None)),
}
print("SMRN_SOURCE_NEIGHBORHOOD=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
