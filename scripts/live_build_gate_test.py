"""Exercise the live build gate and verify that rejection leaves the source unchanged."""

import json
import bpy


scene = bpy.context.scene
source = bpy.data.objects.get("turret_v96_with_rear_drum_L_selectable")
before = [len(source.data.vertices), len(source.data.edges), len(source.data.polygons)]
result = sorted(bpy.ops.smrn.build_rotational_candidate())
after = [len(source.data.vertices), len(source.data.edges), len(source.data.polygons)]
candidate_name = str(scene.get("smrn_rotational_candidate_name", ""))
print("SMRN_BUILD_GATE=" + json.dumps({
    "operator_result": result,
    "source_before": before,
    "source_after": after,
    "source_unchanged": before == after,
    "source_visible": source.visible_get(),
    "candidate_name": candidate_name,
    "candidate_exists": bool(candidate_name and bpy.data.objects.get(candidate_name)),
    "summary": scene.smrn_rotational_summary,
}, ensure_ascii=False, separators=(",", ":")))

