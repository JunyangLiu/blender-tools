"""Build the new exact-green original-mesh rotational preview in the live scene."""

import importlib
import json

import bpy


PACKAGE = "semantic_mesh_marker_next"
scene = bpy.context.scene
anchors = importlib.import_module(PACKAGE + ".anchors")
storage = importlib.import_module(PACKAGE + ".storage")
surface = importlib.import_module(PACKAGE + ".surface_rebuild_blender")

source = bpy.data.objects.get(str(scene.get("smrn_source_name", "")))
if source is None:
    raise RuntimeError("Configured semantic source is missing")
before_fingerprint = anchors.source_snapshot(source)["fingerprint"]
before_counts = storage.document_summary(scene)["role_counts"]
surface.remove_last_candidate(scene)
candidate, report = surface.build_scene_candidate(scene, mode="rotational")
after_fingerprint = anchors.source_snapshot(source)["fingerprint"]
after_counts = storage.document_summary(scene)["role_counts"]
qa = report["topology_qa"]
projection = qa.get("rotational_projection_qa") or {}
result = {
    "candidate": candidate.name,
    "candidate_mode": str(scene.get("smrn_surface_candidate_mode", "")),
    "source_fingerprint_unchanged": before_fingerprint == after_fingerprint,
    "marks_unchanged": before_counts == after_counts,
    "role_counts": after_counts,
    "selected_faces": report["semantic_region"]["selected_faces"],
    "faces_after": qa["region_faces_after"],
    "projected_vertices": projection.get("projected_vertices"),
    "projection_fraction": projection.get("projection_fraction"),
    "residual_before_p90": projection.get("before_radial_residual_p90"),
    "residual_after_p90": projection.get("after_radial_residual_p90"),
    "fit_profile": (projection.get("fit") or {}).get("profile_kind"),
    "topology_passed": qa["passed"],
    "whole_vehicle_search": report["coverage_qa"]["whole_vehicle_search"],
}
if not all((
    result["source_fingerprint_unchanged"], result["marks_unchanged"],
    result["topology_passed"], result["candidate_mode"] == "rotational",
    result["whole_vehicle_search"] is False,
)):
    raise RuntimeError("Rotational surface rebuild QA failed: " + repr(result))
print("SMRN_ROTATIONAL_SURFACE_V068=" + json.dumps(
    result, ensure_ascii=False, separators=(",", ":")
))
