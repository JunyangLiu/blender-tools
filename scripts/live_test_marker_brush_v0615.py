"""Read-only timing and coverage test for the locked-object brush path."""

import importlib
import json
import sys
import time

import bpy


ROOT = r"C:\codex_auto\semantic-mesh-restorer-next\blender_addon"
PACKAGE = "semantic_mesh_marker_next"

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
raycast = importlib.import_module(PACKAGE + ".raycast")
storage = importlib.import_module(PACKAGE + ".storage")
context = bpy.context
scene = context.scene
source_name = str(scene.get("smrn_source_name", ""))
source = bpy.data.objects.get(source_name)
before_counts = dict(storage.document_summary(scene)["role_counts"])
area = next(area for area in context.window.screen.areas if area.type == "VIEW_3D")
region = next(region for region in area.regions if region.type == "WINDOW")
space = area.spaces.active
center = (region.width * 0.5, region.height * 0.5)
durations = []
hits = []
with context.temp_override(area=area, region=region, space_data=space):
    for _index in range(3):
        started = time.perf_counter()
        hits = raycast.brush_object_hits(
            context,
            region,
            space.region_3d,
            center,
            int(scene.smrn_magnetic_radius_px),
            source_name,
        )
        durations.append((time.perf_counter() - started) * 1000.0)
after_counts = dict(storage.document_summary(scene)["role_counts"])
print("SMRN_MARKER_BRUSH_TEST_V0615=" + json.dumps({
    "probe_count": len(raycast._brush_disc_offsets(int(scene.smrn_magnetic_radius_px))),
    "visible_faces": len(hits),
    "mean_ms": sum(durations) / len(durations),
    "max_ms": max(durations),
    "marks_unchanged": before_counts == after_counts,
    "source_visible": bool(source and source.visible_get(view_layer=context.view_layer)),
}, ensure_ascii=False, separators=(",", ":")))
