"""Create the trusted pre-handle checkpoint for the active Maus source."""

import json
import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.handle_blender import _checkpoint


scene = bpy.context.scene
source = bpy.data.objects.get("turret_v96_with_rear_drum_L_selectable")
before = source_snapshot(source)
checkpoint = _checkpoint(scene, source)
after = source_snapshot(source)
print("SMRN_HANDLE_CHECKPOINT=" + json.dumps({
    "checkpoint": checkpoint,
    "exists": __import__("pathlib").Path(checkpoint).exists(),
    "source": source.name,
    "source_unchanged": before["fingerprint"] == after["fingerprint"],
    "source_visible": source.visible_get(),
    "topology": [len(source.data.vertices), len(source.data.edges), len(source.data.polygons)],
}, ensure_ascii=False, separators=(",", ":")))
