"""Capture a compact non-through close-up of the inward-backed ring."""

import json
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector


OUTPUT = Path(r"C:\codex_auto\semantic-mesh-restorer-next\artifacts\rotational_inward_backing_closeup_v0613.png")
scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
candidate = bpy.data.objects.get(str(scene.get("smrn_rotational_candidate_name", "")))
if source is None or candidate is None:
    raise RuntimeError("Missing source or current rotational candidate")

source.hide_set(False)
source.hide_viewport = False
candidate.hide_set(False)
candidate.hide_viewport = False
candidate.show_in_front = False
candidate.show_wire = False
for obj in tuple(bpy.context.selected_objects):
    obj.select_set(False)
candidate.select_set(True)
bpy.context.view_layer.objects.active = candidate

corners = [candidate.matrix_world @ Vector(corner) for corner in candidate.bound_box]
minimum = Vector(tuple(min(point[index] for point in corners) for index in range(3)))
maximum = Vector(tuple(max(point[index] for point in corners) for index in range(3)))

window = bpy.context.window
area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
space = area.spaces.active
space.shading.color_type = "OBJECT"
region_3d = space.region_3d
region_3d.view_perspective = "PERSP"
region_3d.view_rotation = Quaternion((0.826, 0.303, -0.449, -0.157)).normalized()
region_3d.view_location = (minimum + maximum) * 0.5
region_3d.view_distance = max((maximum - minimum).length * 0.72, 7.0)
bpy.context.view_layer.update()

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
with bpy.context.temp_override(window=window, area=area):
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
    bpy.ops.screen.screenshot(filepath=str(OUTPUT))

print("SMRN_INWARD_BACKING_CLOSEUP=" + json.dumps({
    "screenshot": str(OUTPUT),
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "candidate_visible": candidate.visible_get(view_layer=bpy.context.view_layer),
    "show_in_front": candidate.show_in_front,
    "show_wire": candidate.show_wire,
}, ensure_ascii=False, separators=(",", ":")))
