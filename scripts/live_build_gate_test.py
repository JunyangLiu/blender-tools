"""Build the live rotational candidate and audit non-destructive QA gates."""

import json
import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.rotational_blender import (
    CANDIDATE_PREFIX,
    _source_for_targets,
    _task_records,
)

scene = bpy.context.scene
targets, excludes = _task_records(scene)
source, _snapshot = _source_for_targets(scene, targets)
before = source_snapshot(source)
old_name = str(scene.get("smrn_rotational_candidate_name", ""))
candidate_names_before = sorted(
    obj.name for obj in bpy.data.objects if obj.name.startswith(CANDIDATE_PREFIX)
)
result = sorted(bpy.ops.smrn.build_rotational_candidate())
after = source_snapshot(source)
candidate_name = str(scene.get("smrn_rotational_candidate_name", ""))
candidate = bpy.data.objects.get(candidate_name)
candidate_names_after = sorted(
    obj.name for obj in bpy.data.objects if obj.name.startswith(CANDIDATE_PREFIX)
)
report = json.loads(str(scene.get("smrn_rotational_last_report_json", "{}")))
print("SMRN_BUILD_GATE=" + json.dumps({
    "operator_result": result,
    "source": source.name,
    "source_topology": [before["vertex_count"], len(source.data.edges), before["polygon_count"]],
    "source_unchanged": before["fingerprint"] == after["fingerprint"],
    "source_visible": source.visible_get(),
    "targets": len(targets),
    "excludes": len(excludes),
    "old_candidate": old_name,
    "candidate_name": candidate_name,
    "candidate_exists": candidate is not None,
    "candidate_visible": candidate.visible_get() if candidate else None,
    "candidate_names_before": candidate_names_before,
    "candidate_names_after": candidate_names_after,
    "exactly_one_candidate": len(candidate_names_after) == 1,
    "fit": report.get("fit"),
    "domain": report.get("domain"),
    "coverage_qa": report.get("coverage_qa"),
    "exclude_qa": report.get("exclude_qa"),
    "topology_qa": report.get("topology_qa"),
    "checkpoint": report.get("checkpoint"),
    "summary": scene.smrn_rotational_summary,
}, ensure_ascii=False, separators=(",", ":")))
