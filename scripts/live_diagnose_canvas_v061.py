"""Run the current canvas request without committing a scene candidate."""

import importlib
import json

import bmesh
import bpy


surface = importlib.import_module("semantic_mesh_marker_next.surface_rebuild_blender")
scene = bpy.context.scene
source, targets, excludes, snapshot = surface._source_and_records(scene)
hard_angle = __import__("math").radians(float(scene.smrn_surface_hard_angle))
probe = bmesh.new()
probe.from_mesh(source.data)
selected, growth = surface._grow_marked_region(probe, source, targets, excludes, hard_angle)
excluded = set(surface._seed_face_indices(
    [record for record in excludes if record.hit_object_name == source.name], len(probe.faces)
))
probe.free()

working = None
try:
    working, _vertices, _faces, report = surface._rebuild_working_mesh(
        source,
        sorted(selected),
        sorted(excluded),
        int(scene.smrn_surface_subdivision_level),
        float(scene.smrn_canvas_wave_strength),
        hard_angle,
        "canvas",
    )
    print("SMRN_CANVAS_DIAG=" + json.dumps({
        "source": source.name,
        "source_fingerprint": snapshot["fingerprint"],
        "target_marks": len(targets),
        "exclude_marks": len(excludes),
        "growth": growth,
        "report": report,
    }, ensure_ascii=False, separators=(",", ":")))
finally:
    if working is not None:
        mesh = working.data
        bpy.data.objects.remove(working, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
