"""Diagnose hairline artifacts in the current local flatten result only."""

import json
import math
from pathlib import Path

import bpy
from mathutils.bvhtree import BVHTree


def mesh_stats(obj):
    if obj is None or obj.type != "MESH":
        return None
    mesh = obj.data
    areas = []
    aspects = []
    smooth = 0
    for poly in mesh.polygons:
        area = float(poly.area)
        areas.append(area)
        smooth += int(poly.use_smooth)
        coords = [mesh.vertices[index].co for index in poly.vertices]
        if len(coords) == 3 and area > 1.0e-18:
            lengths = [(coords[(i + 1) % 3] - coords[i]).length for i in range(3)]
            longest = max(lengths)
            altitude = (2.0 * area) / max(longest, 1.0e-18)
            aspects.append(longest / max(altitude, 1.0e-18))
    ordered_areas = sorted(areas)
    ordered_aspects = sorted(aspects)
    def percentile(values, fraction):
        if not values:
            return 0.0
        return values[min(len(values) - 1, int(round((len(values) - 1) * fraction)))]
    return {
        "name": obj.name,
        "visible": bool(obj.visible_get(view_layer=bpy.context.view_layer)),
        "hide_viewport": bool(obj.hide_viewport),
        "show_in_front": bool(obj.show_in_front),
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "faces": len(mesh.polygons),
        "smooth_faces": smooth,
        "area_min": min(areas, default=0.0),
        "area_median": percentile(ordered_areas, 0.5),
        "aspect_p95": percentile(ordered_aspects, 0.95),
        "aspect_max": max(aspects, default=0.0),
        "aspect_over_50": sum(value > 50.0 for value in aspects),
        "aspect_over_100": sum(value > 100.0 for value in aspects),
        "aspect_over_500": sum(value > 500.0 for value in aspects),
    }


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
preview = bpy.data.objects.get(str(scene.get("smrn_surface_candidate_name", "")))
working = bpy.data.objects.get(str(scene.get("smrn_surface_working_name", "")))
report = json.loads(str(scene.get("smrn_surface_last_report_json", "{}")))

overlap = None
if source is not None and preview is not None and preview.type == "MESH":
    depsgraph = bpy.context.evaluated_depsgraph_get()
    source_eval = source.evaluated_get(depsgraph)
    source_mesh = source_eval.to_mesh()
    try:
        tree = BVHTree.FromPolygons(
            [source.matrix_world @ vertex.co for vertex in source_mesh.vertices],
            [tuple(poly.vertices) for poly in source_mesh.polygons],
            all_triangles=False,
        )
        distances = []
        for vertex in preview.data.vertices:
            hit = tree.find_nearest(preview.matrix_world @ vertex.co)
            if hit is not None:
                distances.append(float(hit[3]))
        distances.sort()
        if distances:
            overlap = {
                "samples": len(distances),
                "distance_min": distances[0],
                "distance_median": distances[len(distances) // 2],
                "distance_p95": distances[min(len(distances) - 1, int(len(distances) * 0.95))],
                "distance_max": distances[-1],
                "near_coincident_under_1e_6": sum(value <= 1.0e-6 for value in distances),
                "near_coincident_under_1e_4": sum(value <= 1.0e-4 for value in distances),
            }
    finally:
        source_eval.to_mesh_clear()

result = {
    "source_name_property": str(scene.get("smrn_source_name", "")),
    "candidate_name_property": str(scene.get("smrn_surface_candidate_name", "")),
    "working_name_property": str(scene.get("smrn_surface_working_name", "")),
    "report_status": report.get("status"),
    "report_mode": report.get("mode"),
    "source_unchanged": report.get("source_unchanged"),
    "source": mesh_stats(source),
    "preview": mesh_stats(preview),
    "working": mesh_stats(working),
    "preview_source_overlap": overlap,
    "planarity": (report.get("topology_qa") or {}).get("planarity_qa"),
}
print("SMRN_FLATTEN_HAIRLINES_V0618=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))

path = Path(r"C:\codex_auto\semantic-mesh-restorer-next\artifacts\maus_flatten_hairlines_before_v0618.png")
path.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.screen.screenshot(filepath=str(path))
print("SMRN_UI_SCREENSHOT=" + str(path))
