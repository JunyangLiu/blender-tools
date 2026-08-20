import math

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

from .scene_state import (
    is_helper_object,
    is_unaccepted_candidate_object,
    semantic_source_object,
)


def scene_hit_at(context, region, region_3d, coordinate):
    origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, coordinate)
    direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, coordinate).normalized()
    hit, location, normal, face_index, hit_obj, _matrix = context.scene.ray_cast(
        context.evaluated_depsgraph_get(), origin, direction, distance=1.0e9
    )
    if not hit or hit_obj is None or hit_obj.type != "MESH" or face_index < 0:
        return None
    original = getattr(hit_obj, "original", None)
    if original is None or original.type != "MESH":
        original = bpy.data.objects.get(hit_obj.name, hit_obj)
    source = semantic_source_object(original)
    world_location = Vector(location)
    world_normal = Vector(normal)
    if world_normal.length_squared:
        world_normal.normalize()
    toward_viewer = origin - world_location
    if toward_viewer.length_squared:
        toward_viewer.normalize()
    return {
        "world_location": world_location,
        "world_normal": world_normal,
        "toward_viewer": toward_viewer,
        "face_index": int(face_index),
        "hit_object_name": original.name,
        "source_object_name": source.name,
        "ray_distance": float((world_location - origin).length),
    }


def _sample_offsets(radius_px):
    radius = max(0, int(radius_px))
    offsets = [(0, 0)]
    if not radius:
        return offsets
    ring_count = max(1, min(4, math.ceil(radius / 4)))
    for ring in range(1, ring_count + 1):
        distance = radius * ring / ring_count
        sample_count = 8 if ring < ring_count else 16
        for step in range(sample_count):
            angle = math.tau * step / sample_count
            offsets.append((round(math.cos(angle) * distance), round(math.sin(angle) * distance)))
    return offsets


def magnetic_scene_hit(context, region, region_3d, coordinate, radius_px):
    passthrough_objects = [
        obj
        for obj in context.view_layer.objects
        if obj.type == "MESH"
        and (is_helper_object(obj) or is_unaccepted_candidate_object(obj))
        and obj.visible_get(view_layer=context.view_layer)
    ]
    previous_hidden = {obj.name: obj.hide_get() for obj in passthrough_objects}
    for obj in passthrough_objects:
        obj.hide_set(True)
    if passthrough_objects:
        context.view_layer.update()
    candidates = []
    try:
        for dx, dy in _sample_offsets(radius_px):
            hit = scene_hit_at(context, region, region_3d, (coordinate[0] + dx, coordinate[1] + dy))
            if hit is not None:
                hit["screen_offset_px"] = float(math.hypot(dx, dy))
                candidates.append(hit)
    finally:
        for obj in passthrough_objects:
            obj.hide_set(previous_hidden[obj.name])
        if passthrough_objects:
            context.view_layer.update()
    if not candidates:
        return None
    nearest_depth = min(item["ray_distance"] for item in candidates)
    depth_window = max(0.35, nearest_depth * 0.0025)
    foreground = [item for item in candidates if item["ray_distance"] <= nearest_depth + depth_window]
    return min(foreground, key=lambda item: (item["screen_offset_px"], item["ray_distance"]))
