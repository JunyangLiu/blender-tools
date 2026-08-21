"""Inspect only the persisted last rebuild region on the confirmed source."""

import json
import math

import bpy


scene = bpy.context.scene
source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
if source is None or source.type != "MESH":
    raise RuntimeError("Current semantic source is unavailable")
mesh = source.data
attribute = mesh.attributes.get("smrn_rebuild_region")
if attribute is None or attribute.domain != "FACE":
    raise RuntimeError("Confirmed source has no persisted local rebuild-region attribute")

region_indices = [index for index, item in enumerate(attribute.data) if int(item.value) == 1]
region_set = set(region_indices)
areas = []
aspects = []
smooth_faces = 0
zero_area = 0
duplicate_keys = {}
for index in region_indices:
    poly = mesh.polygons[index]
    area = float(poly.area)
    areas.append(area)
    smooth_faces += int(poly.use_smooth)
    zero_area += int(area <= 1.0e-14)
    key = tuple(sorted(int(vertex) for vertex in poly.vertices))
    duplicate_keys.setdefault(key, []).append(index)
    if len(poly.vertices) == 3 and area > 1.0e-18:
        coords = [mesh.vertices[vertex].co for vertex in poly.vertices]
        lengths = [(coords[(i + 1) % 3] - coords[i]).length for i in range(3)]
        longest = max(lengths)
        altitude = (2.0 * area) / max(longest, 1.0e-18)
        aspects.append(longest / max(altitude, 1.0e-18))

internal_edges = []
boundary_edges = []
dihedrals = []
edge_faces = {}
for index in region_indices:
    for edge_key in mesh.polygons[index].edge_keys:
        edge_faces.setdefault(tuple(sorted(edge_key)), []).append(index)

for edge_key, linked in edge_faces.items():
    if len(linked) == 2:
        internal_edges.append(edge_key)
        first = mesh.polygons[linked[0]].normal
        second = mesh.polygons[linked[1]].normal
        dihedrals.append(math.degrees(first.angle(second, 0.0)))
    else:
        boundary_edges.append(edge_key)

def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return 0.0
    return values[min(len(values) - 1, int(round((len(values) - 1) * fraction)))]

result = {
    "source": source.name,
    "region_faces": len(region_indices),
    "region_vertices": len({vertex for index in region_indices for vertex in mesh.polygons[index].vertices}),
    "region_smooth_faces": smooth_faces,
    "zero_area_faces": zero_area,
    "duplicate_face_groups": sum(len(items) > 1 for items in duplicate_keys.values()),
    "area_min": min(areas, default=0.0),
    "area_median": percentile(areas, 0.5),
    "aspect_p50": percentile(aspects, 0.5),
    "aspect_p95": percentile(aspects, 0.95),
    "aspect_max": max(aspects, default=0.0),
    "aspect_over_20": sum(value > 20.0 for value in aspects),
    "aspect_over_50": sum(value > 50.0 for value in aspects),
    "aspect_over_100": sum(value > 100.0 for value in aspects),
    "internal_edges": len(internal_edges),
    "boundary_edges": len(boundary_edges),
    "dihedral_p50_degrees": percentile(dihedrals, 0.5),
    "dihedral_p95_degrees": percentile(dihedrals, 0.95),
    "dihedral_max_degrees": max(dihedrals, default=0.0),
    "dihedral_over_0_1_degrees": sum(value > 0.1 for value in dihedrals),
    "dihedral_over_1_degree": sum(value > 1.0 for value in dihedrals),
    "mesh_attributes": [item.name for item in mesh.attributes],
}
print("SMRN_FLATTEN_REGION_TOPOLOGY_V0618=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
