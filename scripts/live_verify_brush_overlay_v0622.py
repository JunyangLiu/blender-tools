"""Bounded numerical QA for the six reported brush-gap faces."""

import json

import bpy

from semantic_mesh_marker_next.storage import document_summary, load_all_marks


TARGET_FACES = {190868, 190821, 191293, 189606, 189601, 189624}
scene = bpy.context.scene
summary = document_summary(scene)
working = bpy.data.objects.get(str(scene.get("smrn_surface_working_name", "")))
rows = []
for record in load_all_marks(scene, summary["task_id"]):
    face_index = int(record.face_index)
    if face_index not in TARGET_FACES:
        continue
    overlay = bpy.data.objects.get(record.overlay_object_name)
    polygon = working.data.polygons[face_index] if working else None
    expected = [working.matrix_world @ working.data.vertices[index].co for index in polygon.vertices] if polygon else []
    actual = [overlay.matrix_world @ overlay.data.vertices[index].co for index in range(len(expected))] if overlay else []
    # Overlay vertices intentionally receive a tiny normal offset. Tangential
    # displacement should be zero; total displacement must remain that offset.
    distances = [(left - right).length for left, right in zip(actual, expected)]
    rows.append({
        "face": face_index,
        "expected_vertices": len(expected),
        "overlay_vertices_checked": len(actual),
        "max_surface_offset": max(distances) if distances else None,
        "geometry_source": str(overlay.get("smrn_raycast_object_name", "")) if overlay else "",
        "visible": bool(overlay and overlay.visible_get(view_layer=bpy.context.view_layer)),
    })

print("SMRN_BRUSH_OVERLAY_QA_V0622=" + json.dumps({
    "faces_expected": len(TARGET_FACES),
    "faces_checked": len(rows),
    "all_visible": len(rows) == len(TARGET_FACES) and all(row["visible"] for row in rows),
    "all_follow_working": bool(working) and all(row["geometry_source"] == working.name for row in rows),
    "rows": rows,
    "source_mesh_modified": False,
    "whole_vehicle_search": False,
}, ensure_ascii=False, separators=(",", ":")))
