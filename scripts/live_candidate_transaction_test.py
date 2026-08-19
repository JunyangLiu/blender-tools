"""Prove that a late rotational build failure preserves the working candidate."""

import json

import bpy
import semantic_mesh_marker_next.rotational_blender as rotational


scene = bpy.context.scene
before_pointer = str(scene.get("smrn_rotational_candidate_name", ""))
before_names = sorted(
    obj.name for obj in bpy.data.objects if obj.name.startswith(rotational.CANDIDATE_PREFIX)
)
before_object = bpy.data.objects.get(before_pointer)
original_keep_visible = rotational.keep_model_visible


def forced_failure(_scene, _required_objects=()):
    raise RuntimeError("controlled transaction test")


error = None
try:
    rotational.keep_model_visible = forced_failure
    rotational.build_scene_candidate(scene)
except RuntimeError as caught:
    error = str(caught)
finally:
    rotational.keep_model_visible = original_keep_visible

after_pointer = str(scene.get("smrn_rotational_candidate_name", ""))
after_names = sorted(
    obj.name for obj in bpy.data.objects if obj.name.startswith(rotational.CANDIDATE_PREFIX)
)
print("SMRN_TRANSACTION_TEST=" + json.dumps({
    "controlled_error": error,
    "pointer_preserved": after_pointer == before_pointer,
    "object_preserved": bpy.data.objects.get(before_pointer) is before_object,
    "no_partial_candidate": after_names == before_names,
    "candidate_names": after_names,
}, ensure_ascii=False, separators=(",", ":")))
