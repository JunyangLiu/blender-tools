"""Capture the active viewport for compact multifold canvas visual QA."""

import json
from pathlib import Path

import bpy


OUTPUT = Path(r"C:\codex_auto\semantic_mesh_restorer_maus_turret\qa_multifold_canvas_v063.png")
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

print("SMRN_MULTIFOLD_CANVAS_CAPTURE_V063=" + json.dumps({
    "captured": captured,
    "path": str(OUTPUT),
}, ensure_ascii=False, separators=(",", ":")))
