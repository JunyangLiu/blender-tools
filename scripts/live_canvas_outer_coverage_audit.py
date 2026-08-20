"""Inspect only the active marked canvas candidate in the assigned Blender task."""

import json

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


scene = bpy.context.scene
preview_name = str(scene.get("smrn_surface_candidate_name", ""))
working_name = str(scene.get("smrn_surface_working_name", ""))
preview = bpy.data.objects.get(preview_name)
working = bpy.data.objects.get(working_name)
helpers = bpy.data.collections.get("SMRN_03_标记辅助")
if helpers is None:
    helpers = next(
        (collection for collection in bpy.data.collections if collection.get("smrn_collection_role") == "helpers"),
        None,
    )

report = {}
if preview is not None:
    for key in preview.keys():
        if "report" in key.lower():
            try:
                report[key] = json.loads(str(preview[key]))
            except Exception:
                report[key] = str(preview[key])

primary_report = next((value for value in report.values() if isinstance(value, dict)), {})
topology_report = primary_report.get("topology_qa", {})
frame_normal = Vector(
    topology_report.get("canvas_wave_qa", {})
    .get("coordinate_frame", {})
    .get("surface_normal_local", (0.0, 0.0, 1.0))
)
source_name = str(primary_report.get("source", {}).get("object_name", ""))
source = bpy.data.objects.get(source_name)

helper_objects = []
if helpers is not None:
    for obj in helpers.objects:
        helper_objects.append({
            "name": obj.name,
            "hide_viewport": bool(obj.hide_viewport),
            "hide_get": bool(obj.hide_get()),
            "face_index": int(obj.get("smrn_face_index", -1)),
            "source": str(obj.get("smrn_source_object_name", "")),
            "dimensions": [round(float(value), 6) for value in obj.dimensions],
        })

current_mark_helpers = [
    item for item in helper_objects
    if item["face_index"] >= 0 and item["source"] == source_name
]
selected_face_indices = sorted({item["face_index"] for item in current_mark_helpers})

coverage = None
if preview is not None and source is not None and selected_face_indices:
    vertices = [vertex.co.copy() for vertex in preview.data.vertices]
    polygons = [tuple(polygon.vertices) for polygon in preview.data.polygons]
    bvh = BVHTree.FromPolygons(vertices, polygons, all_triangles=False)
    signed_offsets = []
    distances = []
    per_face = []
    for face_index in selected_face_indices:
        polygon = source.data.polygons[face_index]
        coordinates = [source.data.vertices[index].co.copy() for index in polygon.vertices]
        normal = polygon.normal.copy()
        if normal.dot(frame_normal) < 0.0:
            normal.negate()
        samples = list(coordinates)
        samples.append(sum(coordinates, Vector()) / len(coordinates))
        for index, first in enumerate(coordinates):
            second = coordinates[(index + 1) % len(coordinates)]
            samples.append((first + second) * 0.5)
        face_offsets = []
        face_distances = []
        for point in samples:
            nearest, _candidate_normal, _index, distance = bvh.find_nearest(point)
            if nearest is None:
                continue
            signed = float((nearest - point).dot(normal))
            signed_offsets.append(signed)
            distances.append(float(distance))
            face_offsets.append(signed)
            face_distances.append(float(distance))
        per_face.append({
            "face_index": face_index,
            "minimum_signed_offset": min(face_offsets) if face_offsets else None,
            "maximum_signed_offset": max(face_offsets) if face_offsets else None,
            "maximum_distance": max(face_distances) if face_distances else None,
        })
    tolerance = max(float(topology_report.get("local_edge_scale", 1.0)) * 0.005, 1.0e-5)
    behind = [value for value in signed_offsets if value < -tolerance]
    coverage = {
        "sample_count": len(signed_offsets),
        "tolerance": tolerance,
        "behind_count": len(behind),
        "behind_fraction": len(behind) / max(len(signed_offsets), 1),
        "minimum_signed_offset": min(signed_offsets) if signed_offsets else None,
        "maximum_signed_offset": max(signed_offsets) if signed_offsets else None,
        "maximum_distance": max(distances) if distances else None,
        "faces_with_behind_samples": [
            item for item in per_face
            if item["minimum_signed_offset"] is not None
            and item["minimum_signed_offset"] < -tolerance
        ],
    }

result = {
    "scene": scene.name,
    "preview_name": preview_name,
    "preview_exists": preview is not None,
    "preview_vertices": len(preview.data.vertices) if preview and preview.type == "MESH" else 0,
    "preview_faces": len(preview.data.polygons) if preview and preview.type == "MESH" else 0,
    "preview_show_in_front": bool(preview.show_in_front) if preview else None,
    "working_name": working_name,
    "working_exists": working is not None,
    "helpers_collection": helpers.name if helpers else None,
    "helpers_hidden": bool(helpers.hide_viewport) if helpers else None,
    "helper_count": len(helper_objects),
    "visible_helper_count": sum(not item["hide_get"] for item in helper_objects),
    "current_mark_helper_count": len(current_mark_helpers),
    "visible_current_mark_helper_count": sum(
        not item["hide_get"] for item in current_mark_helpers
    ),
    "current_unique_marked_faces": len(selected_face_indices),
    "selected_face_indices": selected_face_indices,
    "coverage": coverage,
    "helper_objects_head": helper_objects[:12],
    "report": report,
}
print("SMRN_CANVAS_INSPECT=" + json.dumps(result, ensure_ascii=False))
