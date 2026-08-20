"""Save the current Blender file after a geometry-preserving UI-only update."""

import json
from pathlib import Path

import bpy


if not bpy.data.filepath:
    raise RuntimeError("当前 Blender 工程尚未保存")
bpy.ops.wm.save_mainfile()
print("SMRN_UI_STATE_SAVED=" + json.dumps({
    "blend": bpy.data.filepath,
    "exists": Path(bpy.data.filepath).exists(),
}, ensure_ascii=False, separators=(",", ":")))
