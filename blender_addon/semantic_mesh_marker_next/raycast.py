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


def _brush_disc_offsets(radius_px, spacing_px=None):
    """Return a deterministic, near-uniform screen-space brush disc.

    Magnetic picking only needs a few probes because it returns one best hit.
    Painting is different: sparse rings leave narrow triangles between probes.
    A small lattice gives bounded coverage while keeping the ray count modest
    (49 probes for the default 12 px radius).
    """
    radius = max(0, int(radius_px))
    if not radius:
        return [(0, 0)]
    if spacing_px is None:
        # One-pixel probes keep very thin visible triangles selectable at the
        # normal brush size. Larger brushes relax to two pixels to bound cost.
        spacing = 1 if radius <= 14 else 2
    else:
        spacing = max(1, int(spacing_px))
    values = range(-radius, radius + 1, spacing)
    offsets = {
        (dx, dy)
        for dx in values
        for dy in values
        if dx * dx + dy * dy <= radius * radius
    }
    offsets.add((0, 0))
    return sorted(offsets, key=lambda item: (item[0] * item[0] + item[1] * item[1], item[1], item[0]))


def object_hit_at(
    context,
    obj,
    region,
    region_3d,
    coordinate,
    *,
    depsgraph=None,
    inverse=None,
    normal_matrix=None,
):
    """Ray-cast one locked mesh object without touching helper visibility."""
    origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, coordinate)
    direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, coordinate).normalized()
    inverse = inverse or obj.matrix_world.inverted_safe()
    depsgraph = depsgraph or context.evaluated_depsgraph_get()
    local_origin = inverse @ origin
    local_direction = (inverse.to_3x3() @ direction).normalized()
    hit, location, normal, face_index = obj.ray_cast(
        local_origin,
        local_direction,
        distance=1.0e9,
        depsgraph=depsgraph,
    )
    if not hit or face_index < 0:
        return None
    world_location = obj.matrix_world @ location
    normal_matrix = normal_matrix or obj.matrix_world.to_3x3().inverted_safe().transposed()
    world_normal = normal_matrix @ normal
    if world_normal.length_squared:
        world_normal.normalize()
    toward_viewer = origin - world_location
    if toward_viewer.length_squared:
        toward_viewer.normalize()
    source = semantic_source_object(obj)
    return {
        "world_location": world_location,
        "world_normal": world_normal,
        "toward_viewer": toward_viewer,
        "face_index": int(face_index),
        "hit_object_name": obj.name,
        "source_object_name": source.name,
        "ray_distance": float((world_location - origin).length),
    }


def _passthrough_objects(context):
    return [
        obj
        for obj in context.view_layer.objects
        if obj.type == "MESH"
        and (is_helper_object(obj) or is_unaccepted_candidate_object(obj))
        and obj.visible_get(view_layer=context.view_layer)
    ]


def _sample_visible_hits(context, region, region_3d, coordinate, offsets):
    passthrough_objects = _passthrough_objects(context)
    previous_hidden = {obj.name: obj.hide_get() for obj in passthrough_objects}
    for obj in passthrough_objects:
        obj.hide_set(True)
    if passthrough_objects:
        context.view_layer.update()
    candidates = []
    try:
        for dx, dy in offsets:
            hit = scene_hit_at(context, region, region_3d, (coordinate[0] + dx, coordinate[1] + dy))
            if hit is not None:
                hit["screen_offset_px"] = float(math.hypot(dx, dy))
                candidates.append(hit)
    finally:
        for obj in passthrough_objects:
            obj.hide_set(previous_hidden[obj.name])
        if passthrough_objects:
            context.view_layer.update()
    return candidates


def magnetic_scene_hit(context, region, region_3d, coordinate, radius_px):
    candidates = _sample_visible_hits(
        context, region, region_3d, coordinate, _sample_offsets(radius_px)
    )
    if not candidates:
        return None
    nearest_depth = min(item["ray_distance"] for item in candidates)
    depth_window = max(0.35, nearest_depth * 0.0025)
    foreground = [item for item in candidates if item["ray_distance"] <= nearest_depth + depth_window]
    return min(foreground, key=lambda item: (item["screen_offset_px"], item["ray_distance"]))


def brush_scene_hits(context, region, region_3d, coordinate, radius_px):
    """Return all unique visible faces covered by a screen-space brush disc.

    The closest probe establishes the object being painted. Other objects in
    the disc are ignored, so a broad brush cannot jump from the intended part
    onto nearby fittings. Every accepted ray is already the front-most visible
    surface at that pixel; no through-surface or whole-model scan is involved.
    """
    candidates = _sample_visible_hits(
        context, region, region_3d, coordinate, _brush_disc_offsets(radius_px)
    )
    if not candidates:
        return []
    anchor = min(candidates, key=lambda item: (item["screen_offset_px"], item["ray_distance"]))
    anchor_object = anchor["hit_object_name"]
    unique = {}
    for hit in candidates:
        if hit["hit_object_name"] != anchor_object:
            continue
        key = (hit["hit_object_name"], hit["face_index"])
        previous = unique.get(key)
        if previous is None or hit["screen_offset_px"] < previous["screen_offset_px"]:
            unique[key] = hit
    return sorted(unique.values(), key=lambda item: (item["screen_offset_px"], item["face_index"]))


def brush_object_hits(context, region, region_3d, coordinate, radius_px, object_name):
    """Dense brush hits on the object locked by the stroke's first click.

    This path avoids repeatedly hiding and restoring hundreds of annotation
    helpers. It also guarantees that a broad brush cannot jump to a neighboring
    object while retaining front-most visibility within the locked source.
    """
    obj = bpy.data.objects.get(object_name)
    if obj is None or obj.type != "MESH":
        return []
    depsgraph = context.evaluated_depsgraph_get()
    inverse = obj.matrix_world.inverted_safe()
    normal_matrix = obj.matrix_world.to_3x3().inverted_safe().transposed()
    unique = {}
    for dx, dy in _brush_disc_offsets(radius_px):
        hit = object_hit_at(
            context,
            obj,
            region,
            region_3d,
            (coordinate[0] + dx, coordinate[1] + dy),
            depsgraph=depsgraph,
            inverse=inverse,
            normal_matrix=normal_matrix,
        )
        if hit is None:
            continue
        hit["screen_offset_px"] = float(math.hypot(dx, dy))
        key = int(hit["face_index"])
        previous = unique.get(key)
        if previous is None or hit["screen_offset_px"] < previous["screen_offset_px"]:
            unique[key] = hit
    return sorted(unique.values(), key=lambda item: (item["screen_offset_px"], item["face_index"]))
