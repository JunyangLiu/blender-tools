"""Read-only live proof that one brush dab can cover multiple visible faces."""

import importlib
import json
import sys

import bpy


ROOT = r"C:\codex_auto\semantic-mesh-restorer-next\blender_addon"
PACKAGE = "semantic_mesh_marker_next"

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
raycast = importlib.import_module(PACKAGE + ".raycast")
storage = importlib.import_module(PACKAGE + ".storage")
context = bpy.context
scene = context.scene
before_counts = dict(storage.document_summary(scene)["role_counts"])
area = next(area for area in context.window.screen.areas if area.type == "VIEW_3D")
region = next(region for region in area.regions if region.type == "WINDOW")
space = area.spaces.active
center = (region.width * 0.5, region.height * 0.5)
with context.temp_override(area=area, region=region, space_data=space):
    hits = raycast.brush_scene_hits(
        context, region, space.region_3d, center, int(scene.smrn_magnetic_radius_px)
    )
after_counts = dict(storage.document_summary(scene)["role_counts"])
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
print("SMRN_MARKER_BRUSH_TEST_V0614=" + json.dumps({
    "center_visible_faces": len(hits),
    "unique_face_keys": len({(hit["hit_object_name"], hit["face_index"]) for hit in hits}),
    "marks_unchanged": before_counts == after_counts,
    "source_visible": bool(source and source.visible_get(view_layer=context.view_layer)),
}, ensure_ascii=False, separators=(",", ":")))
