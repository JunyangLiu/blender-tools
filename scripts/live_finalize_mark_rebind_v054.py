"""Leave the repaired mark state ready for the next bounded flatten attempt."""

import json

import bpy

from semantic_mesh_marker_next.scene_state import keep_model_visible
from semantic_mesh_marker_next.storage import load_all_marks
from semantic_mesh_marker_next.surface_rebuild_blender import remove_last_candidate


scene = bpy.context.scene
remove_last_candidate(scene)
source = bpy.data.objects.get(str(scene.get("smrn_active_source_name", "")))
if source is None:
    source = bpy.data.objects.get("turret_v96_with_rear_drum_L_selectable")
if source is None:
    raise RuntimeError("当前语义源不存在")

scene.smrn_surface_height_mode = "RED_REFERENCE"
scene.smrn_surface_normal_mode = "AUTO"
records = load_all_marks(scene)
target = [record for record in records if record.role == "target"]
exclude = [record for record in records if record.role == "exclude"]
foreign = [
    record for record in target + exclude
    if record.hit_object_name != source.name
]
if foreign:
    raise RuntimeError(f"仍有 {len(foreign)} 个标记未绑定到当前语义源")

scene.smrn_status = "标记归属已修复：红色作为最低高度参考，法向由绿色局部区域拟合；源网格未修改"
scene.smrn_surface_summary = (
    f"绿色 {len(target)} · 红色 {len(exclude)}；全部属于当前语义源；旧候选已移除"
)
keep_model_visible(scene, (source,))
bpy.ops.wm.save_mainfile()

accepted = [
    obj.name for obj in bpy.data.objects
    if bool(obj.get("smrn_accepted", False)) and not obj.hide_get()
]
print("SMRN_MARK_REBIND_FINAL=" + json.dumps({
    "blend": bpy.data.filepath,
    "source": source.name,
    "source_visible": not source.hide_get() and not source.hide_viewport,
    "green": len(target),
    "red": len(exclude),
    "foreign_marks": len(foreign),
    "height_mode": scene.smrn_surface_height_mode,
    "normal_mode": scene.smrn_surface_normal_mode,
    "accepted_visible": accepted,
    "candidate": str(scene.get("smrn_surface_candidate_name", "")),
}, ensure_ascii=False, separators=(",", ":")))
