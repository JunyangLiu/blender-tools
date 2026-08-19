bl_info = {
    "name": "Semantic Mesh Marker Next",
    "author": "Local developer",
    "version": (0, 3, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > 语义标记 Next",
    "description": "Non-destructive target and exclude surface marking",
    "category": "3D View",
}

import bpy

from .operators import CLASSES as OPERATOR_CLASSES
from .panel import CLASSES as PANEL_CLASSES
from .anchors import migrate_scene_anchors


CLASSES = OPERATOR_CLASSES + PANEL_CLASSES


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.smrn_marker_size = bpy.props.FloatProperty(
        name="标记显示大小",
        default=0.08,
        min=0.0001,
        max=10.0,
        precision=4,
    )
    bpy.types.Scene.smrn_magnetic_radius_px = bpy.props.IntProperty(
        name="磁吸半径",
        default=12,
        min=0,
        max=80,
    )
    bpy.types.Scene.smrn_status = bpy.props.StringProperty(
        name="状态",
        default="请选择完整模型或主要语义源，然后开始标记。",
    )
    bpy.types.Scene.smrn_rotational_segments = bpy.props.IntProperty(
        name="圆周细分", default=128, min=32, max=512,
    )
    bpy.types.Scene.smrn_rotational_thickness = bpy.props.FloatProperty(
        name="壳体厚度", default=0.0, min=0.0, max=100.0, precision=4,
    )
    bpy.types.Scene.smrn_rotational_clearance = bpy.props.FloatProperty(
        name="额外外扩", default=0.0, min=0.0, max=10.0, precision=4,
    )
    bpy.types.Scene.smrn_rotational_summary = bpy.props.StringProperty(
        name="旋转曲面结果", default="尚未分析本轮标记",
    )
    try:
        migration = migrate_scene_anchors(bpy.context.scene)
        bpy.context.scene.smrn_status = (
            f"数据架构 v2 已就绪：{migration['count']} 个标记，"
            f"{migration['anchors_backfilled']} 个稳定表面锚点。"
        )
    except Exception as error:
        bpy.context.scene.smrn_status = f"数据迁移未完成：{error}"


def unregister():
    for name in (
        "smrn_rotational_summary", "smrn_rotational_clearance",
        "smrn_rotational_thickness", "smrn_rotational_segments",
        "smrn_status", "smrn_magnetic_radius_px", "smrn_marker_size",
    ):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
