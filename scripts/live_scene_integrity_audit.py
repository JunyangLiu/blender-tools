"""Read-only audit for scene roots and stale Blender object references."""

import json

import bpy

from semantic_mesh_marker_next.constants import (
    CANDIDATE_COLLECTION_NAME,
    MODEL_COLLECTION_NAME,
    SOURCE_NAME_KEY,
)
from semantic_mesh_marker_next.scene_state import load_marks


scene = bpy.context.scene
model = bpy.data.collections.get(MODEL_COLLECTION_NAME)
candidates = bpy.data.collections.get(CANDIDATE_COLLECTION_NAME)


def object_entry(obj):
    if obj is None:
        return {"valid": False, "name": None}
    try:
        return {
            "valid": True,
            "name": obj.name,
            "type": obj.type,
            "hidden_viewport": bool(obj.hide_viewport),
            "hidden_runtime": bool(obj.hide_get()),
        }
    except ReferenceError as error:
        return {"valid": False, "name": None, "error": repr(error)}


records = load_marks(scene)
source_name = str(scene.get(SOURCE_NAME_KEY, ""))
source = bpy.data.objects.get(source_name)
candidate_names = [
    obj.name for obj in bpy.data.objects
    if obj.name.startswith(("SMRN_ROTATIONAL_CANDIDATE_", "SMRN_HANDLE_CANDIDATE_"))
]
payload = {
    "blend": bpy.data.filepath,
    "source_name": source_name,
    "source_exists": source is not None,
    "source_topology": (
        [len(source.data.vertices), len(source.data.edges), len(source.data.polygons)]
        if source is not None and source.type == "MESH" else None
    ),
    "source_visible": source.visible_get() if source is not None else None,
    "marks": {
        "target": sum(item.role == "target" for item in records),
        "exclude": sum(item.role == "exclude" for item in records),
    },
    "scene_candidate_pointer": str(scene.get("smrn_rotational_candidate_name", "")),
    "candidate_objects": candidate_names,
    "model_direct": [object_entry(obj) for obj in model.objects] if model else None,
    "model_recursive": [object_entry(obj) for obj in model.all_objects] if model else None,
    "candidate_collection": [object_entry(obj) for obj in candidates.all_objects] if candidates else None,
}
print("SMRN_SCENE_INTEGRITY=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
