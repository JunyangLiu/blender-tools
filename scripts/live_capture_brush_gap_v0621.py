"""Capture the current viewport and report bounded brush-state metadata."""

import json
from pathlib import Path

import bpy


repo = Path(r"C:\codex_auto\semantic-mesh-restorer-next")
scene = bpy.context.scene
path = repo / "artifacts" / "brush_gap_current_v0621.png"
path.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.screen.screenshot(filepath=str(path))

areas = []
for area in bpy.context.screen.areas:
    if area.type != "VIEW_3D":
        continue
    region = next((item for item in area.regions if item.type == "WINDOW"), None)
    if region is not None:
        areas.append({
            "area": [area.x, area.y, area.width, area.height],
            "window_region": [region.x, region.y, region.width, region.height],
        })

source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
working = bpy.data.objects.get(str(scene.get("smrn_surface_working_name", "")))
print("SMRN_BRUSH_GAP_CAPTURE=" + json.dumps({
    "screenshot": str(path),
    "render_size": list(bpy.context.window.pixel_size * value for value in bpy.context.window_manager.windows[0].screen.areas[0:0]),
    "view3d_areas": areas,
    "source": source.name if source else None,
    "source_display": source.display_type if source else None,
    "working": working.name if working else None,
    "working_visible": bool(working and working.visible_get(view_layer=bpy.context.view_layer)),
    "proxy_enabled": bool(working and working.get("smrn_mark_proxy_face_indices", False)),
    "target_marks": sum(1 for obj in bpy.data.objects if "TARGET" in obj.name and obj.name.startswith("SMRN_MARK_")),
    "whole_vehicle_search": False,
    "source_mesh_modified": False,
}, ensure_ascii=False, separators=(",", ":")))
