"""Capture overview and close-up QA views without hiding the source model."""

import json
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

from semantic_mesh_marker_next.rotational_blender import _source_for_targets, _task_records


OUTPUT_DIR = Path(r"C:\codex_auto\semantic-mesh-restorer-next\artifacts")
OUTPUT_DIR.mkdir(exist_ok=True)
OVERVIEW = OUTPUT_DIR / "maus_rotational_candidate_overview.png"
CLOSEUP = OUTPUT_DIR / "maus_rotational_candidate_closeup.png"
TOP = OUTPUT_DIR / "maus_rotational_candidate_top.png"


def world_bounds(obj):
    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    minimum = Vector(tuple(min(point[index] for point in points) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in points) for index in range(3)))
    return minimum, maximum


scene = bpy.context.scene
targets, _excludes = _task_records(scene)
source, _snapshot = _source_for_targets(scene, targets)
candidate_name = str(scene.get("smrn_rotational_candidate_name", ""))
candidate = bpy.data.objects.get(candidate_name)
if candidate is None:
    raise RuntimeError("No current rotational candidate")

# Visibility remains additive: no source object, collection, or view layer is hidden.
source.hide_set(False)
source.hide_viewport = False
candidate.hide_set(False)
candidate.hide_viewport = False
candidate.show_in_front = True
candidate.show_wire = True
candidate.color = (0.02, 0.55, 1.0, 1.0)
for obj in bpy.context.selected_objects:
    obj.select_set(False)
candidate.select_set(True)
bpy.context.view_layer.objects.active = candidate

window = bpy.context.window
area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
space = area.spaces.active
space.shading.color_type = "OBJECT"
region_3d = space.region_3d
region_3d.view_perspective = "PERSP"
region_3d.view_rotation = Quaternion((0.742, 0.248, -0.560, -0.271)).normalized()

source_min, source_max = world_bounds(source)
candidate_min, candidate_max = world_bounds(candidate)

region_3d.view_location = (source_min + source_max) * 0.5
region_3d.view_distance = max((source_max - source_min).length * 0.62, 28.0)
bpy.context.view_layer.update()
with bpy.context.temp_override(window=window, area=area):
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
    bpy.ops.screen.screenshot(filepath=str(OVERVIEW))

region_3d.view_location = (candidate_min + candidate_max) * 0.5
region_3d.view_distance = max((candidate_max - candidate_min).length * 1.55, 16.0)
bpy.context.view_layer.update()
with bpy.context.temp_override(window=window, area=area):
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
    bpy.ops.screen.screenshot(filepath=str(CLOSEUP))

region_3d.view_perspective = "ORTHO"
region_3d.view_rotation = Quaternion((1.0, 0.0, 0.0, 0.0))
region_3d.view_distance = max((candidate_max - candidate_min).length * 1.35, 14.0)
bpy.context.view_layer.update()
with bpy.context.temp_override(window=window, area=area):
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
    bpy.ops.screen.screenshot(filepath=str(TOP))

print("SMRN_VISUAL_QA=" + json.dumps({
    "overview": str(OVERVIEW),
    "closeup": str(CLOSEUP),
    "top": str(TOP),
    "source": source.name,
    "source_visible": source.visible_get(),
    "candidate": candidate.name,
    "candidate_visible": candidate.visible_get(),
    "source_bounds": [list(source_min), list(source_max)],
    "candidate_bounds": [list(candidate_min), list(candidate_max)],
}, ensure_ascii=False, separators=(",", ":")))
candidate.show_in_front = False
