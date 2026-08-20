import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class ProjectContractTests(unittest.TestCase):
    def test_manifest_points_to_existing_skill_directory(self):
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "semantic-mesh-restorer-next")
        self.assertTrue((ROOT / manifest["skills"]).is_dir())

    def test_addon_uses_side_by_side_namespace(self):
        operators = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "operators.py").read_text(encoding="utf-8")
        self.assertIn('bl_idname = "smrn.mark_surface"', operators)
        self.assertNotIn('bl_idname = "smr.', operators)

    def test_marker_supports_continuous_drag_brushing(self):
        operators = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "operators.py").read_text(encoding="utf-8")
        self.assertIn('event.type == "MOUSEMOVE"', operators)
        self.assertIn("def _paint_segment", operators)
        self.assertIn("self._painting = True", operators)
        self.assertIn("dragging=True", operators)

    def test_legacy_helpers_are_excluded_from_raycast(self):
        scene_state = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "scene_state.py").read_text(encoding="utf-8")
        self.assertIn('obj.get("smr_annotation_only", False)', scene_state)
        self.assertIn('obj.get("smr_source_name", "")', scene_state)

    def test_unaccepted_candidates_cannot_steal_brush_hits(self):
        scene_state = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "scene_state.py").read_text(encoding="utf-8")
        raycast = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "raycast.py").read_text(encoding="utf-8")
        self.assertIn("def is_unaccepted_candidate_object", scene_state)
        self.assertIn('owner.name == CANDIDATE_COLLECTION_NAME', scene_state)
        self.assertIn('bool(obj.get("smrn_accepted", False))', scene_state)
        self.assertIn("is_unaccepted_candidate_object(obj)", raycast)
        self.assertIn("passthrough_objects", raycast)

    def test_panel_uses_lightweight_summary(self):
        panel = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "panel.py").read_text(encoding="utf-8")
        self.assertIn("marks_summary(scene)", panel)
        self.assertNotIn("load_marks(scene)", panel)

    def test_panel_defaults_to_one_click_workflow(self):
        panel = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "panel.py").read_text(encoding="utf-8")
        addon = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('text="一键生成圆润候选"', panel)
        self.assertIn('text="一键生成扶手候选"', panel)
        self.assertIn("if scene.smrn_show_advanced:", panel)
        self.assertIn('bpy.types.Scene.smrn_show_advanced = bpy.props.BoolProperty(', addon)
        self.assertIn("default=False", addon)
        advanced_section = panel.split("if scene.smrn_show_advanced:", 1)[1]
        self.assertIn('prop(scene, "smrn_rotational_segments"', advanced_section)
        self.assertIn('prop(scene, "smrn_handle_path_segments"', advanced_section)

    def test_chunked_versioned_storage_exists(self):
        storage = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "storage.py").read_text(encoding="utf-8")
        self.assertIn('DOCUMENT_KEY = "smrn_document_json"', storage)
        self.assertIn("CHUNK_SIZE = 128", storage)

    def test_rotational_feature_stays_non_destructive(self):
        adapter = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "rotational_blender.py").read_text(encoding="utf-8")
        self.assertIn('CANDIDATE_PREFIX = "SMRN_ROTATIONAL_CANDIDATE_"', adapter)
        self.assertIn("_commit_candidate(scene, obj)", adapter)
        self.assertIn("_semantic_rotational_faces(fit, source, targets)", adapter)
        self.assertIn("semantic_expansion", adapter)
        self.assertNotIn("remove_last_candidate(scene)\n    _model, candidates", adapter)
        self.assertIn("source_unchanged", (ROOT / "scripts" / "live_build_gate_test.py").read_text(encoding="utf-8"))
        self.assertNotIn("bpy.ops.object.delete", adapter)
        auto_thickness = adapter.split("def _auto_thickness", 1)[1].split("def _ring_point", 1)[0]
        self.assertIn("feature_scale * 0.01", auto_thickness)
        self.assertIn("radius * 0.005", auto_thickness)
        self.assertNotIn("radius * 0.08", auto_thickness)

    def test_visibility_guard_only_reveals_authoritative_objects(self):
        scene_state = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "scene_state.py").read_text(encoding="utf-8")
        visibility = scene_state.split("def keep_model_visible", 1)[1].split("def set_helpers_hidden", 1)[0]
        self.assertNotIn("model.all_objects", visibility)
        self.assertIn("if obj is None", visibility)
        self.assertIn("required_objects", visibility)
        self.assertIn("except (AttributeError, ReferenceError)", visibility)
        self.assertIn('obj.get("smrn_archive_only", False)', visibility)
        self.assertIn('obj.get("smrn_superseded_source_only", False)', visibility)
        self.assertIn("obj.hide_set(True)", visibility)

    def test_rotational_axis_candidates_are_data_derived(self):
        fitter = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "rotational_fit.py").read_text(encoding="utf-8")
        section = fitter.split("def candidate_axes", 1)[1].split("def _robust_linear", 1)[0]
        self.assertIn("centered_points", section)
        self.assertIn("centered_normals", section)
        self.assertNotIn("np.eye", section)

    def test_handle_feature_is_non_destructive_and_support_constrained(self):
        adapter = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "handle_blender.py").read_text(encoding="utf-8")
        fitter = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "handle_fit.py").read_text(encoding="utf-8")
        self.assertIn('CANDIDATE_PREFIX = "SMRN_HANDLE_CANDIDATE_"', adapter)
        self.assertIn("source_unchanged", adapter)
        self.assertNotIn("bpy.ops.object.delete", adapter)
        self.assertIn("_signed_angle", fitter)
        self.assertIn("support_angle_after_degrees", fitter)
        self.assertNotIn("np.eye", fitter)
        self.assertIn("terminal_bridge", adapter)
        self.assertIn('"topology_bridge_samples": discarded_topology_bridge_samples', adapter)
        self.assertIn("fit.half_span + endpoint_margin", adapter)
        self.assertIn("minimum_enclosing_circle", adapter)
        self.assertIn("_semantic_handle_faces", adapter)
        self.assertIn('"global_geometry_scan": False', adapter)
        self.assertIn('bool(old_obj.get("smrn_accepted", False))', adapter)
        self.assertIn("def _evidence_request", adapter)
        self.assertIn("左右安装平面各补 1 个红色标记", adapter)
        self.assertIn("def _inferred_mount_surface", adapter)
        self.assertIn('"shared_leg_axis": True', adapter)
        self.assertIn('"uncovered": uncovered', adapter)
        self.assertTrue((ROOT / "scripts" / "live_handle_build_gate_test.py").is_file())

    def test_candidate_confirmation_and_local_thickness_workflow(self):
        operators = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "operators.py").read_text(encoding="utf-8")
        panel = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "panel.py").read_text(encoding="utf-8")
        adapter = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "handle_blender.py").read_text(encoding="utf-8")
        self.assertIn('bl_idname = "smrn.confirm_candidate"', operators)
        self.assertIn('clear_task_marks(context.scene)', operators)
        self.assertIn('obj["smrn_accepted"] = True', operators)
        self.assertIn('bpy.ops.wm.save_mainfile()', operators)
        self.assertIn('text="确认并清除标记"', panel)
        self.assertIn('text="粗细（1.00 = 刚好覆盖）"', panel)
        self.assertIn('def adjust_candidate_thickness(scene):', adapter)
        self.assertIn('"model_rescanned": False', adapter)

    def test_local_surface_rebuild_is_feature_locked_and_recoverable(self):
        adapter = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "surface_rebuild_blender.py").read_text(encoding="utf-8")
        operators = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "operators.py").read_text(encoding="utf-8")
        panel = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "panel.py").read_text(encoding="utf-8")
        addon = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('CANDIDATE_PREFIX = "SMRN_SURFACE_CANDIDATE_"', adapter)
        self.assertIn("obj.show_in_front = False", adapter)
        self.assertIn("preview.show_in_front = False", adapter)
        self.assertIn('"global_geometry_scan": False', adapter)
        self.assertIn('"selection_method": "exact_brushed_faces"', adapter)
        self.assertIn('"display_radius_used_for_growth": False', adapter)
        self.assertIn('def _normal_hint_from_records', adapter)
        self.assertIn('def _height_reference_from_records', adapter)
        self.assertIn('height_mode == "RED_REFERENCE"', adapter)
        self.assertIn('hard_edges if mode != "flatten" else set()', adapter)
        self.assertIn("locked_edges = boundary_edges | protected_feature_edges | excluded_edges", adapter)
        self.assertIn('"scope_policy": "strict_green_faces_only_v2"', adapter)
        self.assertIn("if any(face not in region_face_set for face in vertex.link_faces)", adapter)
        self.assertIn('"strict_marked_scope": True', adapter)
        self.assertIn('"unmarked_vertices_moved": 0', adapter)
        self.assertIn('"progress_metric_scope": "editable_green_interior_vertices"', adapter)
        self.assertIn("matched_dihedral_edges", adapter)
        self.assertIn('"dihedral_sample_matched": True', adapter)
        self.assertIn('"dihedral_edges_before": len(matched_dihedral_edges)', adapter)
        self.assertIn('"dihedral_edges_after": len(matched_dihedral_edges)', adapter)
        self.assertNotIn("before_inner_edges", adapter)
        self.assertIn('"quality_gates": quality_gates', adapter)
        self.assertIn("preview_source_faces = set(region_faces)", adapter)
        self.assertNotIn("transition_ring_count = max(", adapter)
        self.assertIn("flatten_projection_fraction >= 0.5", adapter)
        self.assertIn("max_allowed_displacement", adapter)
        self.assertIn("source.data = new_mesh", adapter)
        self.assertIn("set_active_source(scene, source_snapshot(source))", adapter)
        self.assertIn("model.children.unlink(collection)", adapter)
        self.assertIn("candidates.children.link(collection)", adapter)
        self.assertIn("collection.hide_viewport = True", adapter)
        self.assertIn('bl_idname = "smrn.confirm_surface_replacement"', operators)
        self.assertIn('text="细化平滑"', panel)
        self.assertIn('text="一键平整"', panel)
        self.assertIn('text="0.50 = 旧版最高 · 1.00 = 强平滑"', panel)
        self.assertIn('max=1.0', addon)
        self.assertIn('smoothing_iterations = 2 + int(math.ceil(', adapter)
        self.assertIn('range(smoothing_iterations)', adapter)
        self.assertIn('"smoothing_iterations": smoothing_iterations', adapter)
        self.assertIn('"smrn_surface_height_mode"', panel)
        self.assertIn('"smrn_surface_normal_mode"', panel)
        self.assertIn('"flatten": "确认平整并清除标记"', panel)
        self.assertIn('"smooth": "确认平滑并清除标记"', panel)
        self.assertIn('bl_idname = "smrn.accept_current_surface"', operators)
        self.assertIn('self.report({"INFO"}, message)', operators)
        self.assertIn('text="确认当前效果并清除标记"', panel)
        self.assertIn('confirm_row.enabled = bool(counts[TARGET_ROLE] or counts[EXCLUDE_ROLE])', panel)
        self.assertIn("def _restore_normal_selection(context, source=None):", operators)
        self.assertIn("_restore_normal_selection(context, source)", operators)
        self.assertIn("if owns_token:", operators)
        self.assertIn("普通选择已恢复", operators)
        self.assertTrue((ROOT / "scripts" / "live_surface_confirm_ui_test.py").is_file())
        self.assertIn('mode == "flatten"', adapter)
        self.assertIn("local_region_robust_center_pca_per_feature_component", adapter)
        self.assertIn("def _region_face_components", adapter)
        self.assertIn('"flipped_faces"', adapter)
        self.assertIn('"degenerate_faces"', adapter)
        self.assertIn("def _candidate_request_signature", adapter)
        self.assertIn("def _matching_existing_candidate", adapter)
        self.assertIn('report["reused_existing"] = True', adapter)
        self.assertIn('"request_signature": request_signature', adapter)
        self.assertIn("已保留上一版候选", operators)
        self.assertIn("无需重复生成", operators)
        self.assertTrue((ROOT / "scripts" / "live_surface_repeat_click_test.py").is_file())


if __name__ == "__main__":
    unittest.main()
