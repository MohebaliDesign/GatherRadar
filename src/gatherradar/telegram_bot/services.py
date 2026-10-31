"""Application boundary used by the Telegram handlers.

Phase 1 implements only the read-only source catalog over the existing
`config.load_sources`. Later operations are declared as one protocol so a
Telegram handler never reaches collectors, OCR or exporters directly; their
implementation must reuse `RefreshService`, existing source validation, the
SQLite repository and the existing exporters (no second database, event model
or export path). Adding a source never implies that an arbitrary website is
supported: unknown layouts need an adapter, and robots/access policy applies.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from ..config import load_sources
from ..domain import SourceType


@dataclass(frozen=True)
class SourceView:
    """What the owner may see about one configured source (no local paths)."""

    id: str
    name: str
    kind: str  # 'instagram' | 'website'
    enabled: bool
    disabled_reason: str | None
    public_url: str


class SourceCatalog:
    """Read-only view of `config/sources.yaml` in its configured order."""

    def __init__(self, config_path: str | Path = 'config/sources.yaml') -> None:
        self.config_path = Path(config_path)

    def list(self) -> tuple[SourceView, ...]:
        views = []
        for source in load_sources(self.config_path):
            parts = urlsplit(source.url)
            views.append(SourceView(
                id=source.id, name=source.name,
                kind='instagram' if source.source_type is SourceType.INSTAGRAM else 'website',
                enabled=bool(source.enabled), disabled_reason=source.disabled_reason,
                # Query strings and fragments are dropped; the registry URL is public.
                public_url=urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))))
        return tuple(views)

    def get(self, source_id: str) -> SourceView | None:
        return next((view for view in self.list() if view.id == source_id), None)


class PlannedFeature(str, Enum):
    """Menu entries that are visible but not implemented in Phase 1."""

    CRAWL_ALL = 'crawl_all'
    SELECT_SOURCES = 'select_sources'
    MANAGE_SOURCES = 'manage_sources'
    EXPORTS = 'exports'
    RUNS = 'runs'
    SETTINGS = 'settings'


class GatherRadarOperations(Protocol):
    """Phase 2+ boundary; every call is owner-authorized by the caller.

    Implementations wrap existing services and run at most one job at a time.
    """

    def collect_all_enabled(self) -> str: ...  # job id; RefreshService(all_enabled=True)
    def collect_sources(self, source_ids: tuple[str, ...]) -> str: ...  # single or multi-source
    def cancel_job(self, job_id: str) -> bool: ...
    def job_status(self, job_id: str) -> dict: ...
    def recent_runs(self, limit: int = 5) -> tuple[dict, ...]: ...  # repository.load / manifests
    def validate_source(self, url: str) -> dict: ...  # robots + adapter support, no write
    def register_source(self, definition: dict) -> str: ...
    def set_source_enabled(self, source_id: str, enabled: bool) -> None: ...  # reversible, never delete
    def workbook_path(self, run_id: str = 'latest') -> Path: ...  # existing XLSX export
    def event_list(self, run_id: str = 'latest', limit: int = 20) -> tuple[dict, ...]: ...
