"""Regenerate the current rotational candidate with inward structural backing."""

import importlib
import json
from pathlib import Path

import bpy


PACKAGE = "semantic_mesh_marker_next"
OUTPUT = Path(r"C:\codex_auto\semantic-mesh-restorer-next\artifacts\rotational_inward_backing_v0613.png")

scene = bpy.context.scene
anchors = importlib.import_module(PACKAGE + ".anchors")
storage = importlib.import_module(PACKAGE + ".storage")
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
if source is None:
    raise RuntimeError("Current semantic source is missing")

before_fingerprint = anchors.source_snapshot(source)["fingerprint"]
before_marks = storage.document_summary(scene)["role_counts"]
old_name = str(scene.get("smrn_rotational_candidate_name", ""))
old_obj = bpy.data.objects.get(old_name)
old_report = json.loads(str(old_obj.get("smrn_rotational_report_json", "{}"))) if old_obj else {}

# Zero means source-scaled automatic thickness.  The visible envelope remains
# fixed; only the material-side backing moves toward the recovered axis.
scene.smrn_rotational_thickness = 0.0
result = bpy.ops.smrn.build_rotational_candidate()
if "FINISHED" not in result:
    raise RuntimeError("Rotational candidate rebuild failed: " + repr(result))

name = str(scene.get("smrn_rotational_candidate_name", ""))
candidate = bpy.data.objects.get(name)
if candidate is None:
    raise RuntimeError("Rebuild finished without a current candidate")
report = json.loads(str(candidate.get("smrn_rotational_report_json", "{}")))
domain = report.get("domain", {})
after_fingerprint = anchors.source_snapshot(source)["fingerprint"]
after_marks = storage.document_summary(scene)["role_counts"]
if after_fingerprint != before_fingerprint or after_marks != before_marks:
    raise RuntimeError("Rebuild changed source or semantic marks")
if domain.get("backing_direction") != "toward_axis":
    raise RuntimeError("Outer ring backing did not move toward the recovered axis")
if not domain.get("visible_surface_preserved"):
    raise RuntimeError("Visible fitted surface was not declared preserved")

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.screen.screenshot(filepath=str(OUTPUT))
print("SMRN_INWARD_BACKING_V0613=" + json.dumps({
    "operator": sorted(result),
    "candidate": name,
    "old_thickness": old_report.get("domain", {}).get("thickness"),
    "new_thickness": domain.get("thickness"),
    "thickness_mode": domain.get("thickness_mode"),
    "backing_direction": domain.get("backing_direction"),
    "visible_surface_preserved": domain.get("visible_surface_preserved"),
    "coverage_qa": report.get("coverage_qa"),
    "topology_qa": report.get("topology_qa"),
    "source_fingerprint": after_fingerprint,
    "role_counts": after_marks,
    "screenshot": str(OUTPUT),
}, ensure_ascii=False, separators=(",", ":")))
