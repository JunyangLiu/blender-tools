"""Read-only acceptance/archive/view audit after the live confirmation."""

import json
from pathlib import Path

import bpy
from semantic_mesh_marker_next.storage import load_all_marks


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
accepted = sorted(
    (
        obj for obj in bpy.data.objects
        if bool(obj.get("smrn_accepted", False))
        and obj.name.startswith("SMRN_ROTATIONAL_ACCEPTED_")
    ),
    key=lambda obj: obj.name,
)
if source is None or not accepted:
    raise RuntimeError("Accepted rotational ring or source is missing")
ring = accepted[-1]
marks = load_all_marks(scene)

window = bpy.context.window
area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
region_3d = area.spaces.active.region_3d
archive_dir = Path(bpy.data.filepath).parent / "archives" / "accepted_rotational_ring"
archives = sorted(archive_dir.glob("*_ring_accepted_*.blend"))
checkpoints = sorted(archive_dir.glob("*_before_ring_accept_*.blend"))

output = Path(r"C:\codex_auto\semantic-mesh-restorer-next\artifacts\rotational_ring_accepted_normal_view_v0613.png")
output.parent.mkdir(parents=True, exist_ok=True)
with bpy.context.temp_override(window=window, area=area):
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
    bpy.ops.screen.screenshot(filepath=str(output))

print("SMRN_ACCEPTED_RING_AUDIT=" + json.dumps({
    "accepted_object": ring.name,
    "accepted": bool(ring.get("smrn_accepted", False)),
    "accepted_collection_roles": [
        str(collection.get("smrn_collection_role", ""))
        for collection in ring.users_collection
    ],
    "working_candidate_pointer": str(scene.get("smrn_rotational_candidate_name", "")),
    "source_visible": source.visible_get(view_layer=bpy.context.view_layer),
    "accepted_visible": ring.visible_get(view_layer=bpy.context.view_layer),
    "remaining_target_marks": sum(1 for item in marks if item.role == "TARGET"),
    "remaining_exclude_marks": sum(1 for item in marks if item.role == "EXCLUDE"),
    "current_blend": bpy.data.filepath,
    "latest_checkpoint": str(checkpoints[-1]) if checkpoints else None,
    "latest_archive": str(archives[-1]) if archives else None,
    "normal_view_screenshot": str(output),
    "view_perspective": region_3d.view_perspective,
    "view_distance": region_3d.view_distance,
}, ensure_ascii=False, separators=(",", ":")))
