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
            id=number,
            role=role,
            overlay_object_name=f"SMRN_MARK_{number:04d}_{role.upper()}",
            hit_object_name="Hull",
            source_object_name="Tank",
            face_index=42,
            world_location=(1.0, 2.0, 3.0),
            world_normal=(0.0, 0.0, 1.0),
            screen_offset_px=4.5,
            surface_offset=0.002,
        )

    def test_round_trip_preserves_traceability_fields(self):
        source = [self.make_record()]
        restored = records.loads_marks(records.dumps_marks(source))
        self.assertEqual(restored, source)
        payload = json.loads(records.dumps_marks(source))[0]
        for field in (
            "hit_object_name",
            "source_object_name",
            "face_index",
            "world_location",
            "world_normal",
            "screen_offset_px",
            "surface_offset",
        ):
            self.assertIn(field, payload)

    def test_next_id_is_monotonic_after_undo_gaps(self):
        existing = [self.make_record(2), self.make_record(7, "exclude")]
        self.assertEqual(records.next_mark_id(existing), 8)

    def test_role_counts(self):
        values = [self.make_record(1), self.make_record(2, "exclude"), self.make_record(3)]
        self.assertEqual(records.role_counts(values), {"target": 2, "exclude": 1})

    def test_rejects_invalid_role_and_vector(self):
        with self.assertRaises(ValueError):
            self.make_record(role="maybe")
        payload = self.make_record().to_dict()
        payload["world_normal"] = [0, 1]
        with self.assertRaises(ValueError):
            records.MarkRecord.from_mapping(payload)


if __name__ == "__main__":
    unittest.main()

