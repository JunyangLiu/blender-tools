import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).parents[1] / "blender_addon" / "semantic_mesh_marker_next"
package = types.ModuleType("smrn_test_package")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package


def load(name):
    spec = importlib.util.spec_from_file_location(f"{package.__name__}.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load("constants")
records = load("records")
storage = load("storage")


def mark(number, location=None, face_index=None):
    location = location or (float(number), 0.0, 0.0)
    return records.MarkRecord(
        id=number, role="target", overlay_object_name=f"mark-{number}",
        hit_object_name="Hull", source_object_name="Tank", face_index=number if face_index is None else face_index,
        world_location=location, world_normal=(0, 0, 1), screen_offset_px=0,
        surface_offset=0, local_location=location, source_fingerprint="mesh-1",
    )


def exclude_mark(number, location=None, face_index=None):
    return records.MarkRecord(
        **{
            **mark(number, location, face_index).__dict__,
            "role": "exclude",
            "overlay_object_name": f"exclude-{number}",
        }
    )


class StorageTests(unittest.TestCase):
    def test_legacy_migration_is_non_destructive(self):
        scene = {"smrn_marks_json": json.dumps([{
            "id": 3, "role": "target", "overlay_object_name": "old-3",
            "hit_object_name": "Hull", "source_object_name": "Tank", "face_index": 9,
            "world_location": [1, 2, 3], "world_normal": [0, 0, 1],
            "screen_offset_px": 0, "surface_offset": 0,
        }])}
        summary = storage.document_summary(scene)
        self.assertIn("smrn_marks_json", scene)
        self.assertEqual(summary["mark_count"], 1)
        self.assertEqual(storage.next_id(scene), 4)

    def test_large_collection_is_chunked_and_summary_is_small(self):
        scene = {}
        for number in range(1, 302):
            self.assertTrue(storage.append_mark(scene, mark(number)))
        summary = storage.document_summary(scene)
        self.assertEqual(summary["mark_count"], 301)
        self.assertEqual(summary["chunk_count"], 3)
        document = json.loads(scene[storage.DOCUMENT_KEY])
        self.assertNotIn("records", document)
        self.assertNotIn("surface_keys", document["tasks"]["task-0001"])
        self.assertTrue(all(len(records.loads_marks(scene[key])) <= 128 for key in document["chunks"]))

    def test_duplicate_rejected_and_ids_remain_monotonic_after_undo(self):
        scene = {}
        self.assertTrue(storage.append_mark(scene, mark(1)))
        self.assertFalse(storage.append_mark(scene, mark(2, (1.0, 0.0, 0.0), face_index=1)))
        self.assertEqual(storage.pop_last_mark(scene).id, 1)
        self.assertEqual(storage.next_id(scene), 2)

    def test_clear_returns_removed_records(self):
        scene = {}
        storage.append_mark(scene, mark(1))
        storage.append_mark(scene, mark(2))
        removed = storage.clear_task_marks(scene)
        self.assertEqual([item.id for item in removed], [1, 2])
        self.assertEqual(storage.document_summary(scene)["mark_count"], 0)

    def test_brush_batch_is_one_document_transaction_and_keeps_duplicates_out(self):
        scene = {}
        accepted = storage.append_marks(scene, [
            mark(1),
            mark(2),
            mark(3, (1.0, 0.0, 0.0), face_index=1),
        ])
        self.assertEqual([item.id for item in accepted], [1, 2])
        summary = storage.document_summary(scene)
        self.assertEqual(summary["mark_count"], 2)
        # One initial document creation plus one batch commit.
        self.assertEqual(summary["revision"], 2)

    def test_replace_task_marks_supports_role_specific_eraser(self):
        scene = {}
        target = mark(1)
        excluded = exclude_mark(2, (2.0, 0.0, 0.0), face_index=2)
        storage.append_marks(scene, [target, excluded])
        storage.replace_task_marks(scene, "task-0001", [excluded])
        remaining = storage.load_all_marks(scene, "task-0001")
        self.assertEqual([(item.id, item.role) for item in remaining], [(2, "exclude")])
        summary = storage.document_summary(scene)
        self.assertEqual(summary["mark_count"], 1)
        self.assertEqual(summary["role_counts"]["target"], 0)
        self.assertEqual(summary["role_counts"]["exclude"], 1)


if __name__ == "__main__":
    unittest.main()
