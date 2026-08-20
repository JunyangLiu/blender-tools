"""Read-only audit of the current local-surface candidate and marked scope."""

import json

import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.constants import EXCLUDE_ROLE, TARGET_ROLE
from semantic_mesh_marker_next.storage import document_summary, load_all_marks


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
candidate_name = str(scene.get("smrn_surface_candidate_name", ""))
working_name = str(scene.get("smrn_surface_working_name", ""))
candidate = bpy.data.objects.get(candidate_name)
working = bpy.data.objects.get(working_name)
marks = load_all_marks(scene)
report = {
    "blend": bpy.data.filepath,
    "source": source.name if source else None,
    "source_snapshot": source_snapshot(source) if source and source.type == "MESH" else None,
    "mark_count": document_summary(scene)["mark_count"],
    "target_marks": sum(record.role == TARGET_ROLE for record in marks),
    "exclude_marks": sum(record.role == EXCLUDE_ROLE for record in marks),
    "candidate": candidate.name if candidate else None,
    "candidate_vertices": len(candidate.data.vertices) if candidate and candidate.type == "MESH" else 0,
    "candidate_faces": len(candidate.data.polygons) if candidate and candidate.type == "MESH" else 0,
    "working": working.name if working else None,
    "working_vertices": len(working.data.vertices) if working and working.type == "MESH" else 0,
    "working_faces": len(working.data.polygons) if working and working.type == "MESH" else 0,
    "status": scene.smrn_status,
    "summary": scene.smrn_surface_summary,
}
print("SMRN_SURFACE_SCOPE_AUDIT=" + json.dumps(report, ensure_ascii=False, separators=(",", ":")))
