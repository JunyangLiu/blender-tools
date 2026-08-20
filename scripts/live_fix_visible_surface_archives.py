import json
import sys
from pathlib import Path

import bpy


REPO = Path(r"C:\codex_auto\semantic-mesh-restorer-next")
ADDON_ROOT = REPO / "blender_addon"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

import semantic_mesh_marker_next as addon

try:
    addon.unregister()
except Exception:
    pass
addon.register()

from semantic_mesh_marker_next.constants import (
    CANDIDATE_COLLECTION_NAME,
    MODEL_COLLECTION_NAME,
    SOURCE_NAME_KEY,
)
from semantic_mesh_marker_next.scene_state import ensure_scene_roots, keep_model_visible
from semantic_mesh_marker_next.surface_rebuild_blender import ARCHIVE_COLLECTION_NAME


scene = bpy.context.scene
model, candidates, _helpers = ensure_scene_roots(scene)
archive_collection = bpy.data.collections.get(ARCHIVE_COLLECTION_NAME)
if archive_collection is not None:
    if model.children.get(archive_collection.name) is not None:
        model.children.unlink(archive_collection)
    if candidates.children.get(archive_collection.name) is None:
        candidates.children.link(archive_collection)

archives = [obj for obj in bpy.data.objects if bool(obj.get("smrn_archive_only", False))]
before = [
    {
        "name": obj.name,
        "visible": bool(obj.visible_get(view_layer=bpy.context.view_layer)),
        "vertices": len(obj.data.vertices) if obj.type == "MESH" else 0,
        "faces": len(obj.data.polygons) if obj.type == "MESH" else 0,
    }
    for obj in archives
]

keep_model_visible(scene)
for obj in archives:
    obj.hide_viewport = True
    obj.hide_render = True
    obj.hide_set(True)
if archive_collection is not None:
    archive_collection.hide_viewport = True
    archive_collection.hide_render = True

source = bpy.data.objects.get(str(scene.get(SOURCE_NAME_KEY, "")))
source_state = None
if source is not None:
    source_state = {
        "name": source.name,
        "visible": bool(source.visible_get(view_layer=bpy.context.view_layer)),
        "vertices": len(source.data.vertices),
        "faces": len(source.data.polygons),
    }

bpy.ops.wm.save_mainfile()
result = {
    "archive_count": len(archives),
    "archives_before": before,
    "archives_hidden_after": all(obj.hide_viewport and obj.hide_render and obj.hide_get() for obj in archives),
    "archive_parent": CANDIDATE_COLLECTION_NAME if archive_collection is not None else None,
    "source": source_state,
    "saved": bpy.data.filepath,
}
print("SMRN_ARCHIVE_FIX=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
