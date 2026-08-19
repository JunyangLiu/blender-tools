"""Exercise smooth and flatten reconstruction on a disposable local mesh."""

import importlib
import json
import sys
import traceback

import bpy


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
