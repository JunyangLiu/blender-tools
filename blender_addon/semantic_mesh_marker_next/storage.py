"""Chunked scene storage with cheap summaries and legacy migration."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import uuid
from typing import Any, Iterable

from .constants import MARKS_KEY
from .records import CORE_ROLES, MarkRecord, SCHEMA_NAME, SCHEMA_VERSION, dumps_marks, loads_marks


DOCUMENT_KEY = "smrn_document_json"
CHUNK_PREFIX = "smrn_marks_chunk_"
INDEX_PREFIX = "smrn_surface_index_"
DEFAULT_TASK_ID = "task-0001"
CHUNK_SIZE = 128


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _delete(storage: Any, key: str) -> None:
    if key in storage:
        del storage[key]


def _chunk_key(index: int) -> str:
    return f"{CHUNK_PREFIX}{index:06d}_json"


def _index_key(task_id: str, stable_key: str) -> tuple[str, str]:
    composite = f"{task_id}|{stable_key}"
    bucket = hashlib.sha1(composite.encode()).hexdigest()[:2]
    return f"{INDEX_PREFIX}{bucket}_json", composite


def _read_index(storage: Any, key: str) -> dict[str, int]:
    raw = storage.get(key, "")
    return json.loads(str(raw)) if raw else {}


def _put_surface_index(storage: Any, document: dict[str, Any], record: MarkRecord) -> None:
    key, composite = _index_key(record.task_id, record.anchor.stable_key(record.hit_object_name))
    bucket = _read_index(storage, key)
    bucket.setdefault(composite, record.id)
    storage[key] = _json(bucket)
    if key not in document.setdefault("index_buckets", []):
        document["index_buckets"].append(key)


def _empty_task(task_id: str = DEFAULT_TASK_ID) -> dict[str, Any]:
    return {
        "id": task_id, "label": "当前标记任务", "intent": "unspecified",
        "status": "marking", "source": None, "mark_count": 0,
        "role_counts": {role: 0 for role in CORE_ROLES},
        "extensions": {},
    }


def _empty_document() -> dict[str, Any]:
    return {
        "schema": SCHEMA_NAME, "version": SCHEMA_VERSION,
        "document_id": uuid.uuid4().hex, "revision": 0,
        "next_mark_id": 1, "active_task_id": DEFAULT_TASK_ID,
        "chunk_size": CHUNK_SIZE, "chunks": [], "index_buckets": [],
        "tasks": {DEFAULT_TASK_ID: _empty_task()}, "extensions": {},
    }


def _read_document(storage: Any) -> dict[str, Any] | None:
    raw = storage.get(DOCUMENT_KEY, "")
    if not raw:
        return None
    value = json.loads(str(raw))
    if value.get("schema") != SCHEMA_NAME or int(value.get("version", 0)) > SCHEMA_VERSION:
        raise ValueError("unsupported semantic annotation document")
    return value


def _write_document(storage: Any, document: dict[str, Any]) -> None:
    document["revision"] = int(document.get("revision", 0)) + 1
    storage[DOCUMENT_KEY] = _json(document)


def _read_chunk(storage: Any, key: str) -> list[MarkRecord]:
    return loads_marks(str(storage.get(key, "")))


def _write_chunk(storage: Any, key: str, records: Iterable[MarkRecord]) -> None:
    storage[key] = dumps_marks(records)


def _task(document: dict[str, Any], task_id: str | None = None) -> dict[str, Any]:
    selected = task_id or document["active_task_id"]
    tasks = document.setdefault("tasks", {})
    return tasks.setdefault(selected, _empty_task(selected))


def ensure_document(storage: Any) -> dict[str, Any]:
    document = _read_document(storage)
    if document is not None:
        return document
    document = _empty_document()
    try:
        legacy = loads_marks(str(storage.get(MARKS_KEY, "")))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        legacy = []
    if legacy:
        migrated = [MarkRecord.from_mapping({**record.to_dict(), "task_id": DEFAULT_TASK_ID}) for record in legacy]
        _replace_chunks(storage, document, migrated)
        task = _task(document)
        for record in migrated:
            task["mark_count"] += 1
            counts = task["role_counts"]
            counts[record.role] = int(counts.get(record.role, 0)) + 1
        document["next_mark_id"] = max(record.id for record in migrated) + 1
        document["migrated_from"] = {"key": MARKS_KEY, "version": 1,
                                     "at": datetime.now(timezone.utc).isoformat()}
    _write_document(storage, document)
    return document


def document_summary(storage: Any) -> dict[str, Any]:
    document = ensure_document(storage)
    task = _task(document)
    return {
        "schema": document["schema"], "version": document["version"],
        "document_id": document["document_id"], "revision": document["revision"],
        "task_id": task["id"], "task_label": task["label"],
        "mark_count": int(task.get("mark_count", 0)),
        "role_counts": dict(task.get("role_counts", {})),
        "source": task.get("source"), "chunk_count": len(document.get("chunks", [])),
    }


def load_all_marks(storage: Any, task_id: str | None = None) -> list[MarkRecord]:
    document = ensure_document(storage)
    records = [record for key in document.get("chunks", []) for record in _read_chunk(storage, key)]
    selected = task_id
    if selected is None:
        return records
    return [record for record in records if record.task_id == selected]


def next_id(storage: Any) -> int:
    return int(ensure_document(storage)["next_mark_id"])


def set_active_source(storage: Any, snapshot: dict[str, Any]) -> None:
    document = ensure_document(storage)
    _task(document)["source"] = snapshot
    _write_document(storage, document)


def append_mark(storage: Any, record: MarkRecord) -> bool:
    return bool(append_marks(storage, [record]))


def append_marks(storage: Any, incoming: Iterable[MarkRecord]) -> list[MarkRecord]:
    """Append a brush batch with one document/index write per changed bucket.

    Brush events can cover dozens of narrow faces. Persisting every face as a
    separate transaction made viewport feedback progressively slower as the
    annotation set grew. This keeps the same duplicate semantics while making
    the whole event one storage transaction.
    """
    candidates = list(incoming)
    if not candidates:
        return []
    document = ensure_document(storage)
    bucket_cache: dict[str, dict[str, int]] = {}
    accepted: list[MarkRecord] = []
    for record in candidates:
        stable_key = record.anchor.stable_key(record.hit_object_name)
        index_key, composite = _index_key(record.task_id, stable_key)
        bucket = bucket_cache.setdefault(index_key, _read_index(storage, index_key))
        if composite in bucket:
            continue
        bucket[composite] = record.id
        accepted.append(record)
    if not accepted:
        return []

    chunks = document.setdefault("chunks", [])
    if chunks:
        key = chunks[-1]
        records = _read_chunk(storage, key)
    else:
        key, records = _chunk_key(0), []
        chunks.append(key)
    chunk_size = int(document.get("chunk_size", CHUNK_SIZE))
    for record in accepted:
        if len(records) >= chunk_size:
            _write_chunk(storage, key, records)
            key, records = _chunk_key(len(chunks)), []
            chunks.append(key)
        records.append(record)
        task = _task(document, record.task_id)
        task["mark_count"] = int(task.get("mark_count", 0)) + 1
        counts = task.setdefault("role_counts", {})
        counts[record.role] = int(counts.get(record.role, 0)) + 1
    _write_chunk(storage, key, records)
    for index_key, bucket in bucket_cache.items():
        storage[index_key] = _json(bucket)
        if index_key not in document.setdefault("index_buckets", []):
            document["index_buckets"].append(index_key)
    document["next_mark_id"] = max(
        int(document.get("next_mark_id", 1)),
        max(record.id for record in accepted) + 1,
    )
    _write_document(storage, document)
    return accepted


def pop_last_mark(storage: Any, task_id: str | None = None) -> MarkRecord | None:
    document = ensure_document(storage)
    selected = task_id or document["active_task_id"]
    chunks = document.get("chunks", [])
    for chunk_position in range(len(chunks) - 1, -1, -1):
        key = chunks[chunk_position]
        records = _read_chunk(storage, key)
        for record_position in range(len(records) - 1, -1, -1):
            record = records[record_position]
            if record.task_id != selected:
                continue
            records.pop(record_position)
            if records:
                _write_chunk(storage, key, records)
            else:
                _delete(storage, key)
                chunks.pop(chunk_position)
            task = _task(document, selected)
            task["mark_count"] = max(0, int(task.get("mark_count", 0)) - 1)
            counts = task.setdefault("role_counts", {})
            counts[record.role] = max(0, int(counts.get(record.role, 0)) - 1)
            index_key, composite = _index_key(record.task_id, record.anchor.stable_key(record.hit_object_name))
            bucket = _read_index(storage, index_key)
            if bucket.get(composite) == record.id:
                bucket.pop(composite, None)
                if bucket:
                    storage[index_key] = _json(bucket)
                else:
                    _delete(storage, index_key)
                    if index_key in document.setdefault("index_buckets", []):
                        document["index_buckets"].remove(index_key)
            _write_document(storage, document)
            return record
    return None


def clear_task_marks(storage: Any, task_id: str | None = None) -> list[MarkRecord]:
    document = ensure_document(storage)
    selected = task_id or document["active_task_id"]
    all_records = load_all_marks(storage)
    removed = [record for record in all_records if record.task_id == selected]
    kept = [record for record in all_records if record.task_id != selected]
    _replace_chunks(storage, document, kept)
    task = _task(document, selected)
    task["mark_count"] = 0
    task["role_counts"] = {role: 0 for role in CORE_ROLES}
    _write_document(storage, document)
    return removed


def replace_task_marks(
    storage: Any, task_id: str, task_records: Iterable[MarkRecord]
) -> None:
    """Atomically replace one task's marks and rebuild its compact indexes.

    Eraser strokes use this once on mouse release.  The live overlay can update
    while dragging without rewriting every storage chunk for every mouse event.
    Marks belonging to other tasks are kept verbatim.
    """
    replacement = list(task_records)
    if any(record.task_id != task_id for record in replacement):
        raise ValueError("replacement records must belong to the selected task")
    document = ensure_document(storage)
    all_records = load_all_marks(storage)
    kept = [record for record in all_records if record.task_id != task_id]
    _replace_chunks(storage, document, kept + replacement)
    task = _task(document, task_id)
    task["mark_count"] = len(replacement)
    task["role_counts"] = {role: 0 for role in CORE_ROLES}
    for record in replacement:
        counts = task["role_counts"]
        counts[record.role] = int(counts.get(record.role, 0)) + 1
    if replacement:
        document["next_mark_id"] = max(
            int(document.get("next_mark_id", 1)),
            max(record.id for record in replacement) + 1,
        )
    _write_document(storage, document)


def rewrite_all_marks(storage: Any, records: list[MarkRecord]) -> None:
    """Rewrite chunks/indexes while preserving task summaries and monotonic IDs."""
    document = ensure_document(storage)
    _replace_chunks(storage, document, records)
    if records:
        document["next_mark_id"] = max(int(document.get("next_mark_id", 1)),
                                       max(record.id for record in records) + 1)
    _write_document(storage, document)


def _replace_chunks(storage: Any, document: dict[str, Any], records: list[MarkRecord]) -> None:
    for key in tuple(document.get("chunks", [])):
        _delete(storage, key)
    document["chunks"] = []
    for key in tuple(document.get("index_buckets", [])):
        _delete(storage, key)
    document["index_buckets"] = []
    for start in range(0, len(records), int(document.get("chunk_size", CHUNK_SIZE))):
        key = _chunk_key(len(document["chunks"]))
        document["chunks"].append(key)
        _write_chunk(storage, key, records[start:start + int(document.get("chunk_size", CHUNK_SIZE))])
    for record in records:
        _put_surface_index(storage, document, record)
