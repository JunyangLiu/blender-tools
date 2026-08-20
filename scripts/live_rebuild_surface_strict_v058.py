"""Replace only the unaccepted surface preview with a strict green-scope preview."""

import json
from datetime import datetime
from pathlib import Path

import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.constants import EXCLUDE_ROLE, TARGET_ROLE
from semantic_mesh_marker_next.storage import load_all_marks
from semantic_mesh_marker_next.surface_rebuild_blender import (
    build_scene_candidate,
    remove_last_candidate,
)


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
if source is None or source.type != "MESH":
    raise RuntimeError("当前语义源不存在")

before = source_snapshot(source)
marks_before = load_all_marks(scene)
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
blend_path = Path(bpy.data.filepath)
checkpoint = blend_path.with_name(blend_path.stem + f"_before_strict_green_flatten_{stamp}.blend")
bpy.ops.wm.save_as_mainfile(filepath=str(checkpoint), copy=True)

removed_bad_candidate = remove_last_candidate(scene)
result = {
    "blend": bpy.data.filepath,
    "checkpoint": str(checkpoint),
    "removed_bad_candidate": removed_bad_candidate,
    "source_before": before,
    "marks_before": len(marks_before),
    "target_marks": sum(record.role == TARGET_ROLE for record in marks_before),
    "exclude_marks": sum(record.role == EXCLUDE_ROLE for record in marks_before),
}

try:
    preview, report = build_scene_candidate(scene, "flatten")
    topology = report["topology_qa"]
    strict_ok = (
        topology.get("strict_marked_scope") is True
        and topology.get("unmarked_vertices_moved") == 0
        and topology.get("transition_faces_checked") == 0
        and topology.get("transition_ring_count") == 0
        and topology.get("preview_affected_faces") == topology.get("region_faces_after")
    )
    if not strict_ok:
        remove_last_candidate(scene)
        raise RuntimeError("严格绿色范围核验未通过，已撤销新候选")
    result.update({
        "status": "strict_candidate_ready",
        "candidate": preview.name,
        "candidate_vertices": len(preview.data.vertices),
        "candidate_faces": len(preview.data.polygons),
        "source_unchanged_reported": report.get("source_unchanged"),
        "semantic_region": report.get("semantic_region"),
        "topology_qa": topology,
        "coverage_qa": report.get("coverage_qa"),
    })
except Exception as error:
    result.update({"status": "rejected", "error": str(error)})

after = source_snapshot(source)
marks_after = load_all_marks(scene)
result["source_after"] = after
result["source_fingerprint_unchanged"] = before["fingerprint"] == after["fingerprint"]
result["marks_after"] = len(marks_after)
result["marks_unchanged"] = len(marks_before) == len(marks_after)
bpy.ops.wm.save_mainfile()

print("SMRN_STRICT_SURFACE_REBUILD=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
