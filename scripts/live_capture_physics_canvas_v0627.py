"""Capture the active viewport without hiding the complete vehicle body."""

import json
from pathlib import Path

import bpy


OUTPUT = Path(r"C:\codex_auto\semantic_mesh_restorer_maus_turret\qa_physics_canvas_v0627.png")
scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
old_filepath = scene.render.filepath
old_format = scene.render.image_settings.file_format
captured = False
try:
    scene.render.filepath = str(OUTPUT)
    scene.render.image_settings.file_format = "PNG"
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((item for item in area.regions if item.type == "WINDOW"), None)
            if region is None:
                continue
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.render.opengl(write_still=True, view_context=True)
            captured = OUTPUT.exists()
            break
        if captured:
            break
finally:
    scene.render.filepath = old_filepath
    scene.render.image_settings.file_format = old_format

print("SMRN_PHYSICS_CANVAS_CAPTURE_V0627=" + json.dumps({
    "captured": captured,
    "path": str(OUTPUT),
    "source_visible": bool(source and source.visible_get(view_layer=bpy.context.view_layer)),
}, ensure_ascii=False, separators=(",", ":")))
