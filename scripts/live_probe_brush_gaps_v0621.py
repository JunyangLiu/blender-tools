"""Probe only the two user-reported screen-space brush gaps."""

import json

import bpy

from semantic_mesh_marker_next import raycast
from semantic_mesh_marker_next.storage import document_summary, load_all_marks


area = next(item for item in bpy.context.screen.areas if item.type == "VIEW_3D")
region = next(item for item in area.regions if item.type == "WINDOW")
region_3d = area.spaces.active.region_3d
scene = bpy.context.scene
working = bpy.data.objects.get(str(scene.get("smrn_surface_working_name", "")))
summary = document_summary(scene)
marked_faces = {
    (record.hit_object_name, int(record.face_index))
    for record in load_all_marks(scene, summary["task_id"])
}

# Coordinates are bounded to the two visible gaps in the current viewport.
# They are expressed in Blender window units, not image pixels.
points = {
    "small_gap_left": (475, 560),
    "small_gap_center": (520, 560),
    "small_gap_right": (570, 560),
    "large_gap_left": (820, 730),
    "large_gap_center": (930, 745),
    "large_gap_right": (1040, 760),
}

results = {}
for label, window_coordinate in points.items():
    coordinate = (
        window_coordinate[0] - region.x,
        window_coordinate[1] - region.y,
    )
    visible = raycast._sample_visible_hits(
        bpy.context, region, region_3d, coordinate, [(0, 0)]
    )
    direct = raycast.object_hit_at(
        bpy.context, working, region, region_3d, coordinate
    ) if working is not None else None
    visible_hit = visible[0] if visible else None
    results[label] = {
        "coordinate": list(coordinate),
        "visible": ({
            "hit": visible_hit["hit_object_name"],
            "raycast": visible_hit.get("raycast_object_name"),
            "source": visible_hit["source_object_name"],
            "face": visible_hit["face_index"],
        } if visible_hit else None),
        "working_direct": ({
            "hit": direct["hit_object_name"],
            "raycast": direct.get("raycast_object_name"),
            "face": direct["face_index"],
        } if direct else None),
        "already_marked": bool(
            direct and (direct["hit_object_name"], int(direct["face_index"])) in marked_faces
        ),
    }

print("SMRN_BRUSH_GAP_PROBE=" + json.dumps({
    "window": [bpy.context.window.width, bpy.context.window.height],
    "region": [region.x, region.y, region.width, region.height],
    "points": results,
    "whole_vehicle_search": False,
    "source_mesh_modified": False,
}, ensure_ascii=False, separators=(",", ":")))
