"""Prepare the live candidate for user review without changing mesh data."""

import json
import bpy


scene = bpy.context.scene
scene.smrn_show_advanced = True
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
candidate = bpy.data.objects.get(str(scene.get("smrn_rotational_candidate_name", "")))
if source is None or candidate is None:
    raise RuntimeError("Source or independent rotational candidate is missing")
source.hide_set(False)
source.hide_viewport = False
candidate.hide_set(False)
candidate.hide_viewport = False
candidate.show_in_front = False
candidate.show_wire = False
candidate.show_all_edges = False
for obj in bpy.context.selected_objects:
    obj.select_set(False)
candidate.select_set(True)
bpy.context.view_layer.objects.active = candidate
bpy.context.view_layer.update()
print("SMRN_LEGACY_REVIEW=" + json.dumps({
    "source": source.name,
    "source_visible": source.visible_get(),
    "candidate": candidate.name,
    "candidate_visible": candidate.visible_get(),
    "candidate_in_front": candidate.show_in_front,
    "candidate_wire": candidate.show_wire,
    "advanced_open": scene.smrn_show_advanced,
}, ensure_ascii=False, sort_keys=True))
