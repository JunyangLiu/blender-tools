"""Checkpoint and reload the low-latency dense marker brush."""

import importlib
import json
import os
import sys

import bpy


ROOT = r"C:\codex_auto\semantic-mesh-restorer-next\blender_addon"
PACKAGE = "semantic_mesh_marker_next"
CHECKPOINT = r"C:\codex_auto\semantic_mesh_restorer_maus_turret\maus_turret_before_marker_brush_v0615.blend"


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
        "source_visible": bool(source and source.visible_get(view_layer=bpy.context.view_layer)),
        "role_counts": storage.document_summary(scene)["role_counts"],
        "radius_px": int(scene.smrn_magnetic_radius_px),
    }


if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
old = importlib.import_module(PACKAGE)
before = probe()
bpy.context.scene["smrn_modal_token"] = ""
bpy.context.window.cursor_modal_restore()
bpy.ops.wm.save_as_mainfile(filepath=CHECKPOINT, copy=True)
if not os.path.isfile(CHECKPOINT):
    raise RuntimeError("Checkpoint was not written: " + CHECKPOINT)
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
if tuple(addon.bl_info["version"]) != (0, 6, 15):
    raise RuntimeError("Unexpected add-on version: " + repr(addon.bl_info["version"]))
raycast = importlib.import_module(PACKAGE + ".raycast")
print("SMRN_MARKER_BRUSH_RELOAD_V0615=" + json.dumps({
    "addon_version": list(addon.bl_info["version"]),
    "scene_preserved": True,
    "checkpoint": CHECKPOINT,
    "brush_probe_count": len(raycast._brush_disc_offsets(after["radius_px"])),
    "state": after,
}, ensure_ascii=False, separators=(",", ":")))
