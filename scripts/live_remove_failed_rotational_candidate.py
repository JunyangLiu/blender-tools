"""Remove only the current unaccepted rotational shell from the assigned Blender scene."""

import json

import bpy

from semantic_mesh_marker_next.rotational_blender import remove_last_candidate
from semantic_mesh_marker_next.storage import load_all_marks


scene = bpy.context.scene
candidate_name = str(scene.get("smrn_rotational_candidate_name", ""))
candidate = bpy.data.objects.get(candidate_name)
was_unaccepted = bool(
    candidate is not None
    and candidate_name.startswith("SMRN_ROTATIONAL_CANDIDATE_")
    and not bool(candidate.get("smrn_accepted", False))
)
removed = remove_last_candidate(scene) if was_unaccepted else False
marks = load_all_marks(scene)
result = {
    "candidate_name": candidate_name,
    "removed": bool(removed),
    "marks_preserved": len(marks),
    "target_marks": sum(record.role == "target" for record in marks),
    "exclude_marks": sum(record.role == "exclude" for record in marks),
    "source_name": str(scene.get("smrn_source_name", "")),
}
print("SMRN_RESULT=" + json.dumps(result, ensure_ascii=False))
