"""Print the latest handle report from the isolated Maus Blender scene."""

import json

import bpy


raw = str(bpy.context.scene.get("smrn_handle_last_report_json", "{}"))
report = json.loads(raw)
coverage = report.get("coverage_qa", {})
print("SMRN_HANDLE_LAST_REPORT=" + json.dumps({
    "status": report.get("status"),
    "reason": report.get("reason"),
    "topology": report.get("topology_qa"),
    "source_unchanged": report.get("source_unchanged"),
    "evidence_sources_unchanged": report.get("evidence_sources_unchanged"),
    "endpoint_penetrations": report.get("endpoint_penetrations"),
    "endpoint_coverage_extension": report.get("endpoint_coverage_extension"),
    "coverage": coverage,
}, ensure_ascii=False, separators=(",", ":")))
