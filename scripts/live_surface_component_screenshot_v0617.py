"""Capture the accepted local flatten candidate in the current Blender view."""

from pathlib import Path

import bpy


path = Path(
    r"C:\codex_auto\semantic-mesh-restorer-next\artifacts"
    r"\maus_flatten_component_safety_v0617_live.png"
)
path.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.screen.screenshot(filepath=str(path))
print(f"SMRN_UI_SCREENSHOT={path}")
