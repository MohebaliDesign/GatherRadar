from __future__ import annotations

from pathlib import Path

import yaml

from .domain.source import Source, SourceType


def load_sources(path: str | Path = "config/sources.yaml") -> list[Source]:
    config_path = Path(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    defaults = payload.get("defaults") or {}
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list):
        raise ValueError("sources.yaml must contain a 'sources' list")

    sources: list[Source] = []
    seen_ids: set[str] = set()

    for raw in raw_sources:
        source = Source(
            id=raw["id"],
            publisher_key=raw["publisher_key"],
            name=raw["name"],
            source_type=SourceType(raw["type"]),
            url=raw["url"],
            enabled=raw.get("enabled", True),
            username=raw.get("username"),
            city_hint=raw.get("city_hint", defaults.get("city_hint")),
            timezone=raw.get("timezone", defaults.get("timezone", "Asia/Tehran")),
            locale=raw.get("locale", defaults.get("locale", "fa-IR")),
        )
        if source.id in seen_ids:
            raise ValueError(f"duplicate source id: {source.id}")
        seen_ids.add(source.id)
        sources.append(source)

    return sources
