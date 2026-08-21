"""Hot-reload v0.6.22 and re-anchor current marker overlays to the visible proxy."""

import importlib
import json
import sys
from pathlib import Path

import bpy


REPO = Path(r"C:\codex_auto\semantic-mesh-restorer-next")
ADDON_ROOT = REPO / "blender_addon"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

scene = bpy.context.scene
# End any old modal operator without deleting marks.
scene["smrn_modal_token"] = ""
scene["smrn_marker_modal_token"] = ""
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

from semantic_mesh_marker_next.constants import EXCLUDE_COLOR, TARGET_COLOR, TARGET_ROLE
from semantic_mesh_marker_next.overlay import create_surface_overlay, remove_overlay
from semantic_mesh_marker_next.storage import document_summary, load_all_marks


source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
working = bpy.data.objects.get(str(scene.get("smrn_surface_working_name", "")))
compatible = bool(
    source is not None
    and working is not None
    and source.type == "MESH"
    and working.type == "MESH"
    and len(source.data.vertices) == len(working.data.vertices)
    and len(source.data.polygons) == len(working.data.polygons)
    and str(working.get("smrn_mark_proxy_source", "")) == source.name
)
summary = document_summary(scene)
records = load_all_marks(scene, summary["task_id"])
refreshed = 0
failed = []
if compatible:
    for record in records:
        if record.hit_object_name != source.name:
            continue
        name = record.overlay_object_name
        temporary_name = name + "_V0622_REFRESH"
        remove_overlay(temporary_name)
        hit = {
            "hit_object_name": source.name,
            "source_object_name": source.name,
            "raycast_object_name": working.name,
            "face_index": int(record.face_index),
            "world_location": record.world_location,
            "world_normal": record.world_normal,
            "toward_viewer": record.world_normal,
        }
        try:
            replacement, _offset, _normal = create_surface_overlay(
                bpy.context,
                temporary_name,
                hit,
                TARGET_COLOR if record.role == TARGET_ROLE else EXCLUDE_COLOR,
                record.semantic_radius or scene.smrn_marker_size,
            )
            remove_overlay(name)
            replacement.name = name
            if replacement.data is not None:
                replacement.data.name = name + "_Mesh"
            refreshed += 1
        except Exception as error:
            remove_overlay(temporary_name)
            failed.append({"id": record.id, "face": int(record.face_index), "error": str(error)})

bpy.context.view_layer.update()
for area in bpy.context.screen.areas:
    area.tag_redraw()

probe_faces = {190868, 190821, 191293, 189606, 189601, 189624}
probe = []
for record in records:
    if int(record.face_index) not in probe_faces:
        continue
    overlay = bpy.data.objects.get(record.overlay_object_name)
    probe.append({
        "face": int(record.face_index),
        "overlay": record.overlay_object_name,
        "raycast_geometry": str(overlay.get("smrn_raycast_object_name", "")) if overlay else "",
        "visible": bool(overlay and overlay.visible_get(view_layer=bpy.context.view_layer)),
    })

print("SMRN_BRUSH_OVERLAY_V0622=" + json.dumps({
    "version": list(addon.bl_info["version"]),
    "source": source.name if source else None,
    "working": working.name if working else None,
    "topology_compatible": compatible,
    "records_considered": len(records),
    "overlays_refreshed": refreshed,
    "failures": failed[:8],
    "probe": probe,
    "source_mesh_modified": False,
    "whole_vehicle_search": False,
}, ensure_ascii=False, separators=(",", ":")))
