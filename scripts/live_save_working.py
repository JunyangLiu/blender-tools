"""Save the verified live candidate in the current working blend."""

import json
from pathlib import Path

import bpy


scene = bpy.context.scene
candidate_name = str(scene.get("smrn_rotational_candidate_name", ""))
candidate = bpy.data.objects.get(candidate_name)
if candidate is None:
    raise RuntimeError("Verified rotational candidate is missing")
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
print("SMRN_WORKING_SAVED=" + json.dumps({
    "blend": bpy.data.filepath,
    "exists": Path(bpy.data.filepath).exists(),
    "candidate": candidate.name,
    "candidate_visible": candidate.visible_get(),
}, ensure_ascii=False, separators=(",", ":")))
