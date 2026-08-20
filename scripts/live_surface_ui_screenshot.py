"""Capture the current Blender window after live add-on reload."""

from pathlib import Path

import bpy


path = Path(r"C:\codex_auto\semantic-mesh-restorer-next\artifacts\maus_surface_rebuild_v053_live.png")
path.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.screen.screenshot(filepath=str(path))
print(f"SMRN_UI_SCREENSHOT={path}")
