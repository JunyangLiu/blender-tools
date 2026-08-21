"""Read the current legacy candidate QA report without changing the scene."""

import json

import bpy


scene = bpy.context.scene
name = str(scene.get("smrn_rotational_candidate_name", ""))
obj = bpy.data.objects.get(name)
if obj is None:
    raise RuntimeError("No legacy rotational candidate")
report = json.loads(str(obj.get("smrn_rotational_report_json", "{}")))
print("SMRN_LEGACY_REPORT=" + json.dumps({
    "candidate": name,
    "domain": report.get("domain"),
    "coverage_qa": report.get("coverage_qa"),
    "topology_qa": report.get("topology_qa"),
    "source_unchanged": report.get("source_unchanged"),
}, ensure_ascii=False, sort_keys=True))
