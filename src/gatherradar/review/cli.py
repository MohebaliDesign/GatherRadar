"""Local command parsing and output only; the service owns pipeline behavior."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

from .models import ReviewError


def selection_arguments(parser: argparse.ArgumentParser) -> None:
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--source', action='append', dest='sources')
    selection.add_argument('--all-enabled', action='store_true')
    parser.add_argument('--config', default='config/sources.yaml')
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--days', type=int, default=14)
    parser.add_argument('--review-timezone', default='Asia/Tehran')
    parser.add_argument('--skip-instagram-evidence', action='store_true')
    parser.add_argument('--run-id')


def add_commands(subcommands: object) -> None:
    refresh = subcommands.add_parser('refresh', help='Collect and persist locally, then export review files. No Google.')
    selection_arguments(refresh)
    refresh.add_argument('--stored', action='store_true', help='Analyze local observations only; no collection, browser or OCR.')
    export = subcommands.add_parser('export', help='Regenerate artifacts offline from SQLite only.')
    export.add_argument('format', nargs='?', choices=('all','xlsx','csv','json','gemini'), default='all')
    export.add_argument('--run', default='latest')
    review = subcommands.add_parser('review', help='Offline review-state import.')
    review.add_argument('review_command', choices=('import',))
    status = subcommands.add_parser('status', help='Local persistence paths and run state; no network.')
    for parser in (refresh, export, review, status):
        parser.add_argument('--data-dir', default='data')
        parser.add_argument('--db', help='Default: <data-dir>/state/gatherradar.sqlite3')
        parser.add_argument('--workbook', help='Default: <data-dir>/review/GatherRadar.xlsx')
        parser.add_argument('--export-dir', help='Default: <data-dir>/exports')


def _print_import(result) -> None:
    print(f'Review import: imported={result.imported}; skipped={result.skipped}; malformed={result.malformed}; conflicts={result.conflicts}')


def run(args: argparse.Namespace) -> int:
    from ..storage.sqlite_repository import SqliteCanonicalRepository
    from .workspace import local_workspace
    root = Path(args.data_dir)
    database = Path(args.db) if args.db else root / 'state' / 'gatherradar.sqlite3'
    workbook = Path(args.workbook) if args.workbook else root / 'review' / 'GatherRadar.xlsx'
    exports = Path(args.export_dir) if args.export_dir else root / 'exports'
    try:
        with SqliteCanonicalRepository(database) as repository:
            if args.command == 'status':
                print(json.dumps(dict(repository.status(), workbook=str(workbook), exports=str(exports),
                    google='optional; use sheets status explicitly to contact Google'), ensure_ascii=False, indent=2))
                return 0
            if args.command == 'review':
                from ..exports.excel import ExcelReviewImporter
                if not workbook.exists():
                    raise ReviewError('Review workbook does not exist; choose --workbook or generate an export first.')
                with repository.state.lock():
                    imported = ExcelReviewImporter(workbook, repository).import_reviews()
                _print_import(imported)
                return int(bool(imported.malformed or imported.conflicts))
            kind = args.format if args.command == 'export' else 'all'
            workspace = local_workspace(repository, workbook, exports, kind)
            if args.command == 'export':
                with repository.state.lock():
                    # CSV/JSON/Gemini have no dependency on the XLSX library or file.
                    if kind in ('all','xlsx'):
                        _print_import(workspace.import_reviews())
                    paths, failures = workspace.export(args.run)
                for path in paths:
                    print(path)
                for failure in failures:
                    print(f'Export error: {failure}', file=sys.stderr)
                return int(bool(failures))
            from ..orchestration.refresh import RefreshService
            run_id = args.run_id or uuid4().hex
            print(f'Run id: {run_id}', flush=True)
            result = RefreshService(repository, import_reviews=workspace.import_reviews,
                export_reviews=workspace.export).run(tuple(args.sources or ()), all_enabled=args.all_enabled,
                config_path=args.config, data_dir=root, limit=args.limit, days=args.days,
                review_timezone=args.review_timezone, skip_instagram_evidence=args.skip_instagram_evidence,
                collect=not args.stored, run_id=run_id)
            snapshot = result.snapshot
            print(f'Status: {snapshot.status}; events={snapshot.events}; places={snapshot.places}; duplicates={snapshot.duplicates}')
            print(f'Filtered={snapshot.filtered}; undated={snapshot.undated}; already persisted={snapshot.already_synced}')
            if result.import_summary is not None:
                _print_import(result.import_summary)
            for source in result.sources:
                print(f'{source.source_id}: {source.status}; observed={len(source.observed_item_ids)}; failures={",".join(source.failures)}')
            print(f'Database: {database}\nWorkbook: {workbook}\nExports: {exports}\nGemini: {exports / "gemini/latest"}')
            for error in result.export_failures:
                print(f'Export error (canonical state committed): {error}', file=sys.stderr)
            return int(snapshot.status != 'success' or bool(result.export_failures))
    except (ReviewError, ValueError, OSError, sqlite3.Error) as exc:
        message = str(exc) if isinstance(exc, ReviewError) else 'Local operation failed. Check configuration, database and output paths; no raw exception was logged.'
        print(f'error: {message}', file=sys.stderr)
        return 1
