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
        "raw_metadata": item.raw_metadata,
    }


class JsonlRawItemStore:
    """Append-only JSONL storage keyed by RawItem id."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def existing_ids(self) -> set[str]:
        if not self._path.exists():
            return set()

        ids: set[str] = set()
        try:
            content = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"could not read {self._path}: {exc}") from exc

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
            item_id = payload.get("id") if isinstance(payload, dict) else None
            if isinstance(item_id, str) and item_id:
                ids.add(item_id)
        return ids

    def append_new(self, items: Iterable[RawItem]) -> StoreOutcome:
        """Append items whose ids are not already stored. Reruns stay idempotent."""
        seen = self.existing_ids()
        new_items: list[RawItem] = []
        already_existing = 0

        for item in items:
            if item.id in seen:
                already_existing += 1
                continue
            seen.add(item.id)
            new_items.append(item)

        if new_items:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                    for item in new_items:
                        handle.write(json.dumps(raw_item_to_dict(item), ensure_ascii=False))
                        handle.write("\n")
            except OSError as exc:
                raise StorageError(f"could not write {self._path}: {exc}") from exc

        return StoreOutcome(
            path=self._path,
            new=len(new_items),
            already_existing=already_existing,
        )
