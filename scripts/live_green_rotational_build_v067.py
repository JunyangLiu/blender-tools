"""Exercise the v0.6.7 green-mark rotational path without replacing the source."""

import importlib
import json

import bpy


PACKAGE = "semantic_mesh_marker_next"
scene = bpy.context.scene
anchors = importlib.import_module(PACKAGE + ".anchors")
storage = importlib.import_module(PACKAGE + ".storage")

source_name = str(scene.get("smrn_source_name", ""))
source = bpy.data.objects.get(source_name)
if source is None:
    raise RuntimeError("Configured semantic source is missing")
before_fingerprint = anchors.source_snapshot(source)["fingerprint"]
before_counts = storage.document_summary(scene)["role_counts"]
if int(before_counts.get("target", 0)) <= 0:
    raise RuntimeError("No green semantic marks are available")

result = bpy.ops.smrn.build_rotational_candidate()
candidate_name = str(scene.get("smrn_rotational_candidate_name", ""))
candidate = bpy.data.objects.get(candidate_name)
after_fingerprint = anchors.source_snapshot(source)["fingerprint"]
after_counts = storage.document_summary(scene)["role_counts"]

report = {
    "operator_result": sorted(result),
    "mode_after": bpy.context.mode,
    "candidate": candidate_name,
    "candidate_exists": candidate is not None,
    "candidate_input_mode": (
        str(candidate.get("smrn_input_mode", "")) if candidate is not None else ""
    ),
    "source_fingerprint_unchanged": before_fingerprint == after_fingerprint,
    "marks_unchanged": before_counts == after_counts,
    "role_counts": after_counts,
    "status": scene.smrn_status,
}
if result != {"FINISHED"}:
    raise RuntimeError("Green-mark build did not finish: " + repr(report))
if candidate is None:
    raise RuntimeError("Build finished without a rotational candidate: " + repr(report))
if candidate.get("smrn_input_mode", "") == "selected_faces":
    raise RuntimeError("Green marks were shadowed by native edit selection: " + repr(report))
if before_fingerprint != after_fingerprint or before_counts != after_counts:
    raise RuntimeError("Build modified source or marks: " + repr(report))

print("SMRN_GREEN_ROTATIONAL_BUILD_V067=" + json.dumps(
    report, ensure_ascii=False, separators=(",", ":")
))
