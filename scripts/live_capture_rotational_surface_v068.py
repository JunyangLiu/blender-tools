"""Capture the live original-mesh rotational preview for visual QA."""

import json
from pathlib import Path

import bpy


output = Path(r"C:\codex_auto\semantic-mesh-restorer-next\artifacts\rotational_surface_v068_live.png")
output.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
bpy.ops.screen.screenshot(filepath=str(output))
print("SMRN_ROTATIONAL_SURFACE_CAPTURE=" + json.dumps({
    "path": str(output), "exists": output.exists(),
}, ensure_ascii=False, separators=(",", ":")))
