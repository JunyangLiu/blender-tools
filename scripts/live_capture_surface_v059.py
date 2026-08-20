"""Capture the v0.5.9 strict green-scope surface preview for visual QA."""

import json
from pathlib import Path

import bpy


output = Path(r"C:\codex_auto\semantic_mesh_restorer_maus_turret\qa_surface_strict_green_v059.png")
bpy.ops.screen.screenshot(filepath=str(output))
print("SMRN_SURFACE_CAPTURE_V059=" + json.dumps({
    "path": str(output),
    "exists": output.exists(),
}, ensure_ascii=False, separators=(",", ":")))
