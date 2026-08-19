"""Pure-Python mark record schema; intentionally importable without Blender."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Iterable, Mapping


VALID_ROLES = frozenset({"target", "exclude"})


def _vector3(value: Iterable[Any], field: str) -> tuple[float, float, float]:
    items = tuple(float(item) for item in value)
    if len(items) != 3:
        raise ValueError(f"{field} must contain exactly three numbers")
    return items


@dataclass(frozen=True)
class MarkRecord:
    id: int
    role: str
    overlay_object_name: str
    hit_object_name: str
    source_object_name: str
    face_index: int
    world_location: tuple[float, float, float]
    world_normal: tuple[float, float, float]
    screen_offset_px: float
    surface_offset: float
    annotation_only: bool = True
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.id < 1:
            raise ValueError("id must be positive")
        if self.role not in VALID_ROLES:
            raise ValueError(f"unsupported role: {self.role}")
        if self.face_index < 0:
            raise ValueError("face_index must be non-negative")
        if not self.overlay_object_name or not self.hit_object_name:
            raise ValueError("object names must not be empty")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MarkRecord":
        return cls(
            id=int(value["id"]),
            role=str(value["role"]),
            overlay_object_name=str(value["overlay_object_name"]),
            hit_object_name=str(value["hit_object_name"]),
            source_object_name=str(value.get("source_object_name", value["hit_object_name"])),
            face_index=int(value["face_index"]),
            world_location=_vector3(value["world_location"], "world_location"),
            world_normal=_vector3(value["world_normal"], "world_normal"),
            screen_offset_px=float(value.get("screen_offset_px", 0.0)),
            surface_offset=float(value.get("surface_offset", 0.0)),
            annotation_only=bool(value.get("annotation_only", True)),
            schema_version=int(value.get("schema_version", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["world_location"] = list(self.world_location)
        result["world_normal"] = list(self.world_normal)
        return result


def loads_marks(raw: str | None) -> list[MarkRecord]:
    if not raw:
        return []
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("mark payload must be a JSON list")
    return [MarkRecord.from_mapping(item) for item in payload]


def dumps_marks(records: Iterable[MarkRecord]) -> str:
    return json.dumps(
        [record.to_dict() for record in records],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def next_mark_id(records: Iterable[MarkRecord]) -> int:
    return max((record.id for record in records), default=0) + 1


def role_counts(records: Iterable[MarkRecord]) -> dict[str, int]:
    result = {"target": 0, "exclude": 0}
    for record in records:
        result[record.role] += 1
    return result

