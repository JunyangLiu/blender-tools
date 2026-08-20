"""Capture the strict green-scope surface preview for compact visual QA."""

import json
from pathlib import Path

import bpy


output = Path(r"C:\codex_auto\semantic_mesh_restorer_maus_turret\qa_surface_strict_green_v058.png")
bpy.ops.screen.screenshot(filepath=str(output))
print("SMRN_STRICT_SURFACE_CAPTURE=" + json.dumps({
    "path": str(output),
    "exists": output.exists(),
}, ensure_ascii=False, separators=(",", ":")))
