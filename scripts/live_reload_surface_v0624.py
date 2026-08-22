"""Hot-reload v0.6.24 without changing the current model or marks."""

import importlib
import json
import sys
from pathlib import Path

import bpy


ADDON_ROOT = Path(r"C:\codex_auto\semantic-mesh-restorer-next\blender_addon")
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

scene = bpy.context.scene
source_name = str(scene.get("smrn_source_name", ""))
source = bpy.data.objects.get(source_name)
before = {
    "source": source_name,
    "vertices": len(source.data.vertices) if source else 0,
    "polygons": len(source.data.polygons) if source else 0,
}
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
source = bpy.data.objects.get(source_name)
after = {
    "source": source_name,
    "vertices": len(source.data.vertices) if source else 0,
    "polygons": len(source.data.polygons) if source else 0,
}
if before != after:
    raise RuntimeError("Reload changed source model: " + repr({"before": before, "after": after}))
print("SMRN_SURFACE_RELOAD_V0624=" + json.dumps({
    "version": list(addon.bl_info["version"]),
    "source_unchanged": True,
    "state": after,
}, ensure_ascii=False, separators=(",", ":")))
