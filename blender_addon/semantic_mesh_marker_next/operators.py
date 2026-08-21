import json
import math
import uuid
from datetime import datetime, timezone

import bpy
import bmesh

from .constants import (
    EXCLUDE_COLOR,
    EXCLUDE_ROLE,
    MARK_PREFIX,
    MODAL_TOKEN_KEY,
    TARGET_COLOR,
    TARGET_ROLE,
)
from .overlay import create_surface_overlay, remove_overlay
from .raycast import brush_object_hits, magnetic_scene_hit
from .records import MarkRecord
from .anchors import enrich_hit_anchor, source_snapshot
from .storage import (
    append_mark,
    clear_task_marks,
    document_summary,
    load_all_marks,
    next_id,
    pop_last_mark,
    set_active_source,
)
from .rotational_blender import (
    analyze_scene,
    build_scene_candidate,
    build_selected_scene_candidate,
    remove_last_candidate,
    store_analysis,
)
from .handle_blender import (
    adjust_candidate_thickness,
    analyze_scene as analyze_handle_scene,
    build_scene_candidate as build_handle_candidate,
    remove_last_candidate as remove_handle_candidate,
    store_analysis as store_handle_analysis,
)
from .surface_rebuild_blender import (
    build_scene_candidate as build_surface_candidate,
    confirm_replacement as confirm_surface_replacement,
    remove_last_candidate as remove_surface_candidate,
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


def _selected_rotational_faces(context):
    """Read exact edit-mode selection; return None outside mesh edit mode."""
    if context.mode != "EDIT_MESH" or context.edit_object is None:
        return None
    source = context.edit_object
    configured = bpy.data.objects.get(str(context.scene.get("smrn_source_name", "")))
    if configured is not source:
        raise ValueError("请在当前语义源上进入编辑模式并选择侧面")
    mesh = bmesh.from_edit_mesh(source.data)
    mesh.faces.ensure_lookup_table()
    indices = {face.index for face in mesh.faces if face.select and not face.hide}
    if len(indices) < 4:
        raise ValueError("至少选择 4 个连续侧面；不要选择端盖、台阶或其他零件")
    return source, indices


def _restore_edit_selection(context, source, face_indices):
    """Recover the user's exact face selection after a rejected build."""
    try:
        context.view_layer.objects.active = source
        source.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        mesh = bmesh.from_edit_mesh(source.data)
        mesh.faces.ensure_lookup_table()
        selected = set(face_indices)
        for face in mesh.faces:
            face.select = face.index in selected
        bmesh.update_edit_mesh(source.data, loop_triangles=False, destructive=False)
    except (AttributeError, ReferenceError, RuntimeError):
        pass


def _restore_normal_selection(context, source=None):
    """Exit semantic painting and return the viewport to ordinary object selection."""
    context.scene[MODAL_TOKEN_KEY] = ""
    try:
        context.window.cursor_modal_restore()
    except (AttributeError, RuntimeError):
        pass

    active = context.view_layer.objects.active
    if active is not None and active.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError:
            pass

    if source is not None:
        for obj in tuple(context.selected_objects):
            try:
                obj.select_set(False)
            except (AttributeError, ReferenceError):
                pass
        try:
            source.select_set(True)
            context.view_layer.objects.active = source
        except (AttributeError, ReferenceError):
            pass
        keep_model_visible(context.scene, (source,))
    else:
        keep_model_visible(context.scene)


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
        owns_token = context.scene.get(MODAL_TOKEN_KEY, "") == getattr(self, "_token", "")
        if owns_token:
            context.scene[MODAL_TOKEN_KEY] = ""
        try:
            context.window.cursor_modal_restore()
        except (AttributeError, RuntimeError):
            pass
        if owns_token:
            counts = document_summary(context.scene)["role_counts"]
            _set_status(context.scene, f"标记结束：目标 {counts['target']}，排除 {counts['exclude']}。")

    def _over_sidebar(self, mouse_x, mouse_y):
        return self._ui_region is not None and (
            self._ui_region.x <= mouse_x < self._ui_region.x + self._ui_region.width
            and self._ui_region.y <= mouse_y < self._ui_region.y + self._ui_region.height
        )

    def _store_hit(self, context, hit, *, dragging=False):
        self._stroke_object_name = hit["hit_object_name"]
        face_key = (hit["hit_object_name"], int(hit["face_index"]))
        if face_key in self._marked_faces:
            return False
        number = self._next_mark_id
        role = TARGET_ROLE if self.mark_value == 1 else EXCLUDE_ROLE
        color = TARGET_COLOR if role == TARGET_ROLE else EXCLUDE_COLOR
        name = f"{MARK_PREFIX}{number:04d}_{role.upper()}"
        try:
            _overlay, surface_offset, stored_normal = create_surface_overlay(
                context, name, hit, color, context.scene.smrn_marker_size
            )
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return False
        source = bpy.data.objects.get(hit["source_object_name"])
        hit_object = bpy.data.objects.get(hit["hit_object_name"])
        if source is not None:
            snapshot = self._source_snapshot or source_snapshot(source)
            if self._source_snapshot is None:
                set_active_source(context.scene, snapshot)
                self._source_snapshot = snapshot
        if hit_object is not None:
            fingerprint = self._fingerprints.get(hit_object.name)
            if fingerprint is None:
                fingerprint = source_snapshot(hit_object).get("fingerprint", "")
                self._fingerprints[hit_object.name] = fingerprint
            enrich_hit_anchor(hit, hit_object, fingerprint)
        record = MarkRecord(
            id=number,
            task_id=self._task_id,
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
            self._marked_faces.add(face_key)
            if not dragging:
                _set_status(context.scene, "该位置已有标记；可按住左键继续刷过相邻网面。")
            return False
        self._marked_faces.add(face_key)
        self._next_mark_id += 1
        if not dragging:
            _set_status(
                context.scene,
                f"已标记 {hit['hit_object_name']} 面 {hit['face_index']}；磁吸偏移 {hit['screen_offset_px']:.1f}px。",
            )
        return True

    def _paint_at(self, context, mouse_x, mouse_y, *, dragging=False):
        x = mouse_x - self._window_region.x
        y = mouse_y - self._window_region.y
        if not (0 <= x < self._window_region.width and 0 <= y < self._window_region.height):
            return False
        radius = int(context.scene.smrn_magnetic_radius_px)
        if dragging:
            # Dragging is a visible-surface brush disc, not a sequence of
            # single magnetic picks. The cap protects dense vehicle scenes.
            brush_radius = max(0, min(radius, 24))
            hits = brush_object_hits(
                context,
                self._window_region,
                self._region_3d,
                (x, y),
                brush_radius,
                self._stroke_object_name,
            )
        else:
            hit = magnetic_scene_hit(
                context, self._window_region, self._region_3d, (x, y), radius
            )
            hits = [hit] if hit is not None else []
        if not hits:
            if not dragging:
                _set_status(context.scene, "未找到可见表面；请靠近零件点击或增大刷选覆盖半径。")
            return False
        painted_count = sum(
            1 for hit in hits if self._store_hit(context, hit, dragging=dragging)
        )
        if dragging and painted_count > 1:
            _set_status(context.scene, f"本次刷选覆盖 {painted_count} 个可见网面；已自动跳过重复面。")
        return painted_count > 0

    def _stroke_spacing(self, context):
        radius = max(2.0, min(float(context.scene.smrn_magnetic_radius_px), 24.0))
        return max(4.0, min(7.0, radius * 0.5))

    def _paint_segment(self, context, start, end):
        distance = math.hypot(end[0] - start[0], end[1] - start[1])
        spacing = self._stroke_spacing(context)
        steps = max(1, int(math.ceil(distance / spacing)))
        painted = False
        for step in range(1, steps + 1):
            factor = step / steps
            mouse_x = start[0] + (end[0] - start[0]) * factor
            mouse_y = start[1] + (end[1] - start[1]) * factor
            if self._over_sidebar(mouse_x, mouse_y):
                continue
            painted = self._paint_at(context, mouse_x, mouse_y, dragging=True) or painted
        return painted

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
        self._painting = False
        self._last_paint_window = None
        self._stroke_object_name = ""
        role = TARGET_ROLE if self.mark_value == 1 else EXCLUDE_ROLE
        summary = document_summary(context.scene)
        self._task_id = summary["task_id"]
        self._source_snapshot = summary.get("source")
        self._next_mark_id = next_id(context.scene)
        self._fingerprints = {}
        self._marked_faces = {
            (record.hit_object_name, int(record.face_index))
            for record in load_all_marks(context.scene, summary["task_id"])
            if record.role == role
        }
        self._token = uuid.uuid4().hex
        context.scene[MODAL_TOKEN_KEY] = self._token
        context.window.cursor_modal_set("PAINT_BRUSH")
        context.window_manager.modal_handler_add(self)
        _set_status(context.scene, f"刷选已启动：检测 {len(meshes)} 个可见网格；按住左键拖动，Z 撤销，右键结束。")
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
            if self._over_sidebar(event.mouse_x, event.mouse_y):
                self._finish(context)
                return {"FINISHED"}
            self._painting = True
            self._stroke_object_name = ""
            self._last_paint_window = (event.mouse_x, event.mouse_y)
            self._paint_at(context, event.mouse_x, event.mouse_y)
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE" and getattr(self, "_painting", False):
            current = (event.mouse_x, event.mouse_y)
            previous = self._last_paint_window or current
            if (
                math.hypot(current[0] - previous[0], current[1] - previous[1])
                >= self._stroke_spacing(context)
            ):
                self._paint_segment(context, previous, current)
                self._last_paint_window = current
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE" and getattr(self, "_painting", False):
            current = (event.mouse_x, event.mouse_y)
            previous = self._last_paint_window or current
            if current != previous:
                self._paint_segment(context, previous, current)
            self._painting = False
            self._last_paint_window = None
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


class SMRN_OT_accept_current_surface(bpy.types.Operator):
    bl_idname = "smrn.accept_current_surface"
    bl_label = "确认当前效果并清除标记"
    bl_description = "不替换网面；保留当前源模型，清除本轮标记并恢复普通选择"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if not bpy.data.filepath:
            self.report({"ERROR"}, "请先保存当前 Blender 工程")
            return {"CANCELLED"}
        removed = clear_task_marks(context.scene)
        if not removed:
            self.report({"WARNING"}, "当前没有可确认的标记")
            return {"CANCELLED"}
        for record in removed:
            remove_overlay(record.overlay_object_name)
        source = bpy.data.objects.get(str(context.scene.get("smrn_source_name", "")))
        _restore_normal_selection(context, source)
        context.scene.smrn_surface_summary = "尚未生成局部网面候选"
        message = f"已保留当前网面；清除本轮 {len(removed)} 个标记，普通选择已恢复"
        _set_status(context.scene, message)
        self.report({"INFO"}, message)
        bpy.ops.wm.save_mainfile()
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
        _restore_normal_selection(context)
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
    bl_label = "生成独立圆圈候选"
    bl_description = "使用绿色刷选拟合独立封闭圆圈/圆弧候选；不替换当前原网面结果，也不扫描整车"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected = None
        try:
            mark_counts = document_summary(context.scene).get("role_counts", {})
            has_green_marks = int(mark_counts.get(TARGET_ROLE, 0)) > 0
            if has_green_marks:
                # Semantic brush marks are the normal, lightweight workflow.  Do not let
                # stale native edit selections shadow an already valid green selection.
                if context.mode == "EDIT_MESH":
                    bpy.ops.object.mode_set(mode="OBJECT")
                candidate, report = build_scene_candidate(context.scene)
            else:
                selected = _selected_rotational_faces(context)
                if selected is None:
                    raise ValueError("请先用绿色刷子标记要圆润的侧面；无需进入编辑模式")
                source, face_indices = selected
                bpy.ops.object.mode_set(mode="OBJECT")
                candidate, report = build_selected_scene_candidate(
                    context.scene, source, face_indices
                )
        except (ValueError, RuntimeError) as error:
            if selected is not None:
                _restore_edit_selection(context, selected[0], selected[1])
            self.report({"ERROR"}, str(error))
            _set_status(context.scene, f"候选生成失败：{error}")
            return {"CANCELLED"}
        store_analysis(context.scene, report)
        if candidate is None:
            if selected is not None:
                _restore_edit_selection(context, selected[0], selected[1])
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
        for obj in tuple(context.selected_objects):
            obj.select_set(False)
        candidate.select_set(True)
        context.view_layer.objects.active = candidate
        keep_model_visible(context.scene, (candidate, selected[0] if selected else None))
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
            selected_input = (
                self.candidate_kind == "rotational"
                and str(accepted.get("smrn_input_mode", "")) == "selected_faces"
            )
            removed = [] if selected_input else clear_task_marks(context.scene)
            if not selected_input:
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
        if selected_input:
            message = f"已确认 {accepted.name}；只消费选中面，现有语义标记保持不变"
        else:
            message = f"已确认 {accepted.name}，清除本轮 {len(removed)} 个标记，可以开始下一次生成"
        _set_status(context.scene, message)
        return {"FINISHED"}


class SMRN_OT_build_surface_candidate(bpy.types.Operator):
    bl_idname = "smrn.build_surface_candidate"
    bl_label = "生成局部网面重构候选"
    bl_description = "只处理绿色标记面；未标记面、红色面与绿色区域边界保持不变"
    bl_options = {"REGISTER", "UNDO"}

    mode: bpy.props.EnumProperty(
        items=(
            ("smooth", "细化平滑", ""),
            ("flatten", "一键平整", ""),
            ("rotational", "重建圆润原网面", ""),
            ("canvas", "帆布波浪重建", ""),
            ("canvas_physics", "多折面帆布重建（物理）", ""),
        ),
        default="smooth",
    )

    def execute(self, context):
        previous_candidate_name = str(context.scene.get("smrn_surface_candidate_name", ""))
        previous_candidate = bpy.data.objects.get(previous_candidate_name)
        had_previous_candidate = bool(
            previous_candidate is not None
            and previous_candidate_name.startswith("SMRN_SURFACE_CANDIDATE_")
        )
        try:
            candidate, report = build_surface_candidate(context.scene, self.mode)
        except (ValueError, RuntimeError) as error:
            if had_previous_candidate and bpy.data.objects.get(previous_candidate_name) is not None:
                message = f"新设置未通过，已保留上一版候选；源网格未修改：{error}"
            else:
                message = f"生成失败：{error}"
            self.report({"ERROR"}, message)
            context.scene.smrn_surface_summary = message
            _set_status(context.scene, context.scene.smrn_surface_summary)
            return {"CANCELLED"}
        topology = report["topology_qa"]
        region = report["semantic_region"]
        action = {
            "flatten": "平整",
            "smooth": "细化平滑",
            "rotational": "圆柱/圆锥原网面重建",
            "canvas": "帆布波浪重建",
            "canvas_physics": "多折面帆布重建（物理）",
        }.get(report["mode"], "局部重建")
        protection = {
            "flatten": "外边界与红色面已锁定",
            "rotational": "绿色外边界、红色面与未标记面已锁定",
        }.get(report["mode"], "边界、红色面与大折线已锁定")
        reference = ""
        if report["mode"] == "flatten":
            labels = {"LOW": "最低点", "MEDIAN": "居中", "HIGH": "最高点", "RED_REFERENCE": "红面高度"}
            normal_labels = {"AUTO": "自动法向", "FIRST_TARGET": "首个绿面法向", "RED_REFERENCE": "红面法向"}
            choice = report.get("flatten_reference") or {}
            reference = f" · {labels.get(choice.get('height_mode'), '居中')} / {normal_labels.get(choice.get('normal_mode'), '自动法向')}"
        if report.get("reused_existing"):
            context.scene.smrn_surface_summary = f"当前{action}候选已经是最新结果，无需重复生成{reference}"
            self.report({"INFO"}, context.scene.smrn_surface_summary)
            _set_status(context.scene, context.scene.smrn_surface_summary)
            return {"FINISHED"}
        preserved = ""
        if report["mode"] == "flatten":
            planarity = topology.get("planarity_qa") or {}
            preserved_count = int(planarity.get("preserved_component_count", 0))
            preserved_faces = int(planarity.get("preserved_faces", 0))
            if preserved_count:
                preserved = f" · 保留 {preserved_count} 个低支撑/不安全小区域（{preserved_faces} 面）"
        context.scene.smrn_surface_summary = (
            f"{action}候选 · {region['selected_faces']} 面 → "
            f"{topology['region_faces_after']} 面 · {protection}{reference}{preserved}"
        )
        _set_status(context.scene, context.scene.smrn_surface_summary)
        return {"FINISHED"}


class SMRN_OT_remove_surface_candidate(bpy.types.Operator):
    bl_idname = "smrn.remove_surface_candidate"
    bl_label = "移除局部网面候选"
    bl_description = "移除当前预览和工作副本；源模型保持不变"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = remove_surface_candidate(context.scene)
        context.scene.smrn_surface_summary = (
            "局部网面候选已移除；源网格保持不变" if removed else "没有可移除的局部网面候选"
        )
        _set_status(context.scene, context.scene.smrn_surface_summary)
        return {"FINISHED" if removed else "CANCELLED"}


class SMRN_OT_confirm_surface_replacement(bpy.types.Operator):
    bl_idname = "smrn.confirm_surface_replacement"
    bl_label = "确认替换原网面并清除标记"
    bl_description = "以已通过质量检查的工作网格接替源网格；旧网格自动归档并保留 .blend 检查点"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if not bpy.data.filepath:
            self.report({"ERROR"}, "请先保存当前 Blender 工程，再确认替换")
            return {"CANCELLED"}
        try:
            source, archive, _report = confirm_surface_replacement(context.scene)
            removed = clear_task_marks(context.scene)
            for record in removed:
                remove_overlay(record.overlay_object_name)
            _restore_normal_selection(context, source)
            bpy.ops.wm.save_mainfile()
        except (ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            _set_status(context.scene, f"原网面替换失败：{error}")
            return {"CANCELLED"}
        context.scene.smrn_surface_summary = "尚未生成局部网面候选"
        _set_status(
            context.scene,
            f"局部原网面已确认，旧网格归档为 {archive.name}；清除本轮 {len(removed)} 个标记，普通选择已恢复",
        )
        return {"FINISHED"}


CLASSES = (
    SMRN_OT_setup_source,
    SMRN_OT_mark_surface,
    SMRN_OT_undo_mark,
    SMRN_OT_clear_marks,
    SMRN_OT_accept_current_surface,
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
    SMRN_OT_build_surface_candidate,
    SMRN_OT_remove_surface_candidate,
    SMRN_OT_confirm_surface_replacement,
)
