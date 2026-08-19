import json
import uuid
from datetime import datetime, timezone

import bpy

from .constants import (
    EXCLUDE_COLOR,
    EXCLUDE_ROLE,
    MARK_PREFIX,
    MODAL_TOKEN_KEY,
    TARGET_COLOR,
    TARGET_ROLE,
)
from .overlay import create_surface_overlay, remove_overlay
from .raycast import magnetic_scene_hit
from .records import MarkRecord
from .anchors import enrich_hit_anchor, source_snapshot
from .storage import append_mark, clear_task_marks, document_summary, next_id, pop_last_mark, set_active_source
from .rotational_blender import analyze_scene, build_scene_candidate, remove_last_candidate, store_analysis
from .handle_blender import (
    adjust_candidate_thickness,
    analyze_scene as analyze_handle_scene,
    build_scene_candidate as build_handle_candidate,
    remove_last_candidate as remove_handle_candidate,
    store_analysis as store_handle_analysis,
)
from .scene_state import (
    ensure_scene_roots,
    keep_model_visible,
    set_helpers_hidden,
    set_source,
    visible_meshes,
)


def _set_status(scene, text):
    scene.smrn_status = text


def _accepted_collection(scene):
    model, _candidates, _helpers = ensure_scene_roots(scene)
    name = "SMR_01A_已确认修复_始终可见"
    accepted = bpy.data.collections.get(name)
    if accepted is None:
        accepted = bpy.data.collections.new(name)
    if model.children.get(accepted.name) is None:
        model.children.link(accepted)
    accepted["smrn_collection_role"] = "accepted_repairs"
    accepted.hide_viewport = False
    accepted.hide_render = False
    return accepted


def _accept_candidate(scene, kind):
    settings = {
        "handle": ("smrn_handle_candidate_name", "SMRN_HANDLE_CANDIDATE_", "smrn_handle_report_json", "SMRN_HANDLE_ACCEPTED_"),
        "rotational": ("smrn_rotational_candidate_name", "SMRN_ROTATIONAL_CANDIDATE_", "smrn_rotational_report_json", "SMRN_ROTATIONAL_ACCEPTED_"),
    }
    key, prefix, report_key, accepted_prefix = settings[kind]
    name = str(scene.get(key, ""))
    obj = bpy.data.objects.get(name)
    if obj is None or not name.startswith(prefix) or bool(obj.get("smrn_accepted", False)):
        raise ValueError("没有可确认的当前候选")
    try:
        report = json.loads(str(obj.get(report_key, "{}")))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("当前候选缺少可靠的生成报告") from error
    topology = report.get("topology_qa", {})
    coverage = report.get("coverage_qa", {})
    if report.get("status") != "candidate_ready" or not topology.get("passed") or not coverage.get("passed"):
        raise ValueError("当前候选尚未通过拓扑和覆盖质量门槛")
    if not report.get("source_unchanged", False):
        raise ValueError("源模型不变性检查未通过，不能确认")
    accepted = _accepted_collection(scene)
    if accepted.objects.get(obj.name) is None:
        accepted.objects.link(obj)
    for owner in tuple(obj.users_collection):
        if owner != accepted:
            owner.objects.unlink(obj)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    obj.name = f"{accepted_prefix}{stamp}"
    obj["smrn_accepted"] = True
    obj["smrn_candidate_only"] = False
    obj["smrn_accepted_at_utc"] = stamp
    scene[key] = ""
    return obj


class SMRN_OT_setup_source(bpy.types.Operator):
    bl_idname = "smrn.setup_source"
    bl_label = "设为当前语义源"
    bl_description = "将选中网格放入当前模型集合；不复制、不隐藏、不修改网格"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        source = context.active_object
        if source is None or source.type != "MESH":
            self.report({"ERROR"}, "请先选择一个网格对象")
            return {"CANCELLED"}
        set_source(context.scene, source)
        set_active_source(context.scene, source_snapshot(source))
        _set_status(context.scene, f"当前语义源：{source.name}；源模型保持可见且未修改。")
        return {"FINISHED"}


