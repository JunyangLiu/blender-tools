"""Diagnose one current flatten request without checkpointing or changing source."""

import json
import math

import bmesh
import bpy

from semantic_mesh_marker_next import surface_rebuild_blender as rebuild


scene = bpy.context.scene
source, targets, excludes, source_before = rebuild._source_and_records(scene)
height_mode = str(getattr(scene, "smrn_surface_height_mode", "MEDIAN"))
normal_mode = str(getattr(scene, "smrn_surface_normal_mode", "AUTO"))
normal_hint = rebuild._normal_hint_from_records(source, targets, excludes, normal_mode)
height_reference_points = rebuild._height_reference_from_records(
    source, excludes, height_mode
)
hard_angle = math.radians(float(scene.smrn_surface_hard_angle))

probe = bmesh.new()
probe.from_mesh(source.data)
selected, growth = rebuild._grow_marked_region(
    probe, source, targets, excludes, hard_angle
)
excluded = set(rebuild._seed_face_indices(
    [record for record in excludes if record.hit_object_name == source.name],
    len(probe.faces),
))
probe.free()

working = None
try:
    working, _vertices, _faces, topology = rebuild._rebuild_working_mesh(
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
        height_reference_points,
        None,
    )
    flipped_geometry = []
    for detail in topology.get("flipped_face_details", []):
        face_index = int(detail["face_index"])
        source_face = source.data.polygons[face_index]
        working_face = working.data.polygons[face_index]
        working_vertex_set = set(working_face.vertices)
        adjacent_indices = []
        for candidate_face in working.data.polygons:
            if candidate_face.index == face_index:
                continue
            if len(working_vertex_set.intersection(candidate_face.vertices)) >= 2:
                adjacent_indices.append(candidate_face.index)
        after_neighbor_dots = [
            float(working_face.normal.dot(working.data.polygons[index].normal))
            for index in adjacent_indices
        ]
        flipped_geometry.append({
            "face_index": face_index,
            "vertices": list(source_face.vertices),
            "green_vertices": [
                int(index) for index in source_face.vertices
                if any(
                    int(index) in source.data.polygons[selected_index].vertices
                    for selected_index in selected
                )
            ],
            "before_coordinates": [
                list(source.data.vertices[index].co) for index in source_face.vertices
            ],
            "after_coordinates": [
                list(working.data.vertices[index].co) for index in working_face.vertices
            ],
            "before_normal": list(source_face.normal),
            "after_normal": list(working_face.normal),
            "adjacent_faces": adjacent_indices,
            "after_neighbor_normal_dots": after_neighbor_dots,
        })
    result = {
        "source": source.name,
        "source_unchanged": source_before["fingerprint"] == rebuild.source_snapshot(source)["fingerprint"],
        "green_marks": len(targets),
        "red_marks": len(excludes),
        "selected_faces": len(selected),
        "growth": growth,
        "passed": topology.get("passed"),
        "quality_gates": topology.get("quality_gates"),
        "planarity": topology.get("planarity_qa"),
        "flipped_faces": topology.get("flipped_faces"),
        "flipped_face_details": topology.get("flipped_face_details"),
        "flipped_face_geometry": flipped_geometry,
        "degenerate_faces": topology.get("degenerate_faces"),
        "degenerate_face_details": topology.get("degenerate_face_details"),
        "whole_vehicle_search": False,
    }
    print("SMRN_CURRENT_FLATTEN_FAILURE_V0620=" + json.dumps(
        result, ensure_ascii=False, separators=(",", ":")
    ))
finally:
    if working is not None:
        rebuild._remove_object(working)
