"""Capture the Blender UI after accepting the current surface in v0.5.7."""

import json
from pathlib import Path

import bpy


output = Path(r"C:\codex_auto\semantic_mesh_restorer_maus_turret\qa_surface_accept_current_v057.png")
bpy.ops.screen.screenshot(filepath=str(output))
print("SMRN_PANEL_CAPTURE=" + json.dumps({
    "path": str(output),
    "exists": output.exists(),
}, ensure_ascii=False, separators=(",", ":")))
