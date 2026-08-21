"""Verify the exact flatten candidate and authoritative source in Blender."""

import json
import math

import bpy
from mathutils import Vector


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
preview = bpy.data.objects.get(str(scene.get("smrn_surface_candidate_name", "")))
working = bpy.data.objects.get(str(scene.get("smrn_surface_working_name", "")))
if source is None or preview is None or working is None:
    raise RuntimeError("Exact flatten candidate state is incomplete")

report = json.loads(str(preview.get("smrn_surface_rebuild_report_json", "{}")))
topology = report.get("topology_qa") or {}
planarity = topology.get("planarity_qa") or {}
center = Vector(planarity["plane_center_local"])
normal = Vector(planarity["plane_normal_local"]).normalized()
attribute = working.data.attributes.get("smrn_rebuild_region")
if attribute is None or attribute.domain != "FACE":
    raise RuntimeError("Working mesh lost the persisted rebuild region")
region_faces = [
    polygon for polygon, item in zip(working.data.polygons, attribute.data)
    if int(item.value) == 1
]
region_vertices = {
    index for polygon in region_faces for index in polygon.vertices
}
distances = [
    abs((working.data.vertices[index].co - center).dot(normal))
    for index in region_vertices
]
internal_dihedrals = []
corner_normal_angles = []
region_set = {polygon.index for polygon in region_faces}
edge_faces = {}
for polygon in region_faces:
    for loop_index in polygon.loop_indices:
        corner_normal_angles.append(math.degrees(
            working.data.loops[loop_index].normal.angle(normal, 0.0)
        ))
    for edge_key in polygon.edge_keys:
        edge_faces.setdefault(tuple(sorted(edge_key)), []).append(polygon.index)
for linked in edge_faces.values():
    if len(linked) == 2 and all(index in region_set for index in linked):
        internal_dihedrals.append(math.degrees(
            working.data.polygons[linked[0]].normal.angle(
                working.data.polygons[linked[1]].normal, 0.0
            )
        ))

result = {
    "source": source.name,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "source_unchanged": bool(report.get("source_unchanged")),
    "candidate": preview.name,
    "candidate_visible": preview.visible_get(view_layer=bpy.context.view_layer),
    "candidate_show_in_front": bool(preview.show_in_front),
    "working": working.name,
    "working_hidden": bool(working.hide_get() or working.hide_viewport),
    "region_faces": len(region_faces),
    "region_vertices": len(region_vertices),
    "actual_max_abs_plane_error": max(distances, default=0.0),
    "actual_rms_plane_error": math.sqrt(
        sum(value * value for value in distances) / max(1, len(distances))
    ),
    "internal_dihedral_p95_degrees": sorted(internal_dihedrals)[
        min(len(internal_dihedrals) - 1, int(len(internal_dihedrals) * 0.95))
    ] if internal_dihedrals else 0.0,
    "internal_dihedral_max_degrees": max(internal_dihedrals, default=0.0),
    "custom_corner_normal_max_error_degrees": max(corner_normal_angles, default=0.0),
    "custom_planar_normals_applied": bool(planarity.get("custom_planar_normals_applied")),
    "flipped_faces": topology.get("flipped_faces"),
    "degenerate_faces": topology.get("degenerate_faces"),
    "quality_passed": bool(topology.get("passed")),
    "whole_vehicle_search": False,
}
print("SMRN_EXACT_FLATTEN_VERIFY_V0619=" + json.dumps(
    result, ensure_ascii=False, separators=(",", ":")
))
