bl_info = {
    "name": "Semantic Mesh Marker Next",
    "author": "Local developer",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > 语义标记 Next",
    "description": "Non-destructive target and exclude surface marking",
    "category": "3D View",
}

import bpy

from .operators import CLASSES as OPERATOR_CLASSES
from .panel import CLASSES as PANEL_CLASSES


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


def unregister():
    for name in ("smrn_status", "smrn_magnetic_radius_px", "smrn_marker_size"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()

