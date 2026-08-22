"""Exercise exact flattening on one marked cell surrounded by unmarked cells."""

import json
import math
import traceback

import bpy
from mathutils import Vector

from semantic_mesh_marker_next import surface_rebuild_blender as rebuild


mesh = bpy.data.meshes.new("SMRN_QA_FLATTEN_BOUNDARY_MESH")
vertices = []
for row in range(4):
    for column in range(4):
        height = 0.0
        if row in (1, 2) and column in (1, 2):
            height = (row - 1) * 0.45 + (column - 1) * 0.20
        vertices.append((float(column), float(row), height))
faces = []
for row in range(3):
    for column in range(3):
        first = row * 4 + column
        faces.append((first, first + 1, first + 5, first + 4))
mesh.from_pydata(vertices, [], faces)
mesh.update()
source = bpy.data.objects.new("SMRN_QA_FLATTEN_BOUNDARY_SOURCE", mesh)
bpy.context.scene.collection.objects.link(source)
before = [tuple(vertex.co) for vertex in source.data.vertices]
working = None
try:
    working, _preview_vertices, _preview_faces, report = rebuild._rebuild_working_mesh(
        source,
        [4],
        [],
        0,
        0.0,
        math.radians(35.0),
        "flatten",
        "MEDIAN",
        Vector((0.0, 0.0, 1.0)),
        "AUTO",
        None,
        None,
    )
    after_source = [tuple(vertex.co) for vertex in source.data.vertices]
    isolation = report.get("flatten_boundary_isolation") or {}
    print("SMRN_FLATTEN_BOUNDARY_ISOLATION_V0624=" + json.dumps({
        "passed": report.get("passed"),
        "flipped_faces": report.get("flipped_faces"),
        "degenerate_faces": report.get("degenerate_faces"),
        "invalid_edges_before": report.get("before_topology", {}).get("invalid_edges"),
        "invalid_edges_after": report.get("after_topology", {}).get("invalid_edges"),
        "boundary_components_before": report.get("before_topology", {}).get("boundary_components"),
        "boundary_components_after": report.get("after_topology", {}).get("boundary_components"),
        "source_unchanged": before == after_source,
        "isolation": isolation,
    }, ensure_ascii=False, separators=(",", ":")))
except Exception:
    print("SMRN_FLATTEN_BOUNDARY_ISOLATION_ERROR=" + traceback.format_exc())
finally:
    if working is not None:
        rebuild._remove_object(working)
    rebuild._remove_object(source)
