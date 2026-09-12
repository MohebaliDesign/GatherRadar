import tempfile
import unittest
from pathlib import Path

from gatherradar.collectors.instagram_auth import (
    LoginFailedError,
    SessionInvalidError,
    SessionNotFoundError,
    create_session,
    load_authenticated_loader,
    session_path,
)


class FakeLoader:
    """Stand-in for instaloader.Instaloader matching only the methods GatherRadar
    calls, so tests never import or contact the real Instaloader/Instagram."""

    def __init__(
        self,
        *,
        login_error: Exception | None = None,
        load_error: Exception | None = None,
        test_login_error: Exception | None = None,
        verified_username: str | None = "davvvat",
    ) -> None:
        self._login_error = login_error
        self._load_error = load_error
        self._test_login_error = test_login_error
        self._verified_username = verified_username
        self.interactive_login_calls: list[str] = []
        self.load_session_calls: list[tuple[str, str]] = []
        self.save_session_calls: list[str] = []
        self.context = object()

    def interactive_login(self, username: str) -> None:
        self.interactive_login_calls.append(username)
        if self._login_error is not None:
            raise self._login_error

    def load_session_from_file(self, username: str, filename: str) -> None:
        self.load_session_calls.append((username, filename))
        if self._load_error is not None:
            raise self._load_error

    def test_login(self) -> str | None:
        if self._test_login_error is not None:
            raise self._test_login_error
        return self._verified_username

    def save_session_to_file(self, filename: str) -> None:
        self.save_session_calls.append(filename)
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        Path(filename).write_text("fake-session", encoding="utf-8")


class SessionPathTests(unittest.TestCase):
    def test_path_uses_lowercased_username(self) -> None:
        path = session_path("DavVVat", "data")
        self.assertEqual(path, Path("data") / "sessions" / "instagram-davvvat.session")

    def test_path_strips_whitespace(self) -> None:
        path = session_path("  davvvat  ", "data")
        self.assertEqual(path.name, "instagram-davvvat.session")

    def test_empty_username_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            session_path("   ", "data")

    def test_data_dir_is_respected(self) -> None:
        path = session_path("davvvat", "/tmp/custom-data")
        self.assertEqual(path, Path("/tmp/custom-data") / "sessions" / "instagram-davvvat.session")


class CreateSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)

    def test_successful_login_saves_and_verifies_the_session(self) -> None:
        fake = FakeLoader(verified_username="davvvat")

        path = create_session("davvvat", data_dir=self.data_dir, loader_factory=lambda: fake)

        self.assertEqual(path, session_path("davvvat", self.data_dir))
        self.assertEqual(fake.interactive_login_calls, ["davvvat"])
        self.assertEqual(fake.save_session_calls, [str(path)])
        self.assertTrue(path.exists())

    def test_login_username_is_case_insensitive_on_verification(self) -> None:
        fake = FakeLoader(verified_username="DavVVat")
        path = create_session("davvvat", data_dir=self.data_dir, loader_factory=lambda: fake)
        self.assertTrue(path.exists())

    def test_rejected_login_raises_login_failed(self) -> None:
        from instaloader import exceptions as instaloader_errors

        fake = FakeLoader(login_error=instaloader_errors.BadCredentialsException("bad creds"))

        with self.assertRaises(LoginFailedError):
            create_session("davvvat", data_dir=self.data_dir, loader_factory=lambda: fake)

    def test_verification_mismatch_raises_login_failed(self) -> None:
        fake = FakeLoader(verified_username="someoneelse")

        with self.assertRaises(LoginFailedError):
            create_session("davvvat", data_dir=self.data_dir, loader_factory=lambda: fake)

    def test_verification_returning_none_raises_login_failed(self) -> None:
        fake = FakeLoader(verified_username=None)

        with self.assertRaises(LoginFailedError):
            create_session("davvvat", data_dir=self.data_dir, loader_factory=lambda: fake)

    def test_no_session_file_is_written_when_login_fails(self) -> None:
        from instaloader import exceptions as instaloader_errors

        fake = FakeLoader(login_error=instaloader_errors.BadCredentialsException("bad creds"))
        with self.assertRaises(LoginFailedError):
            create_session("davvvat", data_dir=self.data_dir, loader_factory=lambda: fake)

        self.assertFalse(session_path("davvvat", self.data_dir).exists())


class LoadAuthenticatedLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)

    def _write_fake_session_file(self, username: str = "davvvat") -> Path:
        path = session_path(username, self.data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fake-session", encoding="utf-8")
        return path

    def test_missing_session_file_raises_session_not_found(self) -> None:
        with self.assertRaises(SessionNotFoundError):
            load_authenticated_loader("davvvat", data_dir=self.data_dir)

    def test_valid_session_is_loaded_and_returned(self) -> None:
        self._write_fake_session_file()
        fake = FakeLoader(verified_username="davvvat")

        loader = load_authenticated_loader(
            "davvvat", data_dir=self.data_dir, loader_factory=lambda: fake
        )

        self.assertIs(loader, fake)
        self.assertEqual(len(fake.load_session_calls), 1)

    def test_corrupt_session_file_raises_session_invalid(self) -> None:
        self._write_fake_session_file()
        fake = FakeLoader(load_error=EOFError("corrupt pickle"))

        with self.assertRaises(SessionInvalidError):
            load_authenticated_loader("davvvat", data_dir=self.data_dir, loader_factory=lambda: fake)

    def test_expired_session_fails_verification_and_raises_session_invalid(self) -> None:
        self._write_fake_session_file()
        fake = FakeLoader(verified_username=None)

        with self.assertRaises(SessionInvalidError):
            load_authenticated_loader("davvvat", data_dir=self.data_dir, loader_factory=lambda: fake)

    def test_session_belonging_to_another_account_raises_session_invalid(self) -> None:
        self._write_fake_session_file()
        fake = FakeLoader(verified_username="someone_else")

        with self.assertRaises(SessionInvalidError):
            load_authenticated_loader("davvvat", data_dir=self.data_dir, loader_factory=lambda: fake)

    def test_test_login_error_raises_session_invalid(self) -> None:
        self._write_fake_session_file()
        fake = FakeLoader(test_login_error=ConnectionError("network down"))

        with self.assertRaises(SessionInvalidError):
            load_authenticated_loader("davvvat", data_dir=self.data_dir, loader_factory=lambda: fake)


if __name__ == "__main__":
    unittest.main()
