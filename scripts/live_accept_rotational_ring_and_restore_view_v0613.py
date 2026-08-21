"""Archive the accepted rotational ring and restore a normal full-model view."""

import json
from datetime import datetime, timezone
from pathlib import Path

import bpy
from mathutils import Quaternion
from semantic_mesh_marker_next.storage import load_all_marks


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
candidate_name = str(scene.get("smrn_rotational_candidate_name", ""))
candidate = bpy.data.objects.get(candidate_name)
if source is None or candidate is None:
    raise RuntimeError("Missing the current source or rotational candidate")
if not bpy.data.filepath:
    raise RuntimeError("The current Blender project has not been saved")

report = json.loads(str(candidate.get("smrn_rotational_report_json", "{}")))
if report.get("status") != "candidate_ready":
    raise RuntimeError("The rotational candidate is not ready for acceptance")
if not report.get("source_unchanged", False):
    raise RuntimeError("Source mesh integrity gate did not pass")
if not report.get("coverage_qa", {}).get("passed", False):
    raise RuntimeError("Coverage QA did not pass")
if not report.get("topology_qa", {}).get("passed", False):
    raise RuntimeError("Topology QA did not pass")

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
current_path = Path(bpy.data.filepath)
archive_dir = current_path.parent / "archives" / "accepted_rotational_ring"
archive_dir.mkdir(parents=True, exist_ok=True)
checkpoint_path = archive_dir / f"{current_path.stem}_before_ring_accept_{stamp}.blend"
accepted_path = archive_dir / f"{current_path.stem}_ring_accepted_{stamp}.blend"

# Recoverable source checkpoint before the acceptance transaction.
bpy.ops.wm.save_as_mainfile(filepath=str(checkpoint_path), copy=True, check_existing=False)

result = set(bpy.ops.smrn.confirm_candidate(candidate_kind="rotational"))
if result != {"FINISHED"}:
    raise RuntimeError(f"Rotational acceptance failed: {sorted(result)}")

# The object reference remains valid after the operator renames and archives it.
accepted = candidate
source.hide_set(False)
source.hide_viewport = False
source.hide_render = False
accepted.hide_set(False)
accepted.hide_viewport = False
accepted.hide_render = False
accepted.show_in_front = False
accepted.show_wire = False

# Restore a conventional three-quarter perspective framed on the complete source.
window = bpy.context.window
area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
region = next(region for region in area.regions if region.type == "WINDOW")
space = area.spaces.active
region_3d = space.region_3d
region_3d.view_perspective = "PERSP"
region_3d.view_rotation = Quaternion((0.865, 0.244, -0.424, -0.113)).normalized()

if bpy.context.mode != "OBJECT":
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.object.mode_set(mode="OBJECT")
for obj in tuple(bpy.context.selected_objects):
    obj.select_set(False)
source.select_set(True)
bpy.context.view_layer.objects.active = source
with bpy.context.temp_override(window=window, area=area, region=region):
    bpy.ops.view3d.view_selected(use_all_regions=False)
region_3d.view_distance *= 1.12

bpy.context.view_layer.update()
bpy.ops.wm.save_mainfile()
bpy.ops.wm.save_as_mainfile(filepath=str(accepted_path), copy=True, check_existing=False)
bpy.ops.wm.save_mainfile()
remaining_marks = load_all_marks(scene)

print("SMRN_ROTATIONAL_RING_ACCEPTED=" + json.dumps({
    "accepted_object": accepted.name,
    "accepted": bool(accepted.get("smrn_accepted", False)),
    "source": source.name,
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "accepted_visible": accepted.visible_get(view_layer=bpy.context.view_layer),
    "checkpoint": str(checkpoint_path),
    "archive": str(accepted_path),
    "current_blend": bpy.data.filepath,
    "remaining_target_marks": sum(
        1 for item in remaining_marks if item.role == "TARGET"
    ),
    "remaining_exclude_marks": sum(
        1 for item in remaining_marks if item.role == "EXCLUDE"
    ),
    "view_perspective": region_3d.view_perspective,
    "view_distance": region_3d.view_distance,
}, ensure_ascii=False, separators=(",", ":")))
