"""Capture the current Blender window after the eraser UI hot reload."""

import json
from pathlib import Path

import bpy


output = Path(r"C:\codex_auto\semantic-mesh-restorer-next\artifacts\marker_eraser_v0628.png")
output.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.screen.screenshot(filepath=str(output))
print("SMRN_MARK_ERASER_SCREENSHOT=" + json.dumps({
    "path": str(output),
    "exists": output.exists(),
    "bytes": output.stat().st_size if output.exists() else 0,
}, ensure_ascii=False, separators=(",", ":")))
