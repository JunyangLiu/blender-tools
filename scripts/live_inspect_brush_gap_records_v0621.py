import json

import bpy

from semantic_mesh_marker_next.storage import document_summary, load_all_marks


TARGET_FACES = {190868, 190821, 191293, 189606, 189601, 189624}
scene = bpy.context.scene
summary = document_summary(scene)
rows = []
for record in load_all_marks(scene, summary["task_id"]):
    if int(record.face_index) not in TARGET_FACES:
        continue
    overlay = bpy.data.objects.get(record.overlay_object_name)
    rows.append({
        "id": record.id,
        "role": record.role,
        "face": int(record.face_index),
        "hit_object": record.hit_object_name,
        "overlay": record.overlay_object_name,
        "overlay_exists": overlay is not None,
        "overlay_visible": bool(overlay and overlay.visible_get(view_layer=bpy.context.view_layer)),
        "overlay_hide_get": bool(overlay and overlay.hide_get()),
        "overlay_vertex_count": len(overlay.data.vertices) if overlay and overlay.type == "MESH" else None,
        "overlay_face_count": len(overlay.data.polygons) if overlay and overlay.type == "MESH" else None,
        "overlay_source": str(overlay.get("smrn_source_object_name", "")) if overlay else "",
        "overlay_raycast": str(overlay.get("smrn_raycast_object_name", "")) if overlay else "",
        "record_world": [round(float(value), 6) for value in record.world_location],
    })

print(json.dumps({
    "task": summary["task_id"],
    "mark_count": summary["mark_count"],
    "target_faces": sorted(TARGET_FACES),
    "records": rows,
}, ensure_ascii=False, indent=2))
