"""Read-only live inspection for the legacy independent rotational candidate."""

import json

import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.constants import EXCLUDE_ROLE, SOURCE_NAME_KEY, TARGET_ROLE
from semantic_mesh_marker_next.storage import load_all_marks


scene = bpy.context.scene
records = load_all_marks(scene)
source_name = str(scene.get(SOURCE_NAME_KEY, ""))
source = bpy.data.objects.get(source_name)
candidate_name = str(scene.get("smrn_rotational_candidate_name", ""))
candidate = bpy.data.objects.get(candidate_name)

payload = {
    "blend": bpy.data.filepath,
    "source_name": source_name,
    "source_exists": bool(source and source.type == "MESH"),
    "source_snapshot": source_snapshot(source) if source and source.type == "MESH" else None,
    "target_marks": sum(item.role == TARGET_ROLE for item in records),
    "exclude_marks": sum(item.role == EXCLUDE_ROLE for item in records),
    "mark_sources": sorted({item.source_object_name for item in records}),
    "legacy_candidate_name": candidate_name,
    "legacy_candidate_exists": candidate is not None,
    "legacy_candidate_vertices": len(candidate.data.vertices) if candidate and candidate.type == "MESH" else 0,
    "legacy_candidate_faces": len(candidate.data.polygons) if candidate and candidate.type == "MESH" else 0,
}
print("SMRN_LEGACY_INSPECT=" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
