"""Restore a stable top three-quarter modeling view on the complete source."""

import json
import math
from pathlib import Path

import bpy


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
if source is None:
    raise RuntimeError("Current semantic source is missing")

source.hide_set(False)
source.hide_viewport = False
source.hide_render = False
for obj in bpy.data.objects:
    if bool(obj.get("smrn_accepted", False)):
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.show_in_front = False

window = bpy.context.window
area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
region = next(region for region in area.regions if region.type == "WINDOW")
space = area.spaces.active

if bpy.context.mode != "OBJECT":
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.object.mode_set(mode="OBJECT")
for obj in tuple(bpy.context.selected_objects):
    obj.select_set(False)
source.select_set(True)
bpy.context.view_layer.objects.active = source

with bpy.context.temp_override(window=window, area=area, region=region):
    bpy.ops.view3d.view_axis(type="TOP", align_active=False, relative=False)
    bpy.ops.view3d.view_orbit(type="ORBITDOWN")
    bpy.ops.view3d.view_orbit(type="ORBITDOWN")
    bpy.ops.view3d.view_orbit(type="ORBITRIGHT")
    bpy.ops.view3d.view_roll(angle=math.radians(45.0))
    bpy.ops.view3d.view_selected(use_all_regions=False)

space.region_3d.view_perspective = "PERSP"
space.region_3d.view_distance *= 1.08
bpy.context.view_layer.update()
bpy.ops.wm.save_mainfile()

output = Path(r"C:\codex_auto\semantic-mesh-restorer-next\artifacts\rotational_ring_accepted_standard_view_v0613.png")
output.parent.mkdir(parents=True, exist_ok=True)
with bpy.context.temp_override(window=window, area=area):
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
    bpy.ops.screen.screenshot(filepath=str(output))

print("SMRN_STANDARD_VIEW=" + json.dumps({
    "source": source.name,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "view_perspective": space.region_3d.view_perspective,
    "view_distance": space.region_3d.view_distance,
    "screenshot": str(output),
    "saved_blend": bpy.data.filepath,
}, ensure_ascii=False, separators=(",", ":")))
