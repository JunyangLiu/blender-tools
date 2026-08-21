"""Hot-reload v0.6.21 and enable safe brush hits on the visible flatten copy."""

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
scene["smrn_marker_modal_token"] = ""
old_addon = sys.modules.get("semantic_mesh_marker_next")
if old_addon is not None:
    try:
        old_addon.unregister()
    except Exception:
        pass
for module_name in tuple(sys.modules):
    if module_name == "semantic_mesh_marker_next" or module_name.startswith(
        "semantic_mesh_marker_next."
    ):
        del sys.modules[module_name]

addon = importlib.import_module("semantic_mesh_marker_next")
addon.register()
from semantic_mesh_marker_next import raycast
from semantic_mesh_marker_next import surface_rebuild_blender as surface


source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
working = bpy.data.objects.get(str(scene.get("smrn_surface_working_name", "")))
preview = bpy.data.objects.get(str(scene.get("smrn_surface_candidate_name", "")))
compatible = bool(
    source is not None
    and working is not None
    and preview is not None
    and len(source.data.vertices) == len(working.data.vertices)
    and len(source.data.polygons) == len(working.data.polygons)
)
if compatible:
    surface._show_exact_flatten_working_candidate(source, working, preview)

bpy.context.view_layer.update()
for area in bpy.context.screen.areas:
    area.tag_redraw()

proxy_source = raycast._mark_proxy_source(working) if working is not None else None
print("SMRN_BRUSH_V0621=" + json.dumps({
    "version": list(addon.bl_info["version"]),
    "source": source.name if source is not None else None,
    "source_display": source.display_type if source is not None else None,
    "working": working.name if working is not None else None,
    "working_visible": bool(working and working.visible_get(view_layer=bpy.context.view_layer)),
    "topology_compatible": compatible,
    "proxy_source": proxy_source.name if proxy_source is not None else None,
    "face_count": len(source.data.polygons) if source is not None else None,
    "whole_vehicle_search": False,
    "source_mesh_modified": False,
}, ensure_ascii=False, separators=(",", ":")))
