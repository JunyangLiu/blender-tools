"""Reload v0.4 in the isolated Maus Blender and analyze current marks."""

import importlib
import json
import sys

import bpy


ROOT = r"C:\codex_auto\semantic-mesh-restorer-next\blender_addon"
PACKAGE = "semantic_mesh_marker_next"

old = sys.modules.get(PACKAGE)
if old is not None:
    try:
        old.unregister()
    except Exception as error:
        print("SMRN_OLD_UNREGISTER_WARNING=" + repr(error))
for name in tuple(sys.modules):
    if name == PACKAGE or name.startswith(PACKAGE + "."):
        del sys.modules[name]
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
addon = importlib.import_module(PACKAGE)
addon.register()

from semantic_mesh_marker_next.handle_blender import analyze_scene, store_analysis

scene = bpy.context.scene
fit, source, targets, supports, report = analyze_scene(scene)
report.update({"status": fit.status, "fit": fit.to_dict()})
store_analysis(scene, report)
scene.smrn_handle_summary = (
    f"{fit.path_kind} · 置信度 {fit.confidence:.2f} · 安装角已锁定"
    if fit.status == "candidate_ready" else f"证据不足：{fit.reason}"
)
print("SMRN_HANDLE_LIVE_ANALYSIS=" + json.dumps({
    "addon_version": list(addon.bl_info["version"]),
    "blend": bpy.data.filepath,
    "source": source.name if source else None,
    "source_topology": ([len(source.data.vertices), len(source.data.edges), len(source.data.polygons)]
                        if source else None),
    "source_visible": source.visible_get() if source else None,
    "visible_mesh_count": sum(1 for obj in bpy.context.view_layer.objects
                              if obj.type == "MESH" and obj.visible_get()),
    "targets": len(targets), "supports": len(supports),
    "fit": fit.to_dict(),
}, ensure_ascii=False, separators=(",", ":")))
