"""Exercise smooth and flatten reconstruction on a disposable local mesh."""

import importlib
import json
import sys
import traceback

import bpy
from mathutils import Vector


ROOT = r"C:\codex_auto\semantic-mesh-restorer-next\blender_addon"
PACKAGE = "semantic_mesh_marker_next"

old = sys.modules.get(PACKAGE)
if old is not None:
    try:
        old.unregister()
    except Exception:
        pass
for name in tuple(sys.modules):
    if name == PACKAGE or name.startswith(PACKAGE + "."):
        del sys.modules[name]
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
addon = importlib.import_module(PACKAGE)
addon.register()

from semantic_mesh_marker_next.surface_rebuild_blender import _rebuild_working_mesh, _remove_object


for stale in list(bpy.data.objects):
    if stale.name.startswith("SMRN_SURFACE_WORKING_FULL_SMRN_SYNTHETIC_SOURCE"):
        _remove_object(stale)

mesh = bpy.data.meshes.new("SMRN_SYNTHETIC_SOURCE_MESH")
vertices = [
    (-1.0, -1.0, 0.0), (0.0, -1.0, 0.05), (1.0, -1.0, 0.0),
    (-1.0, 0.0, 0.03), (0.0, 0.0, 0.28), (1.0, 0.0, -0.04),
    (-1.0, 1.0, 0.0), (0.0, 1.0, 0.02), (1.0, 1.0, 0.0),
]
faces = [(0, 1, 4, 3), (1, 2, 5, 4), (3, 4, 7, 6), (4, 5, 8, 7)]
mesh.from_pydata(vertices, [], faces)
mesh.update(calc_edges=True)
source = bpy.data.objects.new("SMRN_SYNTHETIC_SOURCE", mesh)

results = {}
created = []
try:
    for mode in ("smooth", "flatten"):
        try:
            working, preview_vertices, preview_faces, report = _rebuild_working_mesh(
                source, [0, 1, 2, 3], [], 1, 0.22, 0.9, mode
            )
        except Exception:
            results[mode] = {"traceback": traceback.format_exc()}
            break
        created.append(working)
        results[mode] = {
            "passed": report["passed"],
            "faces": len(preview_faces),
            "vertices": len(preview_vertices),
            "planarity": report["planarity_qa"],
            "topology_before": report["before_topology"],
            "topology_after": report["after_topology"],
            "dihedral_before": report["before_dihedral_p95_degrees"],
            "dihedral_after": report["after_dihedral_p95_degrees"],
        }

    for height_mode in ("LOW", "MEDIAN", "HIGH"):
        working, _preview_vertices, _preview_faces, report = _rebuild_working_mesh(
            source, [0, 1, 2, 3], [], 1, 0.22, 0.9, "flatten",
            height_mode, Vector((0.0, 0.0, 1.0)), "FIRST_TARGET",
        )
        created.append(working)
        component = report["planarity_qa"]["components"][0]
        results["height_" + height_mode.lower()] = {
            "passed": report["passed"],
            "height_mode": component["height_mode"],
            "normal_mode": component["normal_mode"],
            "plane_normal": component["plane_normal_local"],
            "flipped_faces": report["flipped_faces"],
            "degenerate_faces": report["degenerate_faces"],
        }

    # Two disconnected warped plates at different heights reproduce the
    # failure mode of several separately marked recessed strips.  They must
    # never be fitted to one shared plane.
    split_mesh = bpy.data.meshes.new("SMRN_SYNTHETIC_SPLIT_MESH")
    split_vertices = []
    split_faces = []
    for patch_index, base_z in enumerate((0.0, 3.0)):
        offset = len(split_vertices)
        base_x = patch_index * 4.0
        split_vertices.extend([
            (base_x - 1.0, -1.0, base_z), (base_x, -1.0, base_z + 0.04), (base_x + 1.0, -1.0, base_z),
            (base_x - 1.0, 0.0, base_z + 0.03), (base_x, 0.0, base_z + 0.24), (base_x + 1.0, 0.0, base_z - 0.03),
            (base_x - 1.0, 1.0, base_z), (base_x, 1.0, base_z + 0.01), (base_x + 1.0, 1.0, base_z),
        ])
        split_faces.extend([
            (offset + 0, offset + 1, offset + 4, offset + 3),
            (offset + 1, offset + 2, offset + 5, offset + 4),
            (offset + 3, offset + 4, offset + 7, offset + 6),
            (offset + 4, offset + 5, offset + 8, offset + 7),
        ])
    split_mesh.from_pydata(split_vertices, [], split_faces)
    split_mesh.update(calc_edges=True)
    split_source = bpy.data.objects.new("SMRN_SYNTHETIC_SPLIT_SOURCE", split_mesh)
    split_working = None
    try:
        split_working, _vertices, _faces, split_report = _rebuild_working_mesh(
            split_source, list(range(8)), [], 1, 0.22, 0.9, "flatten"
        )
        created.append(split_working)
        results["split_flatten"] = {
            "passed": split_report["passed"],
            "component_count": split_report["planarity_qa"]["component_count"],
            "fitted_component_count": split_report["planarity_qa"]["fitted_component_count"],
            "flipped_faces": split_report["flipped_faces"],
            "degenerate_faces": split_report["degenerate_faces"],
            "max_displacement": split_report["max_actual_displacement"],
            "displacement_limit": split_report["max_allowed_displacement"],
        }
    except Exception:
        results["split_flatten"] = {"traceback": traceback.format_exc()}
    finally:
        bpy.data.objects.remove(split_source, do_unlink=True)
        if split_mesh.users == 0:
            bpy.data.meshes.remove(split_mesh)
finally:
    for obj in created:
        _remove_object(obj)
    bpy.data.objects.remove(source, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)

print("SMRN_SURFACE_SYNTHETIC=" + json.dumps({
    "addon_version": list(addon.bl_info["version"]),
    "results": results,
}, ensure_ascii=False, separators=(",", ":")))
