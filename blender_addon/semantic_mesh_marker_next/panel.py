import bpy

from .constants import EXCLUDE_ROLE, HELPER_COLLECTION_NAME, MODAL_TOKEN_KEY, TARGET_ROLE
from .scene_state import marks_summary


def _candidate_exists(scene, key, prefix):
    name = str(scene.get(key, ""))
    return bool(name.startswith(prefix) and bpy.data.objects.get(name) is not None)


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
        box.operator(
            "smrn.setup_source",
            text="更换语义源" if source != "未设置" else "设置语义源",
            icon="EYEDROPPER",
        )
        if scene.get(MODAL_TOKEN_KEY, ""):
            box.operator("smrn.stop_marking", text="结束标记", icon="RESTRICT_SELECT_OFF")

        marks_box = layout.box()
        marks_box.label(text="1. 标记表面", icon="GREASEPENCIL")
        row = marks_box.row(align=True)
        target = row.operator("smrn.mark_surface", text="绿色：要处理", icon="BRUSH_DATA")
        target.mark_value = 1
        exclude = row.operator("smrn.mark_surface", text="红色：要保留", icon="BRUSH_DATA")
        exclude.mark_value = -1
        row = marks_box.row(align=True)
        row.operator("smrn.undo_mark", text="撤销", icon="LOOP_BACK")
        row.operator("smrn.clear_marks", text="清空", icon="X")
        helpers = bpy.data.collections.get(HELPER_COLLECTION_NAME)
        counts = marks_summary(scene)["role_counts"]
        row = marks_box.row(align=True)
        row.label(text=f"绿色 {counts[TARGET_ROLE]}  ·  红色 {counts[EXCLUDE_ROLE]}")
        row.operator(
            "smrn.toggle_helpers",
            text="显示" if helpers is not None and helpers.hide_viewport else "隐藏",
            icon="HIDE_OFF" if helpers is not None and helpers.hide_viewport else "HIDE_ON",
        )

        rotational = layout.box()
        rotational.label(text="2. 圆柱 / 圆锥圆润", icon="MOD_SCREW")
        rotational.label(text="绿色标记需要圆润的表面")
        rotational.operator(
            "smrn.build_rotational_candidate",
            text="一键生成圆润候选",
            icon="MESH_CYLINDER",
        )
        if _candidate_exists(scene, "smrn_rotational_candidate_name", "SMRN_ROTATIONAL_CANDIDATE_"):
            rotational.operator("smrn.remove_rotational_candidate", text="移除当前圆润候选", icon="TRASH")

        handle = layout.box()
        handle.label(text="3. 扶手 / 把手还原", icon="CURVE_BEZCURVE")
        handle.label(text="绿色标管体，红色标两端安装面")
        handle.operator(
            "smrn.build_handle_candidate",
            text="一键生成扶手候选",
            icon="MESH_TORUS",
        )
        if _candidate_exists(scene, "smrn_handle_candidate_name", "SMRN_HANDLE_CANDIDATE_"):
            handle.operator("smrn.remove_handle_candidate", text="移除当前扶手候选", icon="TRASH")

        advanced = layout.box()
        row = advanced.row()
        row.prop(
            scene,
            "smrn_show_advanced",
            text="高级设置",
            icon="DISCLOSURE_TRI_DOWN" if scene.smrn_show_advanced else "DISCLOSURE_TRI_RIGHT",
            emboss=False,
        )
        if scene.smrn_show_advanced:
            marking = advanced.column(align=True)
            marking.label(text="标记工具")
            marking.prop(scene, "smrn_marker_size", text="标记显示大小", slider=True)
            marking.prop(scene, "smrn_magnetic_radius_px", text="磁吸半径", slider=True)

            rotational_settings = advanced.column(align=True)
            rotational_settings.label(text="圆润拟合")
            rotational_settings.prop(scene, "smrn_rotational_segments", text="圆周细分")
            rotational_settings.prop(scene, "smrn_rotational_thickness", text="壳体厚度（0=自动）")
            rotational_settings.prop(scene, "smrn_rotational_clearance", text="额外外扩")
            rotational_settings.operator("smrn.analyze_rotational", text="只分析圆润证据", icon="VIEWZOOM")
            rotational_settings.label(text=scene.smrn_rotational_summary, icon="INFO")

            handle_settings = advanced.column(align=True)
            handle_settings.label(text="扶手拟合")
            handle_settings.prop(scene, "smrn_handle_path_segments", text="路径细分")
            handle_settings.prop(scene, "smrn_handle_section_segments", text="截面细分")
            handle_settings.prop(scene, "smrn_handle_min_diameter", text="最小直径（0=源尺寸）")
            handle_settings.prop(scene, "smrn_handle_clearance", text="额外外扩")
            handle_settings.operator("smrn.analyze_handle", text="只分析扶手证据", icon="VIEWZOOM")
            handle_settings.label(text=scene.smrn_handle_summary, icon="INFO")

        if scene.smrn_status:
            status = layout.box()
            status.label(text="状态", icon="INFO")
            status.label(text=scene.smrn_status)


CLASSES = (SMRN_PT_marking,)