class SMRN_OT_mark_surface(bpy.types.Operator):
    bl_idname = "smrn.mark_surface"
    bl_label = "语义表面标记"
    bl_description = "在所有可见网格的最前方表面建立非破坏式目标或排除标记"
    bl_options = {"REGISTER", "UNDO"}

    mark_value: bpy.props.IntProperty(default=1)

    def _finish(self, context):
        if context.scene.get(MODAL_TOKEN_KEY, "") == getattr(self, "_token", ""):
            context.scene[MODAL_TOKEN_KEY] = ""
        context.window.cursor_modal_restore()
        counts = document_summary(context.scene)["role_counts"]
        _set_status(context.scene, f"标记结束：目标 {counts['target']}，排除 {counts['exclude']}。")

    def _click(self, context, event):
        x = event.mouse_x - self._window_region.x
        y = event.mouse_y - self._window_region.y
        if not (0 <= x < self._window_region.width and 0 <= y < self._window_region.height):
            return
        hit = magnetic_scene_hit(
            context,
            self._window_region,
            self._region_3d,
            (x, y),
            context.scene.smrn_magnetic_radius_px,
        )
        if hit is None:
            _set_status(context.scene, "未找到可见表面；请靠近零件点击或增大磁吸半径。")
            return
        summary = document_summary(context.scene)
        number = next_id(context.scene)
        role = TARGET_ROLE if self.mark_value == 1 else EXCLUDE_ROLE
        color = TARGET_COLOR if role == TARGET_ROLE else EXCLUDE_COLOR
        name = f"{MARK_PREFIX}{number:04d}_{role.upper()}"
        try:
            _overlay, surface_offset, stored_normal = create_surface_overlay(
                context, name, hit, color, context.scene.smrn_marker_size
            )
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return
        source = bpy.data.objects.get(hit["source_object_name"])
        hit_object = bpy.data.objects.get(hit["hit_object_name"])
        if source is not None:
            snapshot = summary.get("source") or source_snapshot(source)
            if not summary.get("source"):
                set_active_source(context.scene, snapshot)
        if hit_object is not None:
            fingerprint = source_snapshot(hit_object).get("fingerprint", "")
            enrich_hit_anchor(hit, hit_object, fingerprint)
        record = MarkRecord(
            id=number,
            task_id=summary["task_id"],
            role=role,
            overlay_object_name=name,
            hit_object_name=hit["hit_object_name"],
            source_object_name=hit["source_object_name"],
            face_index=hit["face_index"],
            world_location=tuple(hit["world_location"]),
            world_normal=tuple(stored_normal),
            screen_offset_px=hit["screen_offset_px"],
            surface_offset=surface_offset,
            local_location=hit.get("local_location"),
            local_normal=hit.get("local_normal"),
            triangle_vertex_indices=hit.get("triangle_vertex_indices"),
            barycentric=hit.get("barycentric"),
            source_fingerprint=hit.get("source_fingerprint", ""),
            semantic_radius=float(context.scene.smrn_marker_size),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        if not append_mark(context.scene, record):
            remove_overlay(name)
            _set_status(context.scene, "该位置已有标记；未创建重复记录。")
            return
        _set_status(
            context.scene,
            f"已标记 {hit['hit_object_name']} 面 {hit['face_index']}；磁吸偏移 {hit['screen_offset_px']:.1f}px。",
        )

    def invoke(self, context, event):
        if context.area is None or context.area.type != "VIEW_3D":
            self.report({"ERROR"}, "请从 3D 视图侧栏启动标记")
            return {"CANCELLED"}
        meshes = visible_meshes(context)
        if not meshes:
            self.report({"ERROR"}, "当前视图没有可见网格")
            return {"CANCELLED"}
        self._window_region = next((region for region in context.area.regions if region.type == "WINDOW"), None)
        self._ui_region = next((region for region in context.area.regions if region.type == "UI"), None)
        if self._window_region is None:
            self.report({"ERROR"}, "找不到 3D 视图窗口")
            return {"CANCELLED"}
        self._region_3d = context.space_data.region_3d
        self._token = uuid.uuid4().hex
        context.scene[MODAL_TOKEN_KEY] = self._token
        context.window.cursor_modal_set("PAINT_BRUSH")
        context.window_manager.modal_handler_add(self)
        _set_status(context.scene, f"标记已启动：检测 {len(meshes)} 个可见网格；左键标记，Z 撤销，右键结束。")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if context.scene.get(MODAL_TOKEN_KEY, "") != getattr(self, "_token", ""):
            self._finish(context)
            return {"FINISHED"}
        if event.type == "Z" and event.value == "PRESS":
            bpy.ops.smrn.undo_mark()
            return {"RUNNING_MODAL"}
        if event.type in {"RET", "NUMPAD_ENTER", "RIGHTMOUSE", "ESC"} and event.value == "PRESS":
            self._finish(context)
            return {"FINISHED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            over_sidebar = self._ui_region is not None and (
                self._ui_region.x <= event.mouse_x < self._ui_region.x + self._ui_region.width
                and self._ui_region.y <= event.mouse_y < self._ui_region.y + self._ui_region.height
            )
            if over_sidebar:
                self._finish(context)
                return {"FINISHED"}
            self._click(context, event)
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}


