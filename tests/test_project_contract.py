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


if __name__ == "__main__":
    unittest.main()
