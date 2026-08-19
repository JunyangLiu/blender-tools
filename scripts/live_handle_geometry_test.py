"""Build an in-memory synthetic handle and validate closed topology in Blender."""

import json
import numpy as np

from semantic_mesh_marker_next.handle_blender import _candidate_geometry, _topology


theta = np.linspace(np.pi, 0.0, 97)
path = np.column_stack((5.0 * np.cos(theta), np.zeros_like(theta), 2.6 * np.sin(theta)))
vertices, faces = _candidate_geometry(path, (0.0, 1.0, 0.0), 0.30, 0.36, 16)
report = _topology(vertices, faces)
report["created_scene_object"] = False
report["source_touched"] = False
print("SMRN_HANDLE_GEOMETRY=" + json.dumps(report, separators=(",", ":")))
