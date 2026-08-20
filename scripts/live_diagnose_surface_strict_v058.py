"""Read-only diagnosis for a strict-scope flatten rejection."""

import json
import math

import bmesh
import bpy

from semantic_mesh_marker_next.anchors import source_snapshot
from semantic_mesh_marker_next.surface_rebuild_blender import (
    _grow_marked_region,
    _height_reference_from_records,
    _normal_hint_from_records,
    _rebuild_working_mesh,
    _remove_object,
    _seed_face_indices,
    _source_and_records,
)


scene = bpy.context.scene
source, targets, excludes, before = _source_and_records(scene)
hard_angle = math.radians(float(scene.smrn_surface_hard_angle))
height_mode = str(scene.smrn_surface_height_mode)
normal_mode = str(scene.smrn_surface_normal_mode)
normal_hint = _normal_hint_from_records(source, targets, excludes, normal_mode)
height_points = _height_reference_from_records(source, excludes, height_mode)
probe = bmesh.new()
probe.from_mesh(source.data)
selected, growth = _grow_marked_region(probe, source, targets, excludes, hard_angle)
excluded = set(
    _seed_face_indices(
        [record for record in excludes if record.hit_object_name == source.name],
        len(probe.faces),
    )
)
probe.free()

working = None
try:
    working, vertices, faces, topology = _rebuild_working_mesh(
        source,
        sorted(selected),
        sorted(excluded),
        int(scene.smrn_surface_subdivision_level),
        float(scene.smrn_surface_smooth_strength),
        hard_angle,
        "flatten",
        height_mode,
        normal_hint,
        normal_mode,
        height_points,
    )
    result = {
        "source": before,
        "source_after": source_snapshot(source),
        "semantic_region": growth,
        "preview_faces": len(faces),
        "preview_vertices": len(vertices),
        "topology_qa": topology,
    }
finally:
    if working is not None:
        _remove_object(working)

print("SMRN_STRICT_SURFACE_DIAGNOSIS=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
