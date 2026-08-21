import math

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

from .scene_state import (
    is_helper_object,
    is_unaccepted_candidate_object,
    semantic_source_object,
)


def _mark_proxy_source(obj):
    """Return the source for a topology-identical visible working candidate.

    Exact flatten previews deliberately show the full working copy while the
    source is drawn as bounds.  Such a copy is safe to ray-cast because its
    polygon indices still map one-to-one to the untouched source mesh.
    """
    if obj is None or not bool(obj.get("smrn_mark_proxy_face_indices", False)):
        return None
    source = bpy.data.objects.get(str(obj.get("smrn_mark_proxy_source", "")))
    if source is None or source.type != "MESH":
        return None
    if (
        len(obj.data.vertices) != len(source.data.vertices)
        or len(obj.data.polygons) != len(source.data.polygons)
    ):
        return None
    return source


def _mark_hit_identity(obj):
    source = _mark_proxy_source(obj)
    if source is None:
        source = semantic_source_object(obj)
        return obj, source
    return source, source


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
    hit_identity, source = _mark_hit_identity(original)
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
        "hit_object_name": hit_identity.name,
        "source_object_name": source.name,
        "raycast_object_name": original.name,
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
        # The stroke path is sampled every 2 px, so a 3 px disc lattice keeps
        # sub-pixel-thin strips covered without repeating the same 441 rays at
        # every nearby mouse position. Default radius 12 now uses 49 probes.
        spacing = 3 if radius <= 18 else 4
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
    hit_identity, source = _mark_hit_identity(obj)
    return {
        "world_location": world_location,
        "world_normal": world_normal,
        "toward_viewer": toward_viewer,
        "face_index": int(face_index),
        "hit_object_name": hit_identity.name,
        "source_object_name": source.name,
        "raycast_object_name": obj.name,
        "ray_distance": float((world_location - origin).length),
    }


def _passthrough_objects(context):
    return [
        obj
        for obj in context.view_layer.objects
        if obj.type == "MESH"
        and (
            is_helper_object(obj)
            or (is_unaccepted_candidate_object(obj) and _mark_proxy_source(obj) is None)
        )
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
    coordinates = [
        (coordinate[0] + dx, coordinate[1] + dy, float(math.hypot(dx, dy)))
        for dx, dy in _brush_disc_offsets(radius_px)
    ]
    return _object_hits_at_coordinates(
        context, region, region_3d, coordinates, object_name
    )


def _object_hits_at_coordinates(context, region, region_3d, coordinates, object_name):
    obj = bpy.data.objects.get(object_name)
    if obj is None or obj.type != "MESH":
        return []
    depsgraph = context.evaluated_depsgraph_get()
    inverse = obj.matrix_world.inverted_safe()
    normal_matrix = obj.matrix_world.to_3x3().inverted_safe().transposed()
    unique = {}
    for sample_x, sample_y, screen_offset in coordinates:
        hit = object_hit_at(
            context,
            obj,
            region,
            region_3d,
            (sample_x, sample_y),
            depsgraph=depsgraph,
            inverse=inverse,
            normal_matrix=normal_matrix,
        )
        if hit is None:
            continue
        hit["screen_offset_px"] = float(screen_offset)
        key = int(hit["face_index"])
        previous = unique.get(key)
        if previous is None or hit["screen_offset_px"] < previous["screen_offset_px"]:
            unique[key] = hit
    return sorted(unique.values(), key=lambda item: (item["screen_offset_px"], item["face_index"]))


def brush_object_stroke_hits(
    context, region, region_3d, start, end, radius_px, object_name, spacing_px=3
):
    """Ray-cast one swept capsule instead of many overlapping brush discs.

    Every screen-space point between two mouse events is covered even when the
    UI coalesces events during a fast drag. A shared lattice removes the large
    overlap that previously delayed the green feedback.
    """
    radius = max(0.0, float(radius_px))
    dx = float(end[0] - start[0])
    dy = float(end[1] - start[1])
    distance = math.hypot(dx, dy)
    if distance < 1.0e-6:
        return brush_object_hits(
            context, region, region_3d, start, radius_px, object_name
        )
    tangent = (dx / distance, dy / distance)
    perpendicular = (-tangent[1], tangent[0])
    spacing = max(1.0, float(spacing_px))
    along_steps = max(1, int(math.ceil((distance + radius * 2.0) / spacing)))
    cross_steps = max(1, int(math.ceil((radius * 2.0) / spacing)))
    coordinates = []
    seen = set()
    for along_index in range(along_steps + 1):
        along = -radius + (distance + radius * 2.0) * along_index / along_steps
        outside = max(0.0, -along, along - distance)
        half_width = math.sqrt(max(0.0, radius * radius - outside * outside))
        for cross_index in range(cross_steps + 1):
            cross = -radius + radius * 2.0 * cross_index / cross_steps
            if abs(cross) > half_width + 1.0e-6:
                continue
            sample_x = start[0] + tangent[0] * along + perpendicular[0] * cross
            sample_y = start[1] + tangent[1] * along + perpendicular[1] * cross
            key = (round(sample_x), round(sample_y))
            if key in seen:
                continue
            seen.add(key)
            coordinates.append((sample_x, sample_y, abs(cross)))
    return _object_hits_at_coordinates(
        context, region, region_3d, coordinates, object_name
    )
