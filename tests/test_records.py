import importlib.util
import json
from pathlib import Path
import sys
import unittest

MODULE_PATH = Path(__file__).parents[1] / "blender_addon" / "semantic_mesh_marker_next" / "records.py"
SPEC = importlib.util.spec_from_file_location("smrn_records", MODULE_PATH)
records = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = records
SPEC.loader.exec_module(records)


class MarkRecordTests(unittest.TestCase):
    def make_record(self, number=1, role="target"):
        return records.MarkRecord(
            id=number, role=role, overlay_object_name=f"SMRN_MARK_{number:04d}_{role.upper()}",
            hit_object_name="Hull", source_object_name="Tank", face_index=42,
            world_location=(1.0, 2.0, 3.0), world_normal=(0.0, 0.0, 1.0),
            screen_offset_px=4.5, surface_offset=0.002,
            local_location=(0.1, 0.2, 0.3), source_fingerprint="mesh-abc",
        )

    def test_v2_round_trip_preserves_traceability(self):
        source = [self.make_record()]
        restored = records.loads_marks(records.dumps_marks(source))
        self.assertEqual(restored, source)
        payload = json.loads(records.dumps_marks(source))
        self.assertEqual(payload["schema"], records.SCHEMA_NAME)
        self.assertEqual(payload["version"], 2)
        self.assertEqual(payload["records"][0]["anchor"]["local_location"], [0.1, 0.2, 0.3])

    def test_v1_list_migrates_without_losing_fields(self):
        legacy = [{
            "id": 7, "role": "exclude", "overlay_object_name": "old",
            "hit_object_name": "Hull", "source_object_name": "Tank", "face_index": 12,
            "world_location": [1, 2, 3], "world_normal": [0, 0, 1],
            "screen_offset_px": 2, "surface_offset": 0.01, "schema_version": 1,
        }]
        restored = records.loads_marks(json.dumps(legacy))[0]
        self.assertEqual(restored.id, 7)
        self.assertEqual(restored.schema_version, 2)
        self.assertEqual(restored.anchor.face_index, 12)

    def test_stable_key_uses_location_not_face_alone(self):
        first = self.make_record()
        changed = first.to_dict()
        changed["anchor"]["local_location"] = [0.1, 0.2, 0.4]
        self.assertNotEqual(first.anchor.stable_key("Tank"),
                            records.MarkRecord.from_mapping(changed).anchor.stable_key("Tank"))

    def test_roles_allow_core_and_namespaced_extensions(self):
        self.make_record(role="boundary")
        self.make_record(role="x.vendor.custom")
        with self.assertRaises(ValueError):
            self.make_record(role="maybe")


if __name__ == "__main__":
    unittest.main()
