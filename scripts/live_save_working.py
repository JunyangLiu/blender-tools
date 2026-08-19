"""Save the verified live candidate in the current working blend."""

import json
from pathlib import Path

import bpy


scene = bpy.context.scene
candidate = None
candidate_kind = None
for key, kind in (
    ("smrn_handle_candidate_name", "handle"),
    ("smrn_rotational_candidate_name", "rotational"),
):
    value = bpy.data.objects.get(str(scene.get(key, "")))
    if value is not None:
        candidate, candidate_kind = value, kind
        break
if candidate is None:
    raise RuntimeError("Verified SMRN candidate is missing")
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
print("SMRN_WORKING_SAVED=" + json.dumps({
    "blend": bpy.data.filepath,
    "exists": Path(bpy.data.filepath).exists(),
    "candidate": candidate.name,
    "candidate_kind": candidate_kind,
    "candidate_visible": candidate.visible_get(),
}, ensure_ascii=False, separators=(",", ":")))
