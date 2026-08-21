"""Reload v0.6.7 in the isolated Maus Blender and prove scene preservation."""

import importlib
import json
import sys

import bpy


ROOT = r"C:\codex_auto\semantic-mesh-restorer-next\blender_addon"
PACKAGE = "semantic_mesh_marker_next"


def scene_probe(package):
    scene = bpy.context.scene
    source_name = str(scene.get("smrn_source_name", ""))
    source = bpy.data.objects.get(source_name)
    anchors = importlib.import_module(package + ".anchors")
    storage = importlib.import_module(package + ".storage")
    summary = storage.document_summary(scene)
    return {
        "blend": bpy.data.filepath,
        "source": source_name,
        "source_fingerprint": (
            anchors.source_snapshot(source)["fingerprint"] if source is not None else ""
        ),
        "marks": summary["mark_count"],
        "role_counts": summary["role_counts"],
        "rotational_candidate": str(scene.get("smrn_rotational_candidate_name", "")),
        "handle_candidate": str(scene.get("smrn_handle_candidate_name", "")),
        "surface_candidate": str(scene.get("smrn_surface_candidate_name", "")),
        "mesh_objects": sum(obj.type == "MESH" for obj in bpy.data.objects),
    }


if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
old = importlib.import_module(PACKAGE)
before = scene_probe(PACKAGE)
try:
    old.unregister()
except Exception as error:
    print("SMRN_OLD_UNREGISTER_WARNING=" + repr(error))
for name in tuple(sys.modules):
    if name == PACKAGE or name.startswith(PACKAGE + "."):
        del sys.modules[name]
addon = importlib.import_module(PACKAGE)
addon.register()
after = scene_probe(PACKAGE)

preserved = before == after
if not preserved:
    raise RuntimeError("Reload changed scene state: " + repr({"before": before, "after": after}))
if tuple(addon.bl_info["version"]) != (0, 6, 7):
    raise RuntimeError("Unexpected add-on version: " + repr(addon.bl_info["version"]))

print("SMRN_SURFACE_RELOAD_V067=" + json.dumps({
    "addon_version": list(addon.bl_info["version"]),
    "scene_preserved": preserved,
    "state": after,
}, ensure_ascii=False, separators=(",", ":")))
