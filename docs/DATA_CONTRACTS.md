# GatherRadar Data Contracts

This document defines the four records used by the MVP pipeline. Collectors may change, but these boundaries should remain stable unless the product contract changes.

```text
Source → RawItem → EventCandidate → Event
```

## Source

A configured place GatherRadar is allowed to inspect. A website and Instagram account for the same publisher are separate sources and share a `publisher_key`.

Key fields: stable `id`, `publisher_key`, `source_type`, canonical `url`, optional Instagram `username`, `enabled`, locale/timezone, and optional `city_hint`.

## RawItem

A source observation before semantic interpretation. Website collectors and Instagram collectors must both produce this same shape.

Key fields: source identity, source-native `external_id`, `content_type`, direct `content_url`, untouched `raw_text`, publication/capture timestamps, author, optional image URL, and adapter-specific `raw_metadata`.

Raw items are intended for append-friendly JSONL storage during the MVP. They are evidence and debugging material, not the final event list.

## EventCandidate

The result of event detection and extraction before deterministic normalization and final persistence. It may be incomplete or uncertain.

It preserves source wording such as `source_date_text` and `price_text`, plus extracted fields and `extraction_confidence`. A candidate can explicitly be `is_event = false`.

## Event

The normalized canonical record used for filtering, deduplication, review, and later Google Sheets export.

It stores normalized event facts, review/status fields, provenance (`canonical_source_url`, `source_item_ids`), first/last seen timestamps, and human review notes.

## Storage boundary

```text
RawItem        → JSONL (planned)
EventCandidate → transient / processing boundary
Event          → SQLite (planned)
Google Sheets  → review/output surface, not source of truth
```

Unknown values remain null. GatherRadar must not invent missing dates, venues, prices, or registration details. Every material event fact must remain traceable to source evidence.
