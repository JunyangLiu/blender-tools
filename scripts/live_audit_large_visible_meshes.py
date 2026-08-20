import json

import bpy


scene = bpy.context.scene
rows = []
for obj in bpy.context.view_layer.objects:
    if obj.type != "MESH":
        continue
    visible = bool(obj.visible_get(view_layer=bpy.context.view_layer))
    vertices = len(obj.data.vertices)
    faces = len(obj.data.polygons)
    dims = tuple(round(float(value), 6) for value in obj.dimensions)
    rows.append(
        {
            "name": obj.name,
            "visible": visible,
            "selected": bool(obj.select_get()),
            "vertices": vertices,
            "faces": faces,
            "dimensions": dims,
            "location": tuple(round(float(value), 6) for value in obj.location),
            "collections": [collection.name for collection in obj.users_collection],
            "archive_only": bool(obj.get("smrn_archive_only", False)),
            "accepted": bool(obj.get("smrn_accepted", False)),
            "source_name": str(obj.get("smrn_source_name", obj.get("smr_source_name", ""))),
        }
    )

rows.sort(key=lambda row: (row["visible"], row["faces"], row["vertices"]), reverse=True)
result = {
    "blend": bpy.data.filepath,
    "active": bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None,
    "source_name": str(scene.get("smrn_source_name", "")),
    "visible_mesh_count": sum(1 for row in rows if row["visible"]),
    "top_visible": [row for row in rows if row["visible"]][:40],
    "top_hidden": [row for row in rows if not row["visible"]][:20],
}
print("SMRN_LARGE_MESH_AUDIT=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
