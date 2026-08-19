"""Read-only diagnostics for rotational target marks in the active Blender scene."""

import json
from collections import defaultdict, deque

import bpy
from mathutils import Vector


scene = bpy.context.scene
records = []
document = json.loads(str(scene.get("smrn_document_json", "{}") or "{}"))
for key in document.get("chunks", []):
    payload = json.loads(str(scene.get(key, "{}") or "{}"))
    records.extend(payload.get("records", []))

task_id = document.get("active_task_id", "task-0001")
targets = [
    item for item in records
    if item.get("task_id", "task-0001") == task_id and item.get("role") == "target"
]
by_source = defaultdict(list)
for item in targets:
    by_source[item.get("source_object_name") or item.get("hit_object_name", "")].append(item)

sources = []
for source_name, items in by_source.items():
    source = bpy.data.objects.get(source_name)
    if source is None or source.type != "MESH":
        sources.append({"name": source_name, "error": "missing mesh source"})
        continue
    face_ids = sorted({int(item["anchor"]["face_index"]) for item in items})
    marked = set(face_ids)
    edge_faces = defaultdict(list)
    for face_id in face_ids:
        polygon = source.data.polygons[face_id]
        for edge_key in polygon.edge_keys:
            edge_faces[tuple(sorted(edge_key))].append(face_id)
    adjacency = {face_id: set() for face_id in face_ids}
    for linked in edge_faces.values():
        if len(linked) > 1:
            for face_id in linked:
                adjacency[face_id].update(other for other in linked if other != face_id)
    components = []
    remaining = set(marked)
    while remaining:
        seed = max(remaining)
        queue = deque([seed])
        component = set()
        while queue:
            face_id = queue.popleft()
            if face_id not in remaining:
                continue
            remaining.remove(face_id)
            component.add(face_id)
            queue.extend(adjacency[face_id] & remaining)
        components.append(sorted(component))
    components.sort(key=lambda value: max(value), reverse=True)

    points = [Vector(item["anchor"]["world_location"]) for item in items]
    normals = [Vector(item["anchor"]["world_normal"]).normalized() for item in items]
    pair_distances = sorted(
        (points[i] - points[j]).length
        for i in range(len(points)) for j in range(i)
        if (points[i] - points[j]).length > 1.0e-9
    )
    sources.append({
        "name": source_name,
        "visible": source.visible_get(),
        "topology": [len(source.data.vertices), len(source.data.edges), len(source.data.polygons)],
        "mark_ids": [int(item["id"]) for item in items],
        "face_ids": face_ids,
        "face_components": components,
        "bbox_min": [round(min(point[i] for point in points), 6) for i in range(3)],
        "bbox_max": [round(max(point[i] for point in points), 6) for i in range(3)],
        "nearest_spacing": round(pair_distances[0], 6) if pair_distances else None,
        "median_spacing": round(pair_distances[len(pair_distances) // 2], 6) if pair_distances else None,
        "points": [[round(value, 6) for value in point] for point in points],
        "normals": [[round(value, 6) for value in normal] for normal in normals],
    })

visible_mesh_count = sum(
    1 for obj in bpy.context.view_layer.objects
    if obj.type == "MESH" and obj.visible_get(view_layer=bpy.context.view_layer)
)
print("SMRN_ROTATIONAL_INPUT=" + json.dumps({
    "blend": bpy.data.filepath,
    "task_id": task_id,
    "target_count": len(targets),
    "sources": sources,
    "visible_mesh_count": visible_mesh_count,
}, ensure_ascii=False, separators=(",", ":")))
