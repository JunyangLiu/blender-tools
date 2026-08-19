"""Keep the add-on panel available in the current Maus editing UI."""

import json
import bpy


view_areas = []
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        space.show_region_ui = True
        view_areas.append({
            "width": area.width,
            "height": area.height,
            "sidebar_visible": bool(space.show_region_ui),
        })

scene = bpy.context.scene
source = bpy.data.objects.get("turret_v96_with_rear_drum_L_selectable")
panel_registered = hasattr(bpy.types, "SMRN_PT_marking")
operators_registered = all(hasattr(bpy.ops.smrn, name) for name in (
    "analyze_handle", "build_handle_candidate", "remove_handle_candidate"
))
print("SMRN_HANDLE_UI_AUDIT=" + json.dumps({
    "panel_registered": panel_registered,
    "operators_registered": operators_registered,
    "view_areas": view_areas,
    "source_visible": bool(source and source.visible_get()),
    "candidate_name": str(scene.get("smrn_handle_candidate_name", "")),
}, ensure_ascii=False, separators=(",", ":")))
