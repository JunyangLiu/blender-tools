"""Hot-reload v0.6.28 while proving the source and semantic marks are unchanged."""

import hashlib
import importlib
import json
import sys
from pathlib import Path

import bpy


ADDON_ROOT = Path(r"C:\codex_auto\semantic-mesh-restorer-next\blender_addon")
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))


def mark_storage_digest(scene):
    payload = {
        key: str(scene.get(key, ""))
        for key in scene.keys()
        if key == "smrn_document_json"
        or key.startswith("smrn_chunk_")
        or key.startswith("smrn_index_")
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), len(payload)


scene = bpy.context.scene
source_name = str(scene.get("smrn_source_name", ""))
source = bpy.data.objects.get(source_name)
before = {
    "source": source_name,
    "vertices": len(source.data.vertices) if source else 0,
    "polygons": len(source.data.polygons) if source else 0,
}
marks_before = mark_storage_digest(scene)
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
marks_after = mark_storage_digest(scene)
erase_property = bpy.ops.smrn.mark_surface.get_rna_type().properties.get("erase")
if before != after:
    raise RuntimeError("Reload changed source model: " + repr({"before": before, "after": after}))
if marks_before != marks_after:
    raise RuntimeError("Reload changed semantic marks")
if erase_property is None:
    raise RuntimeError("Role-specific eraser property was not registered")

for area in bpy.context.screen.areas if bpy.context.screen else ():
    if area.type == "VIEW_3D":
        area.tag_redraw()

print("SMRN_MARK_ERASER_RELOAD_V0628=" + json.dumps({
    "version": list(addon.bl_info["version"]),
    "source_unchanged": True,
    "marks_unchanged": True,
    "mark_storage_keys": marks_after[1],
    "eraser_registered": True,
    "state": after,
}, ensure_ascii=False, separators=(",", ":")))
