import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from gatherradar.cli import build_parser, main
from gatherradar.collectors.instagram_auth import InstagramAuthError

FAKE_COOKIE = "sessionid=super-secret-value; csrftoken=xyz789"


class AuthArgumentParsingTests(unittest.TestCase):
    def test_auth_instagram_takes_no_username(self) -> None:
        args = build_parser().parse_args(["auth", "instagram"])

        self.assertEqual(args.command, "auth")
        self.assertEqual(args.auth_type, "instagram")
        self.assertFalse(hasattr(args, "username"))
        self.assertEqual(args.data_dir, "data")

    def test_auth_instagram_accepts_custom_data_dir(self) -> None:
        args = build_parser().parse_args(["auth", "instagram", "--data-dir", "custom-data"])
        self.assertEqual(args.data_dir, "custom-data")

    def test_auth_requires_a_source_type(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["auth"])

    def test_auth_instagram_rejects_a_positional_username(self) -> None:
        # The auth command must not accept a target/login username as an argument:
        # the login account is discovered from the verified cookie, not typed in.
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["auth", "instagram", "davvvat"])

    def test_collect_command_is_unaffected(self) -> None:
        args = build_parser().parse_args(["collect", "instagram", "davvvat_instagram"])
        self.assertEqual(args.command, "collect")
        self.assertEqual(args.source_id, "davvvat_instagram")


class AuthCommandDispatchTests(unittest.TestCase):
    def test_successful_auth_reports_the_authenticated_username(self) -> None:
        saved_path = Path("data") / "sessions" / "instagram-instaloader.crawler.session"

        with mock.patch(
            "gatherradar.cli.create_session_from_cookie",
            return_value=("instaloader.crawler", saved_path),
        ) as create:
            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = main(["auth", "instagram"], _cookie_prompt=lambda: FAKE_COOKIE)

        create.assert_called_once_with(FAKE_COOKIE, data_dir="data")
        self.assertEqual(exit_code, 0)
        self.assertIn("Authenticated as @instaloader.crawler", out.getvalue())
        self.assertIn("Session saved successfully.", out.getvalue())

    def test_failed_auth_reports_the_error_and_does_not_raise(self) -> None:
        with mock.patch(
            "gatherradar.cli.create_session_from_cookie",
            side_effect=InstagramAuthError("Instagram did not accept the pasted cookie"),
        ):
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = main(["auth", "instagram"], _cookie_prompt=lambda: FAKE_COOKIE)

        self.assertEqual(exit_code, 1)
        self.assertIn("Instagram did not accept the pasted cookie", err.getvalue())

    def test_never_contacts_instagram_during_this_test(self) -> None:
        # Guards against a future edit accidentally wiring main() straight to a real
        # Instaloader login instead of going through create_session_from_cookie().
        with mock.patch("gatherradar.cli.create_session_from_cookie") as create:
            create.return_value = ("instaloader.crawler", Path("data/sessions/x.session"))
            with redirect_stdout(io.StringIO()):
                main(
                    ["auth", "instagram", "--data-dir", "custom-data"],
                    _cookie_prompt=lambda: FAKE_COOKIE,
                )

        create.assert_called_once_with(FAKE_COOKIE, data_dir="custom-data")

    def test_no_secret_value_appears_in_cli_output(self) -> None:
        with mock.patch(
            "gatherradar.cli.create_session_from_cookie",
            return_value=("instaloader.crawler", Path("data/sessions/x.session")),
        ):
            out = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                main(["auth", "instagram"], _cookie_prompt=lambda: FAKE_COOKIE)

        self.assertNotIn("super-secret-value", out.getvalue())
        self.assertNotIn("super-secret-value", err.getvalue())
        self.assertNotIn(FAKE_COOKIE, out.getvalue())

    def test_default_prompt_uses_getpass_so_the_cookie_is_never_echoed(self) -> None:
        with (
            mock.patch("gatherradar.cli.getpass.getpass", return_value=FAKE_COOKIE) as getpass_call,
            mock.patch(
                "gatherradar.cli.create_session_from_cookie",
                return_value=("instaloader.crawler", Path("data/sessions/x.session")),
            ) as create,
        ):
            with redirect_stdout(io.StringIO()):
                main(["auth", "instagram"])

        getpass_call.assert_called_once()
        create.assert_called_once_with(FAKE_COOKIE, data_dir="data")


if __name__ == "__main__":
    unittest.main()
