import bpy

from .constants import EXCLUDE_ROLE, HELPER_COLLECTION_NAME, TARGET_ROLE
from .records import role_counts
from .scene_state import load_marks


class SMRN_PT_marking(bpy.types.Panel):
    bl_label = "语义标记 Next"
    bl_idname = "SMRN_PT_marking"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "语义标记 Next"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        source = scene.get("smrn_source_name", "未设置")
        box = layout.box()
        box.label(text=f"当前语义源：{source}", icon="MESH_DATA")
        box.operator("smrn.setup_source", icon="EYEDROPPER")
        box.operator("smrn.stop_marking", icon="RESTRICT_SELECT_OFF")

        marks_box = layout.box()
        marks_box.label(text="非破坏式表面标记", icon="GREASEPENCIL")
        row = marks_box.row(align=True)
        target = row.operator("smrn.mark_surface", text="绿色：需要处理", icon="BRUSH_DATA")
        target.mark_value = 1
        exclude = row.operator("smrn.mark_surface", text="红色：不要处理", icon="BRUSH_DATA")
        exclude.mark_value = -1
        marks_box.prop(scene, "smrn_marker_size", text="标记显示大小", slider=True)
        marks_box.prop(scene, "smrn_magnetic_radius_px", text="磁吸半径", slider=True)
        row = marks_box.row(align=True)
        row.operator("smrn.undo_mark", icon="LOOP_BACK")
        row.operator("smrn.clear_marks", icon="X")
        helpers = bpy.data.collections.get(HELPER_COLLECTION_NAME)
        marks_box.operator(
            "smrn.toggle_helpers",
            text="显示标记辅助" if helpers is not None and helpers.hide_viewport else "隐藏标记辅助",
            icon="HIDE_OFF" if helpers is not None and helpers.hide_viewport else "HIDE_ON",
        )
        counts = role_counts(load_marks(scene))
        marks_box.label(text=f"目标 {counts[TARGET_ROLE]} ｜ 排除 {counts[EXCLUDE_ROLE]}", icon="INFO")
        layout.label(text=scene.smrn_status, icon="INFO")


CLASSES = (SMRN_PT_marking,)

