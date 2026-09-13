from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable, Sequence

from .collectors.base import CollectorError
from .collectors.instagram import DEFAULT_LIMIT, InstagramCollector
from .collectors.instagram_auth import InstagramAuthError, create_session_from_cookie
from .collectors.instagram_browser import authenticate_browser_profile, browser_profile_path
from .collectors.instagram_instaloader import InstaloaderPostFetcher
from .orchestration.collection_run import RunSummary, run_instagram_collection
from .storage.jsonl import StorageError

TRANSPORT_BROWSER = "browser"
TRANSPORT_INSTALOADER = "instaloader"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gatherradar",
        description="Collect public event content from approved GatherRadar sources.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    collect = subcommands.add_parser("collect", help="Run a collection for one source.")
    collect_kinds = collect.add_subparsers(dest="source_type", required=True)

    instagram = collect_kinds.add_parser("instagram", help="Collect one Instagram source.")
    instagram.add_argument("source_id", help="Source id from config/sources.yaml")
    instagram.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum recent posts to fetch (default: {DEFAULT_LIMIT})",
    )
    instagram.add_argument(
        "--config",
        default="config/sources.yaml",
        help="Path to the source registry (default: config/sources.yaml)",
    )
    instagram.add_argument(
        "--data-dir",
        default="data",
        help="Root directory for local runtime data (default: data)",
    )
    instagram.add_argument(
        "--transport",
        choices=(TRANSPORT_BROWSER, TRANSPORT_INSTALOADER),
        default=TRANSPORT_BROWSER,
        help="Collection transport (default: browser). 'instaloader' is the legacy "
        "transport, kept only while the browser transport is validated.",
    )

    auth = subcommands.add_parser(
        "auth", help="Create and verify an authenticated session for a source type."
    )
    auth_kinds = auth.add_subparsers(dest="auth_type", required=True)

    auth_instagram = auth_kinds.add_parser(
        "instagram",
        help="Open Chrome with the GatherRadar browser profile and log in to Instagram manually.",
    )
    auth_instagram.add_argument(
        "--data-dir",
        default="data",
        help="Root directory for local runtime data (default: data)",
    )
    auth_instagram.add_argument(
        "--legacy-cookie",
        action="store_true",
        help="Use the legacy Instaloader Cookie-header import instead of the browser profile.",
    )

    return parser


def format_summary(summary: RunSummary) -> str:
    source = summary.source
    lines = [
        "GatherRadar collection run",
        "",
        f"Run id: {summary.run_id}",
        f"Source: {source.name}",
        f"Username: @{source.username}",
        "",
        f"Observed: {summary.observed}",
        f"New: {summary.new}",
        f"Changed: {summary.changed}",
        f"Existing: {summary.already_existing}",
        f"Failed: {summary.failed}",
    ]

    if summary.failure_reasons:
        lines.append("")
        lines.append("Skipped items:")
        lines.extend(f"  - {reason}" for reason in summary.failure_reasons)

    lines.append("")
    lines.append("Saved:")
    lines.append(str(summary.output_path))
    return "\n".join(lines)


def format_auth_success(username: str) -> str:
    return "\n".join(
        [
            f"Authenticated as @{username}",
            "Session saved successfully.",
        ]
    )


def format_browser_auth_success() -> str:
    return "\n".join(
        [
            "Instagram browser session verified.",
            "Persistent profile saved.",
        ]
    )


def _wait_for_browser_login() -> None:
    print()
    print("Log in to Instagram in the opened Chrome window.")
    print("When the Instagram home page is visible, return here and press Enter.")
    input()
    print("Verifying session...")


def run_auth_instagram_browser(
    *, data_dir: str, wait_for_user: Callable[[], None] | None = None
) -> int:
    wait = wait_for_user if wait_for_user is not None else _wait_for_browser_login
    print("GatherRadar Instagram authentication")
    print()
    print("Opening Chrome with the GatherRadar browser profile:")
    print(browser_profile_path(data_dir))

    try:
        authenticate_browser_profile(data_dir=data_dir, wait_for_user=wait)
    except CollectorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("error: Instagram authentication was cancelled.", file=sys.stderr)
        return 1

    print()
    print(format_browser_auth_success())
    return 0


def _prompt_for_cookie() -> str:
    # getpass keeps the pasted Cookie header out of the terminal echo and, unlike a
    # CLI argument, out of shell history.
    return getpass.getpass("Paste Instagram Cookie header: ")


def run_auth_instagram_cookie(
    *, data_dir: str, cookie_prompt: Callable[[], str] | None = None
) -> int:
    prompt = cookie_prompt if cookie_prompt is not None else _prompt_for_cookie
    print("GatherRadar Instagram authentication (legacy cookie import)")
    cookie_header = prompt()

    print()
    print("Verifying session...")
    try:
        username, _session_path = create_session_from_cookie(cookie_header, data_dir=data_dir)
    except InstagramAuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print()
    print(format_auth_success(username))
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    _cookie_prompt: Callable[[], str] | None = None,
    _wait_for_user: Callable[[], None] | None = None,
) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "auth":
        if args.legacy_cookie:
            return run_auth_instagram_cookie(data_dir=args.data_dir, cookie_prompt=_cookie_prompt)
        return run_auth_instagram_browser(data_dir=args.data_dir, wait_for_user=_wait_for_user)

    if args.limit < 1:
        print("error: --limit must be a positive integer", file=sys.stderr)
        return 2

    collector = None
    if args.transport == TRANSPORT_INSTALOADER:
        collector = InstagramCollector(fetch_posts=InstaloaderPostFetcher(data_dir=args.data_dir))

    try:
        summary = run_instagram_collection(
            args.source_id,
            config_path=args.config,
            data_dir=args.data_dir,
            limit=args.limit,
            collector=collector,
        )
    except (CollectorError, StorageError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"error: source registry not found: {exc}", file=sys.stderr)
        return 1

    print(format_summary(summary))
    return 0
