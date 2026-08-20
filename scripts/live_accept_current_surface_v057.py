"""Checkpoint and accept the user's current source appearance without replacing geometry."""

import json
from datetime import datetime
from pathlib import Path

import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.storage import document_summary


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
if source is None or source.type != "MESH":
    raise RuntimeError("当前语义源不存在")
before = source_snapshot(source)
marks_before = document_summary(scene)["mark_count"]
if marks_before <= 0:
    raise RuntimeError("当前没有可确认的标记")

current = Path(bpy.data.filepath)
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
checkpoint = current.with_name(current.stem + f"_before_accept_current_{stamp}.blend")
bpy.ops.wm.save_as_mainfile(filepath=str(checkpoint), copy=True)
result = bpy.ops.smrn.accept_current_surface()
after = source_snapshot(source)
marks_after = document_summary(scene)["mark_count"]

assert result == {"FINISHED"}
assert before["fingerprint"] == after["fingerprint"]
assert marks_after == 0
print("SMRN_ACCEPT_CURRENT=" + json.dumps({
    "passed": True,
    "operator_result": sorted(result),
    "checkpoint": str(checkpoint),
    "source_unchanged": True,
    "marks_cleared": marks_before,
    "normal_selection_restored": source.select_get() and source.mode == "OBJECT",
}, ensure_ascii=False, separators=(",", ":")))
