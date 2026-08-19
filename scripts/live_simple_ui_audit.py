"""Show and capture the compact default panel in the isolated Maus Blender."""

import json
from pathlib import Path

import bpy


OUTPUT = Path(r"C:\codex_auto\semantic-mesh-restorer-next\artifacts\maus_simple_panel.png")
scene = bpy.context.scene
scene.smrn_show_advanced = False

view_areas = []
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        area.spaces.active.show_region_ui = True
        ui_region = next((region for region in area.regions if region.type == "UI"), None)
        if ui_region is not None and hasattr(ui_region, "active_panel_category"):
            ui_region.active_panel_category = "语义标记 Next"
        area.tag_redraw()
        view_areas.append({"width": area.width, "height": area.height})

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
bpy.ops.screen.screenshot(filepath=str(OUTPUT))

rotational_name = str(scene.get("smrn_rotational_candidate_name", ""))
handle_name = str(scene.get("smrn_handle_candidate_name", ""))
print("SMRN_SIMPLE_UI_AUDIT=" + json.dumps({
    "screenshot": str(OUTPUT),
    "advanced_open": bool(scene.smrn_show_advanced),
    "view_areas": view_areas,
    "rotational_candidate_visible": bool(
        rotational_name and bpy.data.objects.get(rotational_name)
        and bpy.data.objects.get(rotational_name).visible_get()
    ),
    "handle_candidate_visible": bool(
        handle_name and bpy.data.objects.get(handle_name)
        and bpy.data.objects.get(handle_name).visible_get()
    ),
}, ensure_ascii=False, separators=(",", ":")))
