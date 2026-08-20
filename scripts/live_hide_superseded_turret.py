import importlib
import json
import sys
from pathlib import Path

import bpy


REPO = Path(r"C:\codex_auto\semantic-mesh-restorer-next")
ADDON_ROOT = REPO / "blender_addon"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

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

from semantic_mesh_marker_next.constants import SOURCE_NAME_KEY
from semantic_mesh_marker_next.scene_state import keep_model_visible


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get(SOURCE_NAME_KEY, "")))
old = bpy.data.objects.get("turret")
if source is None or source.type != "MESH":
    raise RuntimeError("当前语义源不存在，停止处理")
if old is None or old.type != "MESH":
    raise RuntimeError("没有找到预期的旧 turret 对象，停止处理")

source_dims = tuple(float(value) for value in source.dimensions)
old_dims = tuple(float(value) for value in old.dimensions)
relative_dimension_delta = max(
    abs(current - previous) / max(abs(current), 1.0)
    for current, previous in zip(source_dims, old_dims)
)
if relative_dimension_delta > 0.03:
    raise RuntimeError("旧 turret 与当前语义源尺寸差异超过 3%，拒绝自动隐藏")

before = {
    "name": old.name,
    "visible": bool(old.visible_get(view_layer=bpy.context.view_layer)),
    "vertices": len(old.data.vertices),
    "faces": len(old.data.polygons),
    "dimensions": old_dims,
    "collections": [collection.name for collection in old.users_collection],
}
old["smrn_superseded_source_only"] = True
old["smrn_superseded_by"] = source.name
keep_model_visible(scene, (source,))
old.hide_viewport = True
old.hide_render = True
old.hide_set(True)

bpy.context.view_layer.objects.active = source
source.select_set(True)
bpy.ops.wm.save_mainfile()
result = {
    "superseded": before,
    "dimension_delta": relative_dimension_delta,
    "hidden_after": bool(old.hide_viewport and old.hide_render and old.hide_get()),
    "source": {
        "name": source.name,
        "visible": bool(source.visible_get(view_layer=bpy.context.view_layer)),
        "vertices": len(source.data.vertices),
        "faces": len(source.data.polygons),
    },
    "saved": bpy.data.filepath,
}
print("SMRN_SUPERSEDED_TURRET_FIX=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
