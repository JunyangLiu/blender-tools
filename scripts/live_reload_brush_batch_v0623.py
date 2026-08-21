"""Hot-reload v0.6.23 and consolidate current marker display objects."""

import importlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import bpy


REPO = Path(r"C:\codex_auto\semantic-mesh-restorer-next")
ADDON_ROOT = REPO / "blender_addon"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

scene = bpy.context.scene
scene["smrn_modal_token"] = ""
scene["smrn_marker_modal_token"] = ""
old_marker_objects = [
    obj.name for obj in bpy.data.objects
    if bool(obj.get("smrn_annotation_only", False))
]

old_addon = sys.modules.get("semantic_mesh_marker_next")
if old_addon is not None:
    try:
        old_addon.unregister()
    except Exception:
        pass
for module_name in tuple(sys.modules):
    if module_name == "semantic_mesh_marker_next" or module_name.startswith("semantic_mesh_marker_next."):
        del sys.modules[module_name]

addon = importlib.import_module("semantic_mesh_marker_next")
addon.register()

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.overlay import (
    rebuild_task_surface_overlays,
    remove_overlay,
    shared_surface_overlay_name,
)
from semantic_mesh_marker_next.raycast import _brush_disc_offsets
from semantic_mesh_marker_next.storage import (
    document_summary,
    load_all_marks,
    rewrite_all_marks,
)


source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
source_before = source_snapshot(source).get("fingerprint", "") if source else ""
summary = document_summary(scene)
task_records = load_all_marks(scene, summary["task_id"])
consolidated = [
    replace(
        record,
        overlay_object_name=shared_surface_overlay_name(record.task_id, record.role),
    )
    for record in task_records
]
for name in {record.overlay_object_name for record in task_records}:
    remove_overlay(name)
if consolidated != task_records:
    replacements = {(record.task_id, record.id): record for record in consolidated}
    rewrite_all_marks(
        scene,
        [
            replacements.get((record.task_id, record.id), record)
            for record in load_all_marks(scene)
        ],
    )
created = rebuild_task_surface_overlays(
    bpy.context, consolidated, scene.smrn_marker_size
)

bpy.context.view_layer.update()
for area in bpy.context.screen.areas:
    area.tag_redraw()

source_after = source_snapshot(source).get("fingerprint", "") if source else ""
new_marker_objects = [
    obj.name for obj in bpy.data.objects
    if bool(obj.get("smrn_annotation_only", False))
]
print("SMRN_BRUSH_BATCH_V0623=" + json.dumps({
    "version": list(addon.bl_info["version"]),
    "records": len(consolidated),
    "marker_objects_before": len(old_marker_objects),
    "marker_objects_after": len(new_marker_objects),
    "created": created,
    "default_brush_rays": len(_brush_disc_offsets(12)),
    "source_fingerprint_unchanged": source_before == source_after,
    "source_mesh_modified": False,
    "whole_vehicle_search": False,
}, ensure_ascii=False, separators=(",", ":")))
