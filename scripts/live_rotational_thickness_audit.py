"""Verify automatic rotational backing stays thin in the live add-on."""

import json

from semantic_mesh_marker_next.rotational_blender import _auto_thickness


class RepresentativeFit:
    def radius_at_axial(self, _axial):
        return 5.29


axial_min, axial_max = 0.0, 0.52
new_value = _auto_thickness(RepresentativeFit(), axial_min, axial_max)
old_value = max(0.02, min(5.29 * 0.08, (axial_max - axial_min) * 0.35))
print("SMRN_ROTATIONAL_THICKNESS_AUDIT=" + json.dumps({
    "representative_radius": 5.29,
    "representative_axial_span": axial_max - axial_min,
    "old_auto_thickness": old_value,
    "new_auto_thickness": new_value,
    "reduction_ratio": 1.0 - new_value / old_value,
    "passed": new_value < old_value * 0.10,
}, separators=(",", ":")))
