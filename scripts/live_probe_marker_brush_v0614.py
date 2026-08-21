"""Read-only probe before installing the denser visible-surface brush."""

import importlib
import json
import sys

import bpy


ROOT = r"C:\codex_auto\semantic-mesh-restorer-next\blender_addon"
PACKAGE = "semantic_mesh_marker_next"

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
storage = importlib.import_module(PACKAGE + ".storage")
scene = bpy.context.scene
source_name = str(scene.get("smrn_source_name", ""))
source = bpy.data.objects.get(source_name)
print("SMRN_BRUSH_PROBE=" + json.dumps({
    "blend": bpy.data.filepath,
    "source": source_name,
    "source_visible": bool(source and source.visible_get(view_layer=bpy.context.view_layer)),
    "role_counts": storage.document_summary(scene)["role_counts"],
    "modal_active": bool(scene.get("smrn_modal_token", "")),
    "radius_px": int(scene.smrn_magnetic_radius_px),
}, ensure_ascii=False, separators=(",", ":")))
