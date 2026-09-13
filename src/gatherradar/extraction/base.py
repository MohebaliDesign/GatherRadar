from __future__ import annotations

from typing import Protocol

from .models import ExtractedEventFacts, ExtractionInput


class ExtractionError(Exception):
    """Base class for failures at the event extraction provider boundary."""


class ProviderExtractionError(ExtractionError):
    """The provider could not produce a result, e.g. it was unavailable or refused.

    Provider adapters translate their own library and network errors into this type so
    they never leak into the rest of GatherRadar. Messages must not contain secrets.
    """


class InvalidExtractionOutputError(ExtractionError):
    """The provider's output violates the ExtractedEventFacts contract."""


class EventExtractionProvider(Protocol):
    """Semantic interpretation of one source observation in a single operation.

    `extract` decides whether the input describes or announces a concrete attendable
    event and returns the source-supported facts together. Implementations raise only
    ProviderExtractionError or InvalidExtractionOutputError. `name` identifies the
    provider for run reporting; it never affects candidate identity.
    """

    name: str

    def extract(self, extraction_input: ExtractionInput) -> ExtractedEventFacts: ...
