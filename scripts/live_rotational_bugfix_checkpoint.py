"""Create a fresh trusted checkpoint before retrying the current rotational marks."""

import json
from pathlib import Path

import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.rotational_blender import (
    _checkpoint,
    _source_for_targets,
    _task_records,
)


scene = bpy.context.scene
targets, _excludes = _task_records(scene)
source, _snapshot = _source_for_targets(scene, targets)

before = source_snapshot(source)
scene["smrn_rotational_checkpoint_path"] = ""
checkpoint = _checkpoint(scene, source)
after = source_snapshot(source)
print("SMRN_ROTATIONAL_BUGFIX_CHECKPOINT=" + json.dumps({
    "checkpoint": checkpoint,
    "exists": Path(checkpoint).exists(),
    "source": source.name,
    "source_unchanged": before["fingerprint"] == after["fingerprint"],
    "source_visible": source.visible_get(),
    "topology": [len(source.data.vertices), len(source.data.edges), len(source.data.polygons)],
}, ensure_ascii=False, separators=(",", ":")))
