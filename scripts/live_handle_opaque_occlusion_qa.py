"""Create an opaque visual occlusion check without hiding the vehicle body."""

from pathlib import Path

import bpy


scene = bpy.context.scene
candidate = bpy.data.objects.get(str(scene.get("smrn_handle_candidate_name", "")))
if candidate is None:
    raise RuntimeError("Missing handle candidate")

for obj in bpy.context.selected_objects:
    obj.select_set(False)
candidate.color = (0.02, 0.72, 0.16, 1.0)
candidate.show_wire = False
candidate.show_in_front = False
candidate.select_set(False)

helpers = bpy.data.collections.get("SMR_03_标记与辅助_一键隐藏")
if helpers is not None:
    for obj in list(helpers.all_objects):
        if obj is None:
            continue
        try:
            obj.hide_viewport = True
        except (AttributeError, ReferenceError):
            continue

window = bpy.context.window
area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
area.spaces.active.shading.color_type = "OBJECT"
area.spaces.active.shading.show_shadows = True
area.spaces.active.shading.show_cavity = True
area.spaces.active.shading.cavity_type = "WORLD"
with bpy.context.temp_override(
    window=window,
    area=area,
    region=next(region for region in area.regions if region.type == "WINDOW"),
):
    candidate.select_set(True)
    bpy.context.view_layer.objects.active = candidate
    bpy.ops.view3d.view_selected(use_all_regions=False)
    candidate.select_set(False)
area.spaces.active.region_3d.view_distance *= 1.2
bpy.context.view_layer.update()

output = Path(r"C:\codex_auto\semantic-mesh-restorer-next\artifacts\maus_handle_opaque_occlusion.png")
with bpy.context.temp_override(window=window, area=area):
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
    bpy.ops.screen.screenshot(filepath=str(output))
print("SMRN_HANDLE_OPAQUE_QA=" + str(output))
