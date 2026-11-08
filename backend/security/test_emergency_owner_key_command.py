from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase

from security.management.commands.issue_gm_emergency_owner_key import _require_tty as require_issue_tty
from security.management.commands.recover_gm_offline import _require_tty as require_recovery_tty


class EmergencyRecoveryCommandBoundaryTests(SimpleTestCase):
    def test_owner_key_rotation_command_refuses_non_tty(self):
        with patch("security.management.commands.issue_gm_emergency_owner_key.sys.stdin.isatty", return_value=False):
            with self.assertRaises(CommandError):
                require_issue_tty()

    def test_emergency_recovery_command_refuses_non_tty(self):
        with patch("security.management.commands.recover_gm_offline.sys.stdin.isatty", return_value=False):
            with self.assertRaises(CommandError):
                require_recovery_tty()

    def test_invalid_owner_key_is_rejected_before_new_totp_seed_is_shown(self):
        output = StringIO()
        gm = SimpleNamespace(user=SimpleNamespace(get_username=lambda: "gm"))
        with (
            patch("security.management.commands.recover_gm_offline._require_tty"),
            patch("security.management.commands.recover_gm_offline.get_current_gm_for_local_operation", return_value=gm),
            patch("security.management.commands.recover_gm_offline.getpass.getpass", return_value="INVALID-OWNER-KEY"),
            self.assertRaises(CommandError),
        ):
            call_command("recover_gm_offline", stdout=output)
        self.assertNotIn("otpauth://", output.getvalue())
        self.assertNotIn("REPLACEMENT OFFLINE GM EMERGENCY OWNER KEY", output.getvalue())
