import json
from pathlib import Path

import bpy

from semantic_mesh_marker_next.scene_state import keep_model_visible


output = Path(r"C:\codex_auto\semantic-mesh-restorer-next\artifacts\maus_overlap_fixed.png")
output.parent.mkdir(parents=True, exist_ok=True)
# Exercise the exact call that previously resurrected the old full turret.
keep_model_visible(bpy.context.scene)
bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
bpy.ops.screen.screenshot(filepath=str(output))

source = bpy.data.objects.get(str(bpy.context.scene.get("smrn_source_name", "")))
old = bpy.data.objects.get("turret")
accepted = bpy.data.objects.get("SMRN_HANDLE_ACCEPTED_MAUS_20260819T184509Z")
result = {
    "screenshot": str(output),
    "source_visible": bool(source and source.visible_get(view_layer=bpy.context.view_layer)),
    "superseded_turret_hidden": bool(old and not old.visible_get(view_layer=bpy.context.view_layer)),
    "accepted_handle_visible": bool(accepted and accepted.visible_get(view_layer=bpy.context.view_layer)),
}
print("SMRN_OVERLAP_VISUAL_QA=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