class SMRN_OT_undo_mark(bpy.types.Operator):
    bl_idname = "smrn.undo_mark"
    bl_label = "撤销上一标记"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        record = pop_last_mark(context.scene)
        if record is None:
            self.report({"WARNING"}, "没有可撤销的标记")
            return {"CANCELLED"}
        remove_overlay(record.overlay_object_name)
        remaining = document_summary(context.scene)["mark_count"]
        _set_status(context.scene, f"已撤销标记 {record.id}；剩余 {remaining} 个。")
        return {"FINISHED"}


class SMRN_OT_clear_marks(bpy.types.Operator):
    bl_idname = "smrn.clear_marks"
    bl_label = "清空全部标记"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = clear_task_marks(context.scene)
        for record in removed:
            remove_overlay(record.overlay_object_name)
        keep_model_visible(context.scene)
        _set_status(context.scene, "全部语义标记已清除；源模型未修改并保持可见。")
        return {"FINISHED"}


class SMRN_OT_toggle_helpers(bpy.types.Operator):
    bl_idname = "smrn.toggle_helpers"
    bl_label = "显示/隐藏标记辅助"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _model, _candidates, helpers = ensure_scene_roots(context.scene)
        hidden = not helpers.hide_viewport
        set_helpers_hidden(context.scene, hidden)
        _set_status(context.scene, "标记辅助已隐藏；当前模型保持可见。" if hidden else "标记辅助已显示。")
        context.view_layer.update()
        return {"FINISHED"}


class SMRN_OT_stop_marking(bpy.types.Operator):
    bl_idname = "smrn.stop_marking"
    bl_label = "退出标记 / 恢复普通选择"

    def execute(self, context):
        context.scene[MODAL_TOKEN_KEY] = ""
        keep_model_visible(context.scene)
        _set_status(context.scene, "已退出标记模式；普通选择已恢复。")
        return {"FINISHED"}


