"""Reload v0.5.5 in the isolated Maus Blender without changing geometry or settings."""

import importlib
import json
import sys

import bpy


ROOT = r"C:\codex_auto\semantic-mesh-restorer-next\blender_addon"
PACKAGE = "semantic_mesh_marker_next"

old = sys.modules.get(PACKAGE)
if old is not None:
    try:
        old.unregister()
    except Exception as error:
        print("SMRN_OLD_UNREGISTER_WARNING=" + repr(error))
for name in tuple(sys.modules):
    if name == PACKAGE or name.startswith(PACKAGE + "."):
        del sys.modules[name]
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
addon = importlib.import_module(PACKAGE)
addon.register()

scene = bpy.context.scene
print("SMRN_SURFACE_RELOAD=" + json.dumps({
    "addon_version": list(addon.bl_info["version"]),
    "blend": bpy.data.filepath,
    "height_mode": scene.smrn_surface_height_mode,
    "normal_mode": scene.smrn_surface_normal_mode,
    "source": str(scene.get("smrn_source_name", "")),
}, ensure_ascii=False, separators=(",", ":")))
