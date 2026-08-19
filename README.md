# Semantic Mesh Restorer Next

这是语义网格修复插件的逐功能重构工程。当前第一个可验收切片是 Blender 中的非破坏式“目标 / 排除”表面标记。

## 当前范围

- 选定当前语义源模型，但不复制、不隐藏、不改写源网格。
- 在所有可见网格上以绿色标记“需要处理”，红色标记“不要处理”。
- 记录命中对象、语义源对象、面编号、世界坐标、法线、磁吸偏移和表面偏移。
- 支持 `Z` 撤销上一标记、清空全部标记、单独隐藏辅助标记。
- 固定使用三个根集合，并始终恢复当前模型可见性。
- 使用版本化“文档 → 任务 → 标记 → 表面锚点”数据模型；旧版标记会自动、非破坏式迁移。
- 标记按每 128 条分块保存，新增标记只改写末尾小块；侧栏只读取轻量统计索引。
- 表面锚点同时保留世界/局部坐标、源网格指纹，并为三角面保留顶点及重心坐标。
- 底层预留边界、安装点、缺口端点、轴线等角色；当前界面仍只开放目标/排除。

尚未迁移：区域生长、缺口路径、边界/安装点约束、重建、加厚、平滑和验收替换。

## 目录

- `blender_addon/semantic_mesh_marker_next/`：Blender 插件源码。
- `skills/semantic-marking-next/`：Codex 的精简使用入口。
- `tests/`：不依赖 Blender 的记录格式测试。
- `docs/data_architecture.md`：版本化数据模型、存储和扩展边界。
- `scripts/build_addon.ps1`：生成可安装 ZIP。

## 验证

```powershell
python -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -File scripts/build_addon.ps1
```

在 Blender 中安装 `dist/semantic_mesh_marker_next.zip` 后，从 3D 视图右侧栏打开“语义标记 Next”。
