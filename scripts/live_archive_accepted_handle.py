"""Freeze the currently approved handle without replacing the vehicle source."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct

import bpy


scene = bpy.context.scene
candidate_name = str(scene.get("smrn_handle_candidate_name", ""))
candidate = bpy.data.objects.get(candidate_name)
if candidate is None or candidate.type != "MESH":
    raise RuntimeError("No live handle candidate is available to archive")

report = json.loads(str(candidate.get("smrn_handle_report_json", "{}") or "{}"))
coverage = report.get("coverage_qa", {})
containment = coverage.get("mesh_containment", {})
topology = report.get("topology_qa", {})
if not (
    report.get("status") == "candidate_ready"
    and coverage.get("passed") is True
    and containment.get("outside") == 0
    and topology.get("passed") is True
    and report.get("source_unchanged") is True
    and report.get("evidence_sources_unchanged") is True
):
    raise RuntimeError("The live candidate does not satisfy the accepted-handle gate")

digest = hashlib.sha256()
for vertex in candidate.data.vertices:
    digest.update(struct.pack("<3d", *candidate.matrix_world @ vertex.co))
for polygon in candidate.data.polygons:
    indices = tuple(int(index) for index in polygon.vertices)
    digest.update(struct.pack("<I", len(indices)))
    digest.update(struct.pack(f"<{len(indices)}I", *indices))
geometry_hash = digest.hexdigest()

model_root = bpy.data.collections.get("SMR_01_当前模型_始终可见")
if model_root is None:
    raise RuntimeError("Trusted always-visible model collection is missing")
accepted_collection = bpy.data.collections.get("SMRN_已确认修复_始终可见")
if accepted_collection is None:
    accepted_collection = bpy.data.collections.new("SMRN_已确认修复_始终可见")
    model_root.children.link(accepted_collection)
elif accepted_collection.name not in {item.name for item in model_root.children}:
    model_root.children.link(accepted_collection)

for collection in tuple(candidate.users_collection):
    collection.objects.unlink(candidate)
accepted_collection.objects.link(candidate)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
candidate.name = f"SMRN_HANDLE_ACCEPTED_MAUS_{stamp}"
candidate.data.name = f"{candidate.name}_MESH"
candidate["smrn_accepted"] = True
candidate["smrn_locked_baseline"] = True
candidate["smrn_accepted_at"] = stamp
candidate["smrn_accepted_commit"] = "7a792c6"
candidate["smrn_geometry_sha256"] = geometry_hash
candidate["smrn_candidate_only"] = False
candidate.hide_set(False)
candidate.hide_viewport = False
candidate.hide_render = False
scene["smrn_handle_candidate_name"] = ""

archive_dir = Path(bpy.data.filepath).parent / "archives"
archive_dir.mkdir(parents=True, exist_ok=True)
archive_blend = archive_dir / "maus_handle_accepted_20260820.blend"
manifest = {
    "schema": "smrn.accepted-handle.v1",
    "accepted_at": stamp,
    "object": candidate.name,
    "collection": accepted_collection.name,
    "geometry_sha256": geometry_hash,
    "source": report.get("source"),
    "evidence_sources": report.get("evidence_sources"),
    "fit": report.get("fit"),
    "coverage_qa": coverage,
    "topology_qa": topology,
    "endpoint_qa": report.get("endpoint_qa"),
    "endpoint_penetrations": report.get("endpoint_penetrations"),
    "endpoint_coverage_extension": report.get("endpoint_coverage_extension"),
    "source_unchanged": report.get("source_unchanged"),
    "evidence_sources_unchanged": report.get("evidence_sources_unchanged"),
    "accepted_commit": "7a792c6",
    "archive_blend": str(archive_blend),
}
scene["smrn_accepted_handle_manifest_json"] = json.dumps(
    manifest, ensure_ascii=False, separators=(",", ":")
)
bpy.ops.wm.save_as_mainfile(filepath=str(archive_blend), copy=True)
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
print("SMRN_ACCEPTED_HANDLE=" + json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