class SMRN_OT_analyze_rotational(bpy.types.Operator):
    bl_idname = "smrn.analyze_rotational"
    bl_label = "分析圆柱 / 圆锥证据"
    bl_description = "只读分析本轮目标与排除标记；不会生成几何或修改源网格"

    def execute(self, context):
        try:
            fit, _source, _targets, _excludes, report = analyze_scene(context.scene)
        except (ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            _set_status(context.scene, f"旋转曲面分析失败：{error}")
            return {"CANCELLED"}
        report.update({"status": fit.status, "fit": fit.to_dict()})
        store_analysis(context.scene, report)
        context.scene.smrn_rotational_summary = (
            f"{fit.profile_kind} · {fit.coverage_mode} · 置信度 {fit.confidence:.2f}"
            if fit.status == "candidate_ready" else f"证据不足：{fit.reason}"
        )
        _set_status(context.scene, context.scene.smrn_rotational_summary)
        return {"FINISHED"}


class SMRN_OT_build_rotational_candidate(bpy.types.Operator):
    bl_idname = "smrn.build_rotational_candidate"
    bl_label = "生成圆润候选"
    bl_description = "通过拟合与质量门槛后生成独立封闭候选；源网格保持不变"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            candidate, report = build_scene_candidate(context.scene)
        except (ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            _set_status(context.scene, f"候选生成失败：{error}")
            return {"CANCELLED"}
        store_analysis(context.scene, report)
        if candidate is None:
            reason = report.get("reason", "质量门槛未通过")
            context.scene.smrn_rotational_summary = f"已拒绝：{reason}"
            _set_status(context.scene, context.scene.smrn_rotational_summary)
            self.report({"WARNING"}, reason)
            return {"CANCELLED"}
        fit = report["fit"]
        context.scene.smrn_rotational_summary = (
            f"候选 {candidate.name} · {fit['profile_kind']} · "
            f"覆盖 {report['coverage_qa']['samples']} 点 · 拓扑封闭"
        )
        _set_status(context.scene, context.scene.smrn_rotational_summary)
        return {"FINISHED"}


class SMRN_OT_remove_rotational_candidate(bpy.types.Operator):
    bl_idname = "smrn.remove_rotational_candidate"
    bl_label = "移除圆润候选"
    bl_description = "只移除本插件最近生成的候选，不影响源网格"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = remove_last_candidate(context.scene)
        context.scene.smrn_rotational_summary = "候选已移除；源网格保持不变" if removed else "没有可移除的圆润候选"
        _set_status(context.scene, context.scene.smrn_rotational_summary)
        return {"FINISHED" if removed else "CANCELLED"}


class SMRN_OT_analyze_handle(bpy.types.Operator):
    bl_idname = "smrn.analyze_handle"
    bl_label = "分析扶手证据"
    bl_description = "只读分析绿色扶手管体；红色双端安装面为可选纠偏证据"

    def execute(self, context):
        try:
            fit, _source, _targets, _supports, report = analyze_handle_scene(context.scene)
        except (ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            _set_status(context.scene, f"扶手分析失败：{error}")
            return {"CANCELLED"}
        report.update({"status": fit.status, "fit": fit.to_dict()})
        store_handle_analysis(context.scene, report)
        context.scene.smrn_handle_summary = (
            f"{fit.path_kind} · 置信度 {fit.confidence:.2f} · 安装角已锁定"
            if fit.status == "candidate_ready" else f"证据不足：{fit.reason}"
        )
        _set_status(context.scene, context.scene.smrn_handle_summary)
        return {"FINISHED"}


class SMRN_OT_build_handle_candidate(bpy.types.Operator):
    bl_idname = "smrn.build_handle_candidate"
    bl_label = "生成扶手候选"
    bl_description = "质量门槛通过后生成独立封闭扶手；不会替换源网格"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            candidate, report = build_handle_candidate(context.scene)
        except (ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            _set_status(context.scene, f"扶手候选生成失败：{error}")
            return {"CANCELLED"}
        store_handle_analysis(context.scene, report)
        if candidate is None:
            request = report.get("evidence_request", {})
            if request.get("required"):
                report["reason"] = f"请补标：{request['message']}"
            reason = report.get("reason", "扶手质量门槛未通过")
            context.scene.smrn_handle_summary = f"已拒绝：{reason}"
            _set_status(context.scene, context.scene.smrn_handle_summary)
            self.report({"WARNING"}, reason)
            return {"CANCELLED"}
        qa = report["coverage_qa"]
        context.scene.smrn_handle_summary = (
            f"候选 {candidate.name} · 密集覆盖 {qa['samples']} 点 · 封闭流形"
        )
        _set_status(context.scene, context.scene.smrn_handle_summary)
        return {"FINISHED"}


class SMRN_OT_remove_handle_candidate(bpy.types.Operator):
    bl_idname = "smrn.remove_handle_candidate"
    bl_label = "移除扶手候选"
    bl_description = "只移除最近生成的扶手候选，不影响源模型"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = remove_handle_candidate(context.scene)
        context.scene.smrn_handle_summary = (
            "扶手候选已移除；源网格保持不变" if removed else "没有可移除的扶手候选"
        )
        _set_status(context.scene, context.scene.smrn_handle_summary)
        return {"FINISHED" if removed else "CANCELLED"}


class SMRN_OT_adjust_handle_thickness(bpy.types.Operator):
    bl_idname = "smrn.adjust_handle_thickness"
    bl_label = "应用粗细"
    bl_description = "只调整当前未确认扶手候选的管径；不重新扫描模型，不改变拟合路径和角度"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            candidate, report = adjust_candidate_thickness(context.scene)
        except (ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            _set_status(context.scene, f"粗细调整失败：{error}")
            return {"CANCELLED"}
        scale = report["thickness_adjustment"]["scale"]
        context.scene.smrn_handle_summary = f"{candidate.name} · 粗细 {scale:.2f}× · 未扫描模型"
        _set_status(context.scene, context.scene.smrn_handle_summary)
        return {"FINISHED"}


class SMRN_OT_confirm_candidate(bpy.types.Operator):
    bl_idname = "smrn.confirm_candidate"
    bl_label = "确认候选并清除本轮标记"
    bl_description = "归档当前候选、清除本插件本轮绿色/红色标记并保存工程；已确认结果不会被后续生成覆盖"
    bl_options = {"REGISTER"}

    candidate_kind: bpy.props.EnumProperty(
        items=(("handle", "扶手", ""), ("rotational", "圆润", "")),
        default="handle",
    )

    def execute(self, context):
        if not bpy.data.filepath:
            self.report({"ERROR"}, "请先保存当前 Blender 工程，再确认候选")
            return {"CANCELLED"}
        try:
            accepted = _accept_candidate(context.scene, self.candidate_kind)
            removed = clear_task_marks(context.scene)
            for record in removed:
                remove_overlay(record.overlay_object_name)
            keep_model_visible(context.scene, (accepted,))
            bpy.ops.wm.save_mainfile()
        except (ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            _set_status(context.scene, f"确认失败：{error}")
            return {"CANCELLED"}
        context.scene.smrn_handle_summary = "尚未分析本轮扶手标记"
        context.scene.smrn_rotational_summary = "尚未分析本轮标记"
        _set_status(context.scene, f"已确认 {accepted.name}，清除本轮 {len(removed)} 个标记，可以开始下一次生成")
        return {"FINISHED"}


CLASSES = (
    SMRN_OT_setup_source,
    SMRN_OT_mark_surface,
    SMRN_OT_undo_mark,
    SMRN_OT_clear_marks,
    SMRN_OT_toggle_helpers,
    SMRN_OT_stop_marking,
    SMRN_OT_analyze_rotational,
    SMRN_OT_build_rotational_candidate,
    SMRN_OT_remove_rotational_candidate,
    SMRN_OT_analyze_handle,
    SMRN_OT_build_handle_candidate,
    SMRN_OT_remove_handle_candidate,
    SMRN_OT_adjust_handle_thickness,
    SMRN_OT_confirm_candidate,
)
