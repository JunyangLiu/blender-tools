"""Read-only diagnostics for the current handle marks and rotational candidate."""

import json

import bpy
from semantic_mesh_marker_next.handle_fit import fit_handle


scene = bpy.context.scene
document = json.loads(str(scene.get("smrn_document_json", "{}") or "{}"))
records = []
for key in document.get("chunks", []):
    payload = json.loads(str(scene.get(key, "{}") or "{}"))
    records.extend(payload.get("records", []))

task_id = document.get("active_task_id", "task-0001")
marks = []
for item in records:
    if item.get("task_id", "task-0001") != task_id:
        continue
    anchor = item.get("anchor", item)
    hit_name = item.get("hit_object_name", "")
    source_name = item.get("source_object_name", "")
    hit = bpy.data.objects.get(hit_name)
    source = bpy.data.objects.get(source_name)
    marks.append({
        "id": int(item.get("id", -1)),
        "role": item.get("role"),
        "hit": hit_name,
        "source": source_name,
        "face": int(anchor.get("face_index", -1)),
        "world": [round(float(value), 6) for value in anchor.get("world_location", ())],
        "hit_exists": bool(hit and hit.type == "MESH"),
        "source_exists": bool(source and source.type == "MESH"),
        "hit_collections": sorted(owner.name for owner in hit.users_collection) if hit else [],
        "source_fingerprint": str(anchor.get("source_fingerprint", ""))[:12],
    })

candidate_name = str(scene.get("smrn_rotational_candidate_name", ""))
candidate = bpy.data.objects.get(candidate_name)
candidate_report = {}
if candidate is not None:
    candidate_report = json.loads(str(candidate.get("smrn_rotational_report_json", "{}") or "{}"))

active_source_name = str(scene.get("smrn_source_name", ""))
active_source = bpy.data.objects.get(active_source_name)
target_marks = [item for item in marks if item["role"] == "target"]
fit = fit_handle(
    [item["world"] for item in target_marks],
    [
        next(
            record.get("anchor", record).get("world_normal", (0.0, 0.0, 1.0))
            for record in records if int(record.get("id", -1)) == item["id"]
        )
        for item in target_marks
    ],
)
rotational_candidates = []
for obj in bpy.data.objects:
    if obj.type != "MESH" or not obj.name.startswith("SMRN_ROTATIONAL_CANDIDATE_"):
        continue
    report = json.loads(str(obj.get("smrn_rotational_report_json", "{}") or "{}"))
    rotational_candidates.append({
        "name": obj.name,
        "visible": obj.visible_get(view_layer=bpy.context.view_layer),
        "domain": report.get("domain"),
        "source": obj.get("smrn_source_name", ""),
    })
record_overlay_names = {item.get("overlay_object_name", "") for item in records}
next_overlays = sorted(
    obj.name for obj in bpy.data.objects if obj.name.startswith("SMRN_MARK_")
)
legacy_mark_like = sorted(
    obj.name for obj in bpy.data.objects
    if obj.name.startswith(("SMR_VISIBLE_MARK_", "SMR_CONSTRAINT_"))
)
print("SMRN_HANDLE_ROUNDING_ISSUE=" + json.dumps({
    "blend": bpy.data.filepath,
    "task_id": task_id,
    "active_source": active_source_name,
    "active_source_topology": (
        [len(active_source.data.vertices), len(active_source.data.edges), len(active_source.data.polygons)]
        if active_source is not None and active_source.type == "MESH" else None
    ),
    "marks": marks,
    "unconstrained_handle_fit": fit.to_dict(),
    "rotational_setting_thickness": float(scene.smrn_rotational_thickness),
    "rotational_candidate": candidate_name,
    "rotational_domain": candidate_report.get("domain"),
    "rotational_source_unchanged": candidate_report.get("source_unchanged"),
    "rotational_candidates": rotational_candidates,
    "record_overlays": sorted(record_overlay_names),
    "next_overlay_objects": next_overlays,
    "orphan_next_overlays": sorted(set(next_overlays) - record_overlay_names),
    "legacy_marker_object_count": len(legacy_mark_like),
    "visible_mesh_count": sum(
        1 for obj in bpy.context.view_layer.objects
        if obj.type == "MESH" and obj.visible_get(view_layer=bpy.context.view_layer)
    ),
}, ensure_ascii=False, separators=(",", ":")))
