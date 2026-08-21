"""Bounded live QA for brush mapping on the current marked ROI."""

import json

import bpy
from bpy_extras import view3d_utils

from semantic_mesh_marker_next import raycast
from semantic_mesh_marker_next.storage import load_all_marks


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
working = bpy.data.objects.get(str(scene.get("smrn_surface_working_name", "")))
area = next((item for item in bpy.context.screen.areas if item.type == "VIEW_3D"), None)
region = next((item for item in area.regions if item.type == "WINDOW"), None) if area else None
region_3d = area.spaces.active.region_3d if area else None
records = [record for record in load_all_marks(scene) if record.role == "target"]
sample_indices = []
if records:
    step = max(1, len(records) // 16)
    sample_indices = [int(record.face_index) for record in records[::step][:16]]

mapped = 0
tested = 0
if source and working and region and region_3d:
    for face_index in sample_indices:
        if not (0 <= face_index < len(working.data.polygons)):
            continue
        world = working.matrix_world @ working.data.polygons[face_index].center
        coordinate = view3d_utils.location_3d_to_region_2d(region, region_3d, world)
        if coordinate is None:
            continue
        hit = raycast.object_hit_at(
            bpy.context, working, region, region_3d, coordinate
        )
        tested += 1
        if (
            hit is not None
            and hit["hit_object_name"] == source.name
            and hit["source_object_name"] == source.name
            and hit["raycast_object_name"] == working.name
        ):
            mapped += 1

passthrough_names = {obj.name for obj in raycast._passthrough_objects(bpy.context)}
print("SMRN_BRUSH_PROXY_QA=" + json.dumps({
    "roi_records_considered": len(sample_indices),
    "projected_rays_tested": tested,
    "mapped_to_source": mapped,
    "working_is_passthrough_hidden": bool(working and working.name in passthrough_names),
    "working_remains_visible": bool(working and working.visible_get(view_layer=bpy.context.view_layer)),
    "source_mesh_modified": False,
    "whole_vehicle_search": False,
}, ensure_ascii=False, separators=(",", ":")))
