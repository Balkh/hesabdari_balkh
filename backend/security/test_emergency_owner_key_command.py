from django.core.management.base import CommandError
from unittest.mock import patch

from security.management.commands.recover_gm_offline import _require_tty


class EmergencyRecoveryCommandBoundaryTests(__import__("django.test", fromlist=["SimpleTestCase"]).SimpleTestCase):
    def test_recovery_command_is_tty_only(self):
        with patch("security.management.commands.recover_gm_offline.sys.stdin.isatty", return_value=False):
            with self.assertRaises(CommandError):
                _require_tty()

    def test_invalid_owner_key_is_rejected_before_any_new_seed_is_displayed(self):
        from io import StringIO
        from django.core.management import call_command

        from security.management.commands import recover_gm_offline

        output = StringIO()
        with (
            patch.object(recover_gm_offline, "_require_tty"),
            patch.object(recover_gm_offline, "get_current_gm_for_local_operation", return_value=type("GM", (), {"user": type("User", (), {"get_username": lambda self: "gm"})()})()),
            patch.object(recover_gm_offline.getpass, "getpass", return_value="INVALID-OWNER-KEY"),
            self.assertRaises(CommandError),
        ):
            call_command("recover_gm_offline", stdout=output)
        self.assertNotIn("otpauth://", output.getvalue())
