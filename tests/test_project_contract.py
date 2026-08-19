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

    def test_legacy_helpers_are_excluded_from_raycast(self):
        scene_state = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "scene_state.py").read_text(encoding="utf-8")
        self.assertIn('obj.get("smr_annotation_only", False)', scene_state)
        self.assertIn('obj.get("smr_source_name", "")', scene_state)

    def test_panel_uses_lightweight_summary(self):
        panel = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "panel.py").read_text(encoding="utf-8")
        self.assertIn("marks_summary(scene)", panel)
        self.assertNotIn("load_marks(scene)", panel)

    def test_chunked_versioned_storage_exists(self):
        storage = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "storage.py").read_text(encoding="utf-8")
        self.assertIn('DOCUMENT_KEY = "smrn_document_json"', storage)
        self.assertIn("CHUNK_SIZE = 128", storage)

    def test_rotational_feature_stays_non_destructive(self):
        adapter = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "rotational_blender.py").read_text(encoding="utf-8")
        self.assertIn('CANDIDATE_PREFIX = "SMRN_ROTATIONAL_CANDIDATE_"', adapter)
        self.assertIn("_commit_candidate(scene, obj)", adapter)
        self.assertNotIn("remove_last_candidate(scene)\n    _model, candidates", adapter)
        self.assertIn("source_unchanged", (ROOT / "scripts" / "live_build_gate_test.py").read_text(encoding="utf-8"))
        self.assertNotIn("bpy.ops.object.delete", adapter)

    def test_visibility_guard_skips_stale_recursive_objects(self):
        scene_state = (ROOT / "blender_addon" / "semantic_mesh_marker_next" / "scene_state.py").read_text(encoding="utf-8")
        visibility = scene_state.split("def keep_model_visible", 1)[1].split("def set_helpers_hidden", 1)[0]
        self.assertIn("list(model.all_objects)", visibility)
        self.assertIn("if obj is None", visibility)
        self.assertIn("required_objects", visibility)
        self.assertIn("except (AttributeError, ReferenceError)", visibility)

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
        self.assertIn('"uncovered": uncovered', adapter)
        self.assertTrue((ROOT / "scripts" / "live_handle_build_gate_test.py").is_file())


if __name__ == "__main__":
    unittest.main()
