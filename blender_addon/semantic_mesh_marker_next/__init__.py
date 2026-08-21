bl_info = {
    "name": "Semantic Mesh Marker Next",
    "author": "Local developer",
    "version": (0, 6, 18),
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
    bpy.types.Scene.smrn_show_advanced = bpy.props.BoolProperty(
        name="高级设置",
        description="显示不常用的拟合与诊断参数",
        default=False,
    )
    bpy.types.Scene.smrn_magnetic_radius_px = bpy.props.IntProperty(
        name="刷选覆盖半径",
        description="拖刷覆盖范围；单击时也作为靠近细小表面的磁吸范围",
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
    bpy.types.Scene.smrn_handle_path_segments = bpy.props.IntProperty(
        name="扶手路径细分", default=96, min=32, max=384,
    )
    bpy.types.Scene.smrn_handle_section_segments = bpy.props.IntProperty(
        name="扶手截面细分", default=16, min=8, max=64,
    )
    bpy.types.Scene.smrn_handle_min_diameter = bpy.props.FloatProperty(
        name="最小打印直径", default=0.0, min=0.0, max=100.0, precision=4,
    )
    bpy.types.Scene.smrn_handle_clearance = bpy.props.FloatProperty(
        name="扶手额外外扩", default=0.0, min=0.0, max=10.0, precision=4,
    )
    bpy.types.Scene.smrn_handle_thickness_scale = bpy.props.FloatProperty(
        name="扶手粗细",
        description="1.00 为刚好覆盖旧扶手；只允许向外加粗，以保证旧扶手完全被覆盖",
        default=1.0,
        min=1.0,
        max=2.0,
        step=2,
        precision=2,
    )
    bpy.types.Scene.smrn_handle_summary = bpy.props.StringProperty(
        name="扶手还原结果", default="尚未分析本轮扶手标记",
    )
    bpy.types.Scene.smrn_surface_subdivision_level = bpy.props.IntProperty(
        name="局部细化等级", description="只细分绿色标记附近的局部网面", default=1, min=1, max=2,
    )
    bpy.types.Scene.smrn_surface_smooth_strength = bpy.props.FloatProperty(
        name="局部平滑强度",
        description="0.50 为旧版最高强度；继续增大时只增加标记内部的受限平滑轮数",
        default=0.22, min=0.0, max=1.0, step=1, precision=2,
    )
    bpy.types.Scene.smrn_canvas_wave_strength = bpy.props.FloatProperty(
        name="帆布自然波纹程度",
        description="从绿色帆布表面拟合波纹方向、波长与相位；0 为不增强，1 为明显但受限",
        default=0.45, min=0.0, max=1.0, step=1, precision=2,
    )
    bpy.types.Scene.smrn_surface_hard_angle = bpy.props.FloatProperty(
        name="硬边保护角度", default=35.0, min=5.0, max=85.0, precision=1,
    )
    bpy.types.Scene.smrn_surface_height_mode = bpy.props.EnumProperty(
        name="平整高度",
        description="决定平整面经过绿色标记区域的最低点、中间位置或最高点",
        items=(
            ("LOW", "贴最低点", "沿所选法向贴到绿色标记区域的最低点"),
            ("MEDIAN", "居中拟合", "使用绿色标记区域的中间高度"),
            ("HIGH", "贴最高点", "沿所选法向贴到绿色标记区域的最高点"),
            ("RED_REFERENCE", "红面高度", "让平整面经过红色标记面的稳健中间高度；红色面保持不动"),
        ),
        default="MEDIAN",
    )
    bpy.types.Scene.smrn_surface_normal_mode = bpy.props.EnumProperty(
        name="平整方向",
        description="决定平直面的法向依据",
        items=(
            ("AUTO", "自动拟合", "分别从每个连续绿色区域拟合稳定法向"),
            ("FIRST_TARGET", "第一处绿色面", "采用本轮第一处绿色标记面的法向"),
            ("RED_REFERENCE", "红色参考面", "采用红色标记面的平均法向；红色面保持不动"),
        ),
        default="AUTO",
    )
    bpy.types.Scene.smrn_surface_summary = bpy.props.StringProperty(
        name="局部网面重构结果", default="尚未生成局部网面候选",
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
        "smrn_surface_summary", "smrn_surface_normal_mode", "smrn_surface_height_mode",
        "smrn_surface_hard_angle",
        "smrn_canvas_wave_strength", "smrn_surface_smooth_strength", "smrn_surface_subdivision_level",
        "smrn_handle_summary", "smrn_handle_clearance", "smrn_handle_thickness_scale",
        "smrn_handle_min_diameter", "smrn_handle_section_segments",
        "smrn_handle_path_segments",
        "smrn_rotational_summary", "smrn_rotational_clearance",
        "smrn_rotational_thickness", "smrn_rotational_segments",
        "smrn_status", "smrn_magnetic_radius_px", "smrn_marker_size",
        "smrn_show_advanced",
    ):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
