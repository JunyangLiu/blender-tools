"""Versioned pure-Python semantic annotation records."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Iterable, Mapping


SCHEMA_NAME = "smrn.semantic_annotations"
SCHEMA_VERSION = 2
CORE_ROLES = frozenset({
    "target", "exclude", "boundary", "attachment", "gap_start", "gap_end",
    "axis", "centerline", "reference",
})
VALID_ROLES = CORE_ROLES


def _vector(value: Iterable[Any], field_name: str, length: int = 3) -> tuple[float, ...]:
    result = tuple(float(item) for item in value)
    if len(result) != length:
        raise ValueError(f"{field_name} must contain exactly {length} numbers")
    return result


def _optional_vector(value: Any, field_name: str, length: int = 3) -> tuple[float, ...] | None:
    return None if value is None else _vector(value, field_name, length)


def valid_role(role: str) -> bool:
    return role in CORE_ROLES or role.startswith("x.")


@dataclass(frozen=True)
class SourceSnapshot:
    object_name: str
    mesh_name: str = ""
    vertex_count: int = 0
    polygon_count: int = 0
    matrix_world: tuple[float, ...] = ()
    bounds_local: tuple[float, ...] = ()
    fingerprint: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "SourceSnapshot | None":
        if not value:
            return None
        return cls(
            object_name=str(value.get("object_name", "")),
            mesh_name=str(value.get("mesh_name", "")),
            vertex_count=int(value.get("vertex_count", 0)),
            polygon_count=int(value.get("polygon_count", 0)),
            matrix_world=_vector(value.get("matrix_world", ()), "matrix_world", 16) if value.get("matrix_world") else (),
            bounds_local=_vector(value.get("bounds_local", ()), "bounds_local", 6) if value.get("bounds_local") else (),
            fingerprint=str(value.get("fingerprint", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_name": self.object_name, "mesh_name": self.mesh_name,
            "vertex_count": self.vertex_count, "polygon_count": self.polygon_count,
            "matrix_world": list(self.matrix_world), "bounds_local": list(self.bounds_local),
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class SurfaceAnchor:
    face_index: int
    world_location: tuple[float, float, float]
    world_normal: tuple[float, float, float]
    local_location: tuple[float, float, float] | None = None
    local_normal: tuple[float, float, float] | None = None
    triangle_vertex_indices: tuple[int, int, int] | None = None
    barycentric: tuple[float, float, float] | None = None
    source_fingerprint: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SurfaceAnchor":
        return cls(
            face_index=int(value["face_index"]),
            world_location=_vector(value["world_location"], "world_location"),
            world_normal=_vector(value["world_normal"], "world_normal"),
            local_location=_optional_vector(value.get("local_location"), "local_location"),
            local_normal=_optional_vector(value.get("local_normal"), "local_normal"),
            triangle_vertex_indices=(tuple(int(item) for item in value["triangle_vertex_indices"])
                                     if value.get("triangle_vertex_indices") is not None else None),
            barycentric=_optional_vector(value.get("barycentric"), "barycentric"),
            source_fingerprint=str(value.get("source_fingerprint", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "face_index": self.face_index,
            "world_location": list(self.world_location), "world_normal": list(self.world_normal),
            "local_location": list(self.local_location) if self.local_location is not None else None,
            "local_normal": list(self.local_normal) if self.local_normal is not None else None,
            "triangle_vertex_indices": list(self.triangle_vertex_indices) if self.triangle_vertex_indices else None,
            "barycentric": list(self.barycentric) if self.barycentric is not None else None,
            "source_fingerprint": self.source_fingerprint,
        }

    def stable_key(self, source_name: str, precision: int = 5) -> str:
        location = self.local_location or self.world_location
        rounded = ",".join(f"{item:.{precision}f}" for item in location)
        identity = self.source_fingerprint or source_name
        return f"{identity}|{self.face_index}|{rounded}"


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
    schema_version: int = SCHEMA_VERSION
    task_id: str = "task-0001"
    local_location: tuple[float, float, float] | None = None
    local_normal: tuple[float, float, float] | None = None
    triangle_vertex_indices: tuple[int, int, int] | None = None
    barycentric: tuple[float, float, float] | None = None
    source_fingerprint: str = ""
    semantic_radius: float | None = None
    confidence: float = 1.0
    created_at: str = ""
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.id < 1:
            raise ValueError("id must be positive")
        if not valid_role(self.role):
            raise ValueError(f"unsupported role: {self.role}")
        if self.face_index < 0:
            raise ValueError("face_index must be non-negative")
        if not self.overlay_object_name or not self.hit_object_name or not self.task_id:
            raise ValueError("object names and task_id must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between zero and one")

    @property
    def anchor(self) -> SurfaceAnchor:
        return SurfaceAnchor(
            self.face_index, self.world_location, self.world_normal, self.local_location,
            self.local_normal, self.triangle_vertex_indices, self.barycentric,
            self.source_fingerprint,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MarkRecord":
        anchor = value.get("anchor", value)
        return cls(
            id=int(value["id"]), role=str(value["role"]),
            overlay_object_name=str(value["overlay_object_name"]),
            hit_object_name=str(value["hit_object_name"]),
            source_object_name=str(value.get("source_object_name", value["hit_object_name"])),
            face_index=int(anchor["face_index"]),
            world_location=_vector(anchor["world_location"], "world_location"),
            world_normal=_vector(anchor["world_normal"], "world_normal"),
            screen_offset_px=float(value.get("screen_offset_px", 0.0)),
            surface_offset=float(value.get("surface_offset", 0.0)),
            annotation_only=bool(value.get("annotation_only", True)),
            schema_version=SCHEMA_VERSION,
            task_id=str(value.get("task_id", "task-0001")),
            local_location=_optional_vector(anchor.get("local_location"), "local_location"),
            local_normal=_optional_vector(anchor.get("local_normal"), "local_normal"),
            triangle_vertex_indices=(tuple(int(item) for item in anchor["triangle_vertex_indices"])
                                     if anchor.get("triangle_vertex_indices") is not None else None),
            barycentric=_optional_vector(anchor.get("barycentric"), "barycentric"),
            source_fingerprint=str(anchor.get("source_fingerprint", "")),
            semantic_radius=(float(value["semantic_radius"]) if value.get("semantic_radius") is not None else None),
            confidence=float(value.get("confidence", 1.0)), created_at=str(value.get("created_at", "")),
            extensions=dict(value.get("extensions", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION, "id": self.id, "task_id": self.task_id,
            "role": self.role, "overlay_object_name": self.overlay_object_name,
            "hit_object_name": self.hit_object_name, "source_object_name": self.source_object_name,
            "anchor": self.anchor.to_dict(), "screen_offset_px": self.screen_offset_px,
            "surface_offset": self.surface_offset, "semantic_radius": self.semantic_radius,
            "confidence": self.confidence, "annotation_only": self.annotation_only,
            "created_at": self.created_at, "extensions": dict(self.extensions),
        }


def loads_marks(raw: str | None) -> list[MarkRecord]:
    if not raw:
        return []
    payload = json.loads(raw)
    if isinstance(payload, dict):
        payload = payload.get("records", [])
    if not isinstance(payload, list):
        raise ValueError("mark payload must contain a record list")
    return [MarkRecord.from_mapping(item) for item in payload]


def dumps_marks(records: Iterable[MarkRecord]) -> str:
    return json.dumps({"schema": SCHEMA_NAME, "version": SCHEMA_VERSION,
                       "records": [record.to_dict() for record in records]},
                      ensure_ascii=False, separators=(",", ":"))


def next_mark_id(records: Iterable[MarkRecord]) -> int:
    return max((record.id for record in records), default=0) + 1


def role_counts(records: Iterable[MarkRecord]) -> dict[str, int]:
    result = {role: 0 for role in CORE_ROLES}
    for record in records:
        result[record.role] = result.get(record.role, 0) + 1
    return result
