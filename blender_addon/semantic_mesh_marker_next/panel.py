import bpy

from .constants import EXCLUDE_ROLE, HELPER_COLLECTION_NAME, MODAL_TOKEN_KEY, TARGET_ROLE
from .scene_state import marks_summary


def _candidate_exists(scene, key, prefix):
    name = str(scene.get(key, ""))
    return bool(name.startswith(prefix) and bpy.data.objects.get(name) is not None)


def _candidate_input_mode(scene, key):
    candidate = bpy.data.objects.get(str(scene.get(key, "")))
    return str(candidate.get("smrn_input_mode", "")) if candidate is not None else ""


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
        target = row.operator("smrn.mark_surface", text="绿色刷选：要处理", icon="BRUSH_DATA")
        target.mark_value = 1
        exclude = row.operator("smrn.mark_surface", text="红色刷选：要保留", icon="BRUSH_DATA")
        exclude.mark_value = -1
        row = marks_box.row(align=True)
        erase_target = row.operator("smrn.mark_surface", text="擦除绿色", icon="X")
        erase_target.mark_value = 1
        erase_target.erase = True
        erase_exclude = row.operator("smrn.mark_surface", text="擦除红色", icon="X")
        erase_exclude.mark_value = -1
        erase_exclude.erase = True
        row = marks_box.row(align=True)
        row.operator("smrn.undo_mark", text="撤销", icon="LOOP_BACK")
        row.operator("smrn.clear_marks", text="清空", icon="X")
        helpers = bpy.data.collections.get(HELPER_COLLECTION_NAME)
        counts = marks_summary(scene)["role_counts"]
        has_any_surface_candidate = _candidate_exists(
            scene, "smrn_surface_candidate_name", "SMRN_SURFACE_CANDIDATE_"
        )
        surface_candidate_mode = str(scene.get("smrn_surface_candidate_mode", ""))
        row = marks_box.row(align=True)
        row.label(text=f"绿色 {counts[TARGET_ROLE]}  ·  红色 {counts[EXCLUDE_ROLE]}")
        row.operator(
            "smrn.toggle_helpers",
            text="显示" if helpers is not None and helpers.hide_viewport else "隐藏",
            icon="HIDE_OFF" if helpers is not None and helpers.hide_viewport else "HIDE_ON",
        )

        rotational = layout.box()
        rotational.label(text="2. 圆柱 / 圆锥圆润", icon="MOD_SCREW")
        rotational.label(text="物体模式绿色刷选；重建原网面，不生成罩体")
        rebuild_rotational = rotational.operator(
            "smrn.build_surface_candidate",
            text="重建绿色圆润原网面",
            icon="MESH_CYLINDER",
        )
        rebuild_rotational.mode = "rotational"
        if has_any_surface_candidate and surface_candidate_mode == "rotational":
            rotational.operator(
                "smrn.confirm_surface_replacement",
                text="确认圆润并替换标记网面",
                icon="CHECKMARK",
            )
            rotational.operator(
                "smrn.remove_surface_candidate", text="移除当前圆润预览", icon="TRASH"
            )
        handle = layout.box()
        handle.label(text="3. 扶手 / 把手还原", icon="CURVE_BEZCURVE")
        handle.label(text="绿色标管体；红色安装面仅用于纠偏")
        handle.operator(
            "smrn.build_handle_candidate",
            text="一键生成扶手候选",
            icon="MESH_TORUS",
        )
        if _candidate_exists(scene, "smrn_handle_candidate_name", "SMRN_HANDLE_CANDIDATE_"):
            handle.prop(scene, "smrn_handle_thickness_scale", text="粗细（1.00 = 刚好覆盖）", slider=True)
            handle.operator("smrn.adjust_handle_thickness", text="应用粗细（不扫描模型）", icon="MOD_SOLIDIFY")
            confirm = handle.operator("smrn.confirm_candidate", text="确认并清除标记", icon="CHECKMARK")
            confirm.candidate_kind = "handle"
            handle.operator("smrn.remove_handle_candidate", text="移除当前扶手候选", icon="TRASH")

        surface = layout.box()
        surface.label(text="4. 局部原网面重构", icon="MOD_REMESH")
        surface.label(text="绿色：重构区域  ·  红色：锁定保留")
        direction = surface.row(align=True)
        direction.prop(scene, "smrn_surface_height_mode", text="高度")
        direction.prop(scene, "smrn_surface_normal_mode", text="法向")
        row = surface.row(align=True)
        smooth = row.operator(
            "smrn.build_surface_candidate",
            text="细化平滑",
            icon="MOD_SUBSURF",
        )
        smooth.mode = "smooth"
        flatten = row.operator(
            "smrn.build_surface_candidate",
            text="一键平整",
            icon="SNAP_FACE",
        )
        flatten.mode = "flatten"
        canvas = surface.operator(
            "smrn.build_surface_candidate",
            text="帆布波浪重建",
            icon="MOD_WAVE",
        )
        canvas.mode = "canvas"
        physics = surface.operator(
            "smrn.build_surface_candidate",
            text="多折面帆布重建（物理）",
            icon="PHYSICS",
        )
        physics.mode = "canvas_physics"
        has_surface_candidate = has_any_surface_candidate and surface_candidate_mode != "rotational"
        mode = surface_candidate_mode
        if has_surface_candidate:
            if mode == "smooth":
                surface.prop(scene, "smrn_surface_smooth_strength", text="平滑程度", slider=True)
                hint = surface.row()
                hint.scale_y = 0.75
                hint.label(text="0.50 = 旧版最高 · 1.00 = 强平滑", icon="INFO")
            elif mode in {"canvas", "canvas_physics"}:
                surface.prop(scene, "smrn_canvas_wave_strength", text="自然波纹程度", slider=True)
                hint = surface.row()
                hint.scale_y = 0.75
                hint.label(
                    text=(
                        "自动识别上侧绳挂边，使用重力与布料约束；只分析绿色区域"
                        if mode == "canvas_physics"
                        else "从绿色帆布自身拟合方向与波长，不使用随机噪声"
                    ),
                    icon="INFO",
                )
            apply = surface.operator(
                "smrn.build_surface_candidate", text="重新应用（只重算标记附近）", icon="FILE_REFRESH"
            )
            apply.mode = mode

        confirm_row = surface.row()
        if has_surface_candidate:
            confirm_text = {
                "flatten": "确认平整并清除标记",
                "smooth": "确认平滑并清除标记",
                "canvas": "确认帆布波浪并清除标记",
                "canvas_physics": "确认多折面帆布并清除标记",
            }.get(mode, "确认候选并清除标记")
            confirm_row.operator(
                "smrn.confirm_surface_replacement",
                text=confirm_text,
                icon="CHECKMARK",
            )
        elif not has_any_surface_candidate:
            confirm_row.enabled = bool(counts[TARGET_ROLE] or counts[EXCLUDE_ROLE])
            confirm_row.operator(
                "smrn.accept_current_surface",
                text="确认当前效果并清除标记",
                icon="CHECKMARK",
            )
        if has_surface_candidate:
            surface.operator("smrn.remove_surface_candidate", text="移除当前网面候选", icon="TRASH")

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
            marking.prop(scene, "smrn_magnetic_radius_px", text="刷选覆盖半径", slider=True)

            rotational_settings = advanced.column(align=True)
            rotational_settings.label(text="圆润拟合")
            rotational_settings.label(text="独立圆圈候选（不替换原网面）", icon="MESH_CIRCLE")
            rotational_settings.operator(
                "smrn.build_rotational_candidate", text="生成独立圆圈候选", icon="MESH_CYLINDER"
            )
            if _candidate_exists(
                scene, "smrn_rotational_candidate_name", "SMRN_ROTATIONAL_CANDIDATE_"
            ):
                selected_input = _candidate_input_mode(
                    scene, "smrn_rotational_candidate_name"
                ) == "selected_faces"
                confirm = rotational_settings.operator(
                    "smrn.confirm_candidate",
                    text=(
                        "确认独立圆圈（保留标记）"
                        if selected_input
                        else "确认独立圆圈并清除标记"
                    ),
                    icon="CHECKMARK",
                )
                confirm.candidate_kind = "rotational"
                rotational_settings.operator(
                    "smrn.remove_rotational_candidate",
                    text="移除独立圆圈候选",
                    icon="TRASH",
                )
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

            surface_settings = advanced.column(align=True)
            surface_settings.label(text="局部原网面重构")
            surface_settings.prop(scene, "smrn_surface_subdivision_level", text="细化等级")
            surface_settings.prop(scene, "smrn_surface_hard_angle", text="硬边保护角度")
            surface_settings.label(text=scene.smrn_surface_summary, icon="INFO")

        if scene.smrn_status:
            status = layout.box()
            status.label(text="状态", icon="INFO")
            status.label(text=scene.smrn_status)


CLASSES = (SMRN_PT_marking,)
