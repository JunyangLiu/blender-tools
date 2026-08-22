"""Hot-reload v0.6.26 while proving current source and marks are preserved."""

import importlib
import json
import sys
from pathlib import Path

import bpy


ADDON_ROOT = Path(r"C:\codex_auto\semantic-mesh-restorer-next\blender_addon")
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))


def probe():
    scene = bpy.context.scene
    anchors = importlib.import_module("semantic_mesh_marker_next.anchors")
    storage = importlib.import_module("semantic_mesh_marker_next.storage")
    source_name = str(scene.get("smrn_source_name", ""))
    source = bpy.data.objects.get(source_name)
    return {
        "source": source_name,
        "source_fingerprint": anchors.source_snapshot(source)["fingerprint"],
        "vertices": len(source.data.vertices),
        "polygons": len(source.data.polygons),
        "role_counts": storage.document_summary(scene)["role_counts"],
        "source_visible": not source.hide_get(),
    }


before = probe()
scene = bpy.context.scene
scene["smrn_modal_token"] = ""
scene["smrn_marker_modal_token"] = ""
old = sys.modules.get("semantic_mesh_marker_next")
if old is not None:
    try:
        old.unregister()
    except Exception as error:
        print("SMRN_OLD_UNREGISTER_WARNING=" + repr(error))
for name in tuple(sys.modules):
    if name == "semantic_mesh_marker_next" or name.startswith("semantic_mesh_marker_next."):
        del sys.modules[name]
addon = importlib.import_module("semantic_mesh_marker_next")
addon.register()
after = probe()
if before != after:
    raise RuntimeError("Reload changed source or marks: " + repr({"before": before, "after": after}))
if tuple(addon.bl_info["version"]) != (0, 6, 26):
    raise RuntimeError("Unexpected add-on version: " + repr(addon.bl_info["version"]))
print("SMRN_HANDLE_RELOAD_V0626=" + json.dumps({
    "version": list(addon.bl_info["version"]),
    "scene_preserved": True,
    "state": after,
}, ensure_ascii=False, separators=(",", ":")))
