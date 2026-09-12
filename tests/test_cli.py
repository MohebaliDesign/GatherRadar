import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from gatherradar.cli import build_parser, main
from gatherradar.collectors.instagram_auth import InstagramAuthError


class AuthArgumentParsingTests(unittest.TestCase):
    def test_auth_instagram_parses_username(self) -> None:
        args = build_parser().parse_args(["auth", "instagram", "davvvat"])

        self.assertEqual(args.command, "auth")
        self.assertEqual(args.auth_type, "instagram")
        self.assertEqual(args.username, "davvvat")
        self.assertEqual(args.data_dir, "data")

    def test_auth_instagram_accepts_custom_data_dir(self) -> None:
        args = build_parser().parse_args(
            ["auth", "instagram", "davvvat", "--data-dir", "custom-data"]
        )
        self.assertEqual(args.data_dir, "custom-data")

    def test_auth_requires_a_source_type(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["auth"])

    def test_auth_instagram_requires_a_username(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["auth", "instagram"])

    def test_collect_command_is_unaffected(self) -> None:
        args = build_parser().parse_args(["collect", "instagram", "davvvat_instagram"])
        self.assertEqual(args.command, "collect")
        self.assertEqual(args.source_id, "davvvat_instagram")


class AuthCommandDispatchTests(unittest.TestCase):
    def test_successful_auth_reports_the_saved_session_path(self) -> None:
        saved_path = Path("data") / "sessions" / "instagram-davvvat.session"

        with mock.patch("gatherradar.cli.create_session", return_value=saved_path) as create:
            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = main(["auth", "instagram", "davvvat"])

        create.assert_called_once_with("davvvat", data_dir="data")
        self.assertEqual(exit_code, 0)
        self.assertIn("davvvat", out.getvalue())
        self.assertIn(str(saved_path), out.getvalue())

    def test_failed_auth_reports_the_error_and_does_not_raise(self) -> None:
        with mock.patch(
            "gatherradar.cli.create_session",
            side_effect=InstagramAuthError("Instagram login failed for @davvvat: bad creds"),
        ):
            err = io.StringIO()
            with redirect_stderr(err):
                exit_code = main(["auth", "instagram", "davvvat"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Instagram login failed", err.getvalue())

    def test_never_contacts_instagram_during_this_test(self) -> None:
        # Guards against a future edit accidentally wiring main() straight to the
        # real Instaloader login instead of going through create_session().
        with mock.patch("gatherradar.cli.create_session") as create:
            create.return_value = Path("data/sessions/instagram-davvvat.session")
            with redirect_stdout(io.StringIO()):
                main(["auth", "instagram", "davvvat", "--data-dir", "custom-data"])

        create.assert_called_once_with("davvvat", data_dir="custom-data")


if __name__ == "__main__":
    unittest.main()
