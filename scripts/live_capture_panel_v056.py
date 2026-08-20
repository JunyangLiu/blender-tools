"""Capture the current Blender UI for the v0.5.6 confirmation-control QA."""

import json
from pathlib import Path

import bpy


output = Path(r"C:\codex_auto\semantic_mesh_restorer_maus_turret\qa_surface_confirm_v056.png")
bpy.ops.screen.screenshot(filepath=str(output))
print("SMRN_PANEL_CAPTURE=" + json.dumps({
    "path": str(output),
    "exists": output.exists(),
}, ensure_ascii=False, separators=(",", ":")))
