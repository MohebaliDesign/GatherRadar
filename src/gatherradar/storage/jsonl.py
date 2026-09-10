from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain import RawItem


class StorageError(Exception):
    """Raised when raw items cannot be read from or written to local storage."""


@dataclass(frozen=True, slots=True)
class StoreOutcome:
    path: Path
    new: int
    changed: int
    already_existing: int


def raw_item_to_dict(item: RawItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "source_id": item.source_id,
        "source_type": item.source_type.value,
        "external_id": item.external_id,
        "content_type": item.content_type,
        "content_url": item.content_url,
        "raw_text": item.raw_text,
        "captured_at": item.captured_at.isoformat(),
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "author": item.author,
        "image_url": item.image_url,
        "content_hash": item.content_hash,
        "raw_metadata": item.raw_metadata,
    }


class JsonlRawItemStore:
    """Append-only JSONL storage keyed by RawItem id.

    Raw observations are never overwritten or deleted. When a rerun sees an id whose
    content hash has changed since the last stored observation (e.g. an organizer
    edited a caption), a new line is appended to the same file rather than mutating
    history, so both the original and the edited wording remain on record. `existing_ids`
    and the "already existing" count only consider the most recently stored observation
    of each id, so an old, superseded content hash does not stop a genuinely new edit
    from being recorded again in the future if the content reverts.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def _read_records(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []

        try:
            content = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"could not read {self._path}: {exc}") from exc

        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise StorageError(
                    f"{self._path} is not valid JSONL at line {line_number}: {exc.msg}. "
                    "Repair or remove the file before rerunning."
                ) from exc
            if isinstance(payload, dict):
                records.append(payload)
        return records

    def existing_ids(self) -> set[str]:
        return {
            payload["id"]
            for payload in self._read_records()
            if isinstance(payload.get("id"), str) and payload["id"]
        }

    def _latest_hashes(self) -> dict[str, str]:
        """id -> content_hash of the most recently stored observation for that id.
        Later lines win, since raw observations are appended in run order."""
        latest: dict[str, str] = {}
        for payload in self._read_records():
            item_id = payload.get("id")
            content_hash = payload.get("content_hash")
            if isinstance(item_id, str) and item_id and isinstance(content_hash, str):
                latest[item_id] = content_hash
        return latest

    def append_new(self, items: Iterable[RawItem]) -> StoreOutcome:
        """Classify each item against the most recently stored observation with the
        same id, then append the new and changed ones. Reruns of unchanged content
        stay idempotent; edited content is appended as a new, auditable observation."""
        known_hashes = self._latest_hashes()
        to_write: list[RawItem] = []
        new_count = 0
        changed_count = 0
        already_existing = 0

        for item in items:
            prior_hash = known_hashes.get(item.id)
            if prior_hash is None:
                new_count += 1
                to_write.append(item)
            elif prior_hash != item.content_hash:
                changed_count += 1
                to_write.append(item)
            else:
                already_existing += 1
                continue
            known_hashes[item.id] = item.content_hash

        if to_write:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                    for item in to_write:
                        handle.write(json.dumps(raw_item_to_dict(item), ensure_ascii=False))
                        handle.write("\n")
            except OSError as exc:
                raise StorageError(f"could not write {self._path}: {exc}") from exc

        return StoreOutcome(
            path=self._path,
            new=new_count,
            changed=changed_count,
            already_existing=already_existing,
        )
