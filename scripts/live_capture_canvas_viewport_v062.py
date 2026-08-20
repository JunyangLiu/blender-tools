"""Capture the active viewport after the v0.6.2 outer-envelope rebuild."""

import json
from pathlib import Path

import bpy


OUTPUT = Path(r"C:\codex_auto\semantic_mesh_restorer_maus_turret\qa_canvas_outer_envelope_viewport_v062.png")
scene = bpy.context.scene
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

print("SMRN_CANVAS_VIEWPORT_V062=" + json.dumps({
    "captured": captured,
    "path": str(OUTPUT),
}, ensure_ascii=False, separators=(",", ":")))
