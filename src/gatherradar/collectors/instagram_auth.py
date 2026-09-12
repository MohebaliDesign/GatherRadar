from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

# Authenticated session handling for the Instagram collector, isolated from the
# domain models per AGENTS.md. Passwords are never accepted as arguments, stored,
# or logged: Instaloader's own interactive_login() reads the password through
# getpass and keeps it only in memory for the login request.

LoaderFactory = Callable[[], Any]

SESSION_SUBDIR = "sessions"


class InstagramAuthError(Exception):
    """Base class for Instagram authentication/session failures."""


class LoginFailedError(InstagramAuthError):
    """Instagram refused the interactive login, or the session could not be verified
    immediately after logging in."""


class SessionNotFoundError(InstagramAuthError):
    """No local session file exists for the requested username."""


class SessionInvalidError(InstagramAuthError):
    """A local session file exists but failed to load or no longer authenticates."""


def session_path(username: str, data_dir: str | Path = "data") -> Path:
    """Deterministic local path for one account's saved Instaloader session.

    Matches the `data/sessions/instagram-<username>.session` layout.
    """
    normalized = (username or "").strip().lower()
    if not normalized:
        raise ValueError("username must not be empty")
    return Path(data_dir) / SESSION_SUBDIR / f"instagram-{normalized}.session"


def _default_loader_factory(*, quiet: bool) -> Any:
    import instaloader

    return instaloader.Instaloader(
        quiet=quiet,
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        iphone_support=False,
    )


def _usernames_match(expected: str, actual: str | None) -> bool:
    return isinstance(actual, str) and actual.strip().lower() == expected.strip().lower()


def create_session(
    username: str,
    *,
    data_dir: str | Path = "data",
    loader_factory: LoaderFactory | None = None,
) -> Path:
    """Interactively log in as `username` and save a reusable, verified session.

    The password is prompted for through Instaloader's interactive_login(), which
    uses getpass internally; it is never passed as an argument, written to a file,
    or logged. Raises LoginFailedError if Instagram refuses the login or the
    resulting session cannot be verified as belonging to `username`.
    """
    from instaloader import exceptions as instaloader_errors

    build_loader = loader_factory or (lambda: _default_loader_factory(quiet=False))
    loader = build_loader()
    path = session_path(username, data_dir)

    try:
        loader.interactive_login(username)
    except instaloader_errors.InstaloaderException as exc:
        raise LoginFailedError(f"Instagram login failed for @{username}: {exc}") from exc

    verified_username = loader.test_login()
    if not _usernames_match(username, verified_username):
        raise LoginFailedError(
            f"Instagram session for @{username} could not be verified after login"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    loader.save_session_to_file(str(path))
    return path


def load_authenticated_loader(
    username: str,
    *,
    data_dir: str | Path = "data",
    loader_factory: LoaderFactory | None = None,
) -> Any:
    """Load and verify a previously saved session for `username`.

    Raises SessionNotFoundError if no session file exists, or SessionInvalidError
    if the file exists but fails to load or no longer authenticates as `username`.
    Never attempts an anonymous request as a fallback.
    """
    path = session_path(username, data_dir)
    if not path.exists():
        raise SessionNotFoundError(f"no local Instagram session found at {path}")

    build_loader = loader_factory or (lambda: _default_loader_factory(quiet=True))
    loader = build_loader()

    try:
        loader.load_session_from_file(username, str(path))
    except Exception as exc:  # session files can fail to load in ways Instaloader
        # itself does not type consistently (corrupt pickle, permission errors, an
        # old format); any such failure means the session cannot be trusted.
        raise SessionInvalidError(
            f"Instagram session for @{username} could not be loaded: {exc}"
        ) from exc

    try:
        verified_username = loader.test_login()
    except Exception as exc:
        raise SessionInvalidError(
            f"Instagram session for @{username} failed verification: {exc}"
        ) from exc

    if not _usernames_match(username, verified_username):
        raise SessionInvalidError(
            f"Instagram session for @{username} is no longer valid or has expired"
        )

    return loader


__all__ = [
    "InstagramAuthError",
    "LoginFailedError",
    "SessionNotFoundError",
    "SessionInvalidError",
    "session_path",
    "create_session",
    "load_authenticated_loader",
]
