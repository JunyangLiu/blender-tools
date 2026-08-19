import bpy

from .constants import (
    CANDIDATE_COLLECTION_NAME,
    HELPER_COLLECTION_NAME,
    MARK_PREFIX,
    MODEL_COLLECTION_NAME,
    SOURCE_NAME_KEY,
)
from .storage import document_summary, load_all_marks


def ensure_root_collection(name, scene):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    if scene.collection.children.get(collection.name) is None:
        scene.collection.children.link(collection)
    return collection


def ensure_scene_roots(scene, *, reveal_helpers=False):
    model = ensure_root_collection(MODEL_COLLECTION_NAME, scene)
    candidates = ensure_root_collection(CANDIDATE_COLLECTION_NAME, scene)
    helpers = ensure_root_collection(HELPER_COLLECTION_NAME, scene)
    model["smrn_collection_role"] = "current_model"
    candidates["smrn_collection_role"] = "working_candidates"
    helpers["smrn_collection_role"] = "helpers"
    model.hide_viewport = False
    model.hide_render = False
    helpers.hide_render = True
    if reveal_helpers:
        helpers.hide_viewport = False
    return model, candidates, helpers


def is_helper_object(obj):
    legacy_role = str(obj.get("smr_role", ""))
    return bool(
        obj.name.startswith(MARK_PREFIX)
        or obj.get("smrn_annotation_only", False)
        or obj.get("smrn_role", "") == "marker_do_not_export"
        or obj.get("smr_annotation_only", False)
        or obj.name.startswith(("SMR_VISIBLE_MARK_", "SMR_CONSTRAINT_"))
        or "marker" in legacy_role
        or "overlay" in legacy_role
        or "do_not_export" in legacy_role
        or any(owner.name == HELPER_COLLECTION_NAME for owner in obj.users_collection)
    )


def link_helper_object(obj, scene):
    _model, _candidates, helpers = ensure_scene_roots(scene, reveal_helpers=True)
    if helpers.objects.get(obj.name) is None:
        helpers.objects.link(obj)
    for owner in tuple(obj.users_collection):
        if owner != helpers:
            owner.objects.unlink(obj)
    obj.hide_render = True


def set_source(scene, source):
    model, _candidates, _helpers = ensure_scene_roots(scene)
    if model.objects.get(source.name) is None:
        model.objects.link(source)
    for owner in tuple(source.users_collection):
        if owner != model:
            owner.objects.unlink(source)
    scene[SOURCE_NAME_KEY] = source.name
    source.hide_viewport = False
    source.hide_render = False
    source.hide_set(False)


def semantic_source_object(obj):
    if obj is None:
        return None
    source_name = str(obj.get("smrn_source_name", obj.get("smr_source_name", "")))
    source = bpy.data.objects.get(source_name) if source_name else None
    return source if source is not None and source.type == "MESH" else obj


def keep_model_visible(scene):
    model, _candidates, _helpers = ensure_scene_roots(scene)
    model.hide_viewport = False
    model.hide_render = False
    for obj in model.all_objects:
        obj.hide_viewport = False
        obj.hide_render = False
        obj.hide_set(False)


def set_helpers_hidden(scene, hidden):
    _model, _candidates, helpers = ensure_scene_roots(scene)
    helpers.hide_viewport = bool(hidden)
    keep_model_visible(scene)


def load_marks(scene):
    return load_all_marks(scene)


def marks_summary(scene):
    return document_summary(scene)


def visible_meshes(context):
    return [
        obj
        for obj in context.view_layer.objects
        if obj.type == "MESH"
        and obj.visible_get(view_layer=context.view_layer)
        and not is_helper_object(obj)
    ]
