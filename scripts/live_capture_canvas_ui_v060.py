"""Expose the compact panel and capture the v0.6.0 canvas control."""

import json
from pathlib import Path

import bpy

OUTPUT = Path(r"C:\codex_auto\semantic_mesh_restorer_maus_turret\qa_canvas_wave_ui_v060.png")
scene = bpy.context.scene
scene.smrn_show_advanced = False
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        area.spaces.active.show_region_ui = True
        ui_region = next((region for region in area.regions if region.type == "UI"), None)
        if ui_region is not None and hasattr(ui_region, "active_panel_category"):
            ui_region.active_panel_category = "语义标记 Next"
        area.tag_redraw()

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
bpy.ops.screen.screenshot(filepath=str(OUTPUT))
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
print("SMRN_CANVAS_UI=" + json.dumps({
    "screenshot": str(OUTPUT),
    "exists": OUTPUT.exists(),
    "version": [0, 6, 0],
    "canvas_strength": float(scene.smrn_canvas_wave_strength),
    "source_visible": bool(
        bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
        and bpy.data.objects.get(str(scene.get("smrn_source_name", ""))).visible_get()
    ),
}, ensure_ascii=False, separators=(",", ":")))
