"""Reload v0.5.11 while preserving the current surface review state."""

import importlib
import json
from pathlib import Path
import sys

import bpy


ROOT = r"C:\codex_auto\semantic-mesh-restorer-next\blender_addon"
PACKAGE = "semantic_mesh_marker_next"
OUTPUT = Path(
    r"C:\codex_auto\semantic_mesh_restorer_maus_turret\qa_surface_smoothing_range_v0511.png"
)

scene = bpy.context.scene
old_strength = float(getattr(scene, "smrn_surface_smooth_strength", 0.22))
source_name = str(scene.get("smrn_source_name", ""))
candidate_name = str(scene.get("smrn_surface_candidate_name", ""))
working_name = str(scene.get("smrn_surface_working_name", ""))

old_anchors = importlib.import_module(PACKAGE + ".anchors")
source = bpy.data.objects.get(source_name)
if source is None or source.type != "MESH":
    raise RuntimeError("Current semantic source is unavailable")
before = old_anchors.source_snapshot(source)

old = sys.modules.get(PACKAGE)
if old is not None:
    old.unregister()
for name in tuple(sys.modules):
    if name == PACKAGE or name.startswith(PACKAGE + "."):
        del sys.modules[name]
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

addon = importlib.import_module(PACKAGE)
addon.register()
scene.smrn_surface_smooth_strength = max(0.0, min(1.0, old_strength))

anchors = importlib.import_module(PACKAGE + ".anchors")
storage = importlib.import_module(PACKAGE + ".storage")
scene_state = importlib.import_module(PACKAGE + ".scene_state")
after = anchors.source_snapshot(source)
if before["fingerprint"] != after["fingerprint"]:
    raise RuntimeError("Add-on reload unexpectedly changed the source mesh")

candidate = bpy.data.objects.get(candidate_name)
working = bpy.data.objects.get(working_name)
required = tuple(obj for obj in (source, candidate) if obj is not None)
scene_state.keep_model_visible(scene, required)
marks = storage.load_all_marks(scene)
prop = bpy.types.Scene.bl_rna.properties["smrn_surface_smooth_strength"]

bpy.context.view_layer.update()
bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
bpy.ops.screen.screenshot(filepath=str(OUTPUT))

print("SMRN_SMOOTHING_RELOAD_V0511=" + json.dumps({
    "addon_version": list(addon.bl_info["version"]),
    "blend": bpy.data.filepath,
    "source": source.name,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "source_fingerprint": after["fingerprint"],
    "source_unchanged": before["fingerprint"] == after["fingerprint"],
    "strength_preserved": float(scene.smrn_surface_smooth_strength),
    "strength_min": float(prop.hard_min),
    "strength_max": float(prop.hard_max),
    "candidate": candidate.name if candidate else None,
    "candidate_preserved": candidate is not None,
    "candidate_unaccepted": bool(candidate and not candidate.get("smrn_accepted", False)),
    "working_preserved": working is not None,
    "marks_preserved": len(marks),
    "screenshot": str(OUTPUT),
    "screenshot_exists": OUTPUT.exists(),
}, ensure_ascii=False, separators=(",", ":")))
