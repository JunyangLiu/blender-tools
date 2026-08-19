---
name: semantic-marking-next
description: Migrate, maintain, build, test, package, or use the refactored Blender semantic target and exclude marking feature. Use for Semantic Mesh Restorer Next, SMRN marking, non-destructive surface annotations, marking data compatibility, or the next staged mesh-restoration migration.
---

# Semantic Marking Next

Work in small, independently testable Git commits. Treat the add-on under `blender_addon/semantic_mesh_marker_next/` as the source of truth.

For every Blender marking change:

1. Preserve the three scene roots: current model, candidates, and helpers.
2. Keep at least one complete source vehicle visible at all times. Never hide it to expose marks.
3. Store markers only in the helper collection and exclude helper objects from ray casting.
4. Use ordinary depth testing and surface-normal offsets so rear marks remain occluded and marks stay attached while the view rotates.
5. Preserve the versioned document/task/mark/anchor contract in `records.py` and `storage.py`; migrate older records non-destructively.
6. Run `python -m unittest discover -s tests -v` before packaging.
7. Build the Blender ZIP with `scripts/build_addon.ps1` and report unverified Blender UI behavior honestly when Blender was not run.

Do not migrate segmentation, gap repair, rebuilding, thickening, or source replacement into a marking-only change.
