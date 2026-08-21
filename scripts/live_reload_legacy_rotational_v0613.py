"""Reload v0.6.13 and prove that the live scene state is preserved."""

import importlib
import json
import sys

import bpy


ROOT = r"C:\codex_auto\semantic-mesh-restorer-next\blender_addon"
PACKAGE = "semantic_mesh_marker_next"


def probe():
    scene = bpy.context.scene
    source_name = str(scene.get("smrn_source_name", ""))
    source = bpy.data.objects.get(source_name)
    anchors = importlib.import_module(PACKAGE + ".anchors")
    storage = importlib.import_module(PACKAGE + ".storage")
    return {
        "blend": bpy.data.filepath,
        "source": source_name,
        "source_fingerprint": anchors.source_snapshot(source)["fingerprint"],
        "role_counts": storage.document_summary(scene)["role_counts"],
        "rotational_candidate": str(scene.get("smrn_rotational_candidate_name", "")),
        "surface_candidate": str(scene.get("smrn_surface_candidate_name", "")),
    }


if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
old = importlib.import_module(PACKAGE)
before = probe()
try:
    old.unregister()
except Exception as error:
    print("SMRN_OLD_UNREGISTER_WARNING=" + repr(error))
for name in tuple(sys.modules):
    if name == PACKAGE or name.startswith(PACKAGE + "."):
        del sys.modules[name]
addon = importlib.import_module(PACKAGE)
addon.register()
after = probe()
if before != after:
    raise RuntimeError("Reload changed scene state: " + repr({"before": before, "after": after}))
if tuple(addon.bl_info["version"]) != (0, 6, 13):
    raise RuntimeError("Unexpected add-on version: " + repr(addon.bl_info["version"]))
print("SMRN_LEGACY_RELOAD_V0613=" + json.dumps({
    "addon_version": list(addon.bl_info["version"]),
    "scene_preserved": True,
    "state": after,
}, ensure_ascii=False, separators=(",", ":")))
