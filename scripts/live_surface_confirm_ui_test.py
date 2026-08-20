"""Verify confirmation-state cleanup without changing geometry or semantic marks."""

import json

import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.constants import MODAL_TOKEN_KEY
from semantic_mesh_marker_next.operators import _restore_normal_selection
from semantic_mesh_marker_next.storage import document_summary


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
if source is None or source.type != "MESH":
    raise RuntimeError("当前语义源不存在")

before = source_snapshot(source)
marks_before = document_summary(scene)["role_counts"]
scene[MODAL_TOKEN_KEY] = "SMRN_CONFIRM_UI_TEST"
_restore_normal_selection(bpy.context, source)
after = source_snapshot(source)
marks_after = document_summary(scene)["role_counts"]

assert scene.get(MODAL_TOKEN_KEY, "") == ""
assert bpy.context.view_layer.objects.active == source
assert source.select_get()
assert source.mode == "OBJECT"
assert before["fingerprint"] == after["fingerprint"]
assert marks_before == marks_after

print("SMRN_SURFACE_CONFIRM_UI_TEST=" + json.dumps({
    "passed": True,
    "normal_selection_restored": True,
    "source": source.name,
    "source_unchanged": True,
    "target_marks_preserved_for_test": marks_after["target"],
    "exclude_marks_preserved_for_test": marks_after["exclude"],
}, ensure_ascii=False, separators=(",", ":")))
