from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from security.mfa import totp_code
from security.mfa_models import (
    MFADeviceStatus,
    SecurityBootstrapToken,
    SecurityMFADevice,
    SecurityRecoveryCode,
)
from security.gm_slot import claim_gm_slot
from security.models import AuditEvent, GMRoleSlot, Role, UserRoleAssignment


class ProviderStub:
    def active_key_id(self):
        return "test-gm-bootstrap-key"

    def get_key(self, key_id):
        if key_id != "test-gm-bootstrap-key":
            raise KeyError(key_id)
        return b"B" * 32


@override_settings(ERP_MFA_KEY_PROVIDER="security.test_gm_bootstrap.ProviderStub")
class InitialGMBootstrapCommandTests(TestCase):
    def setUp(self):
        self.gm_role, _ = Role.objects.get_or_create(
            code="GM",
            defaults={"name": "General Manager", "is_active": True, "is_system": True},
        )

    def _issue_token(self):
        output = StringIO()
        with patch("security.management.commands.issue_gm_bootstrap_token._require_tty"):
            call_command("issue_gm_bootstrap_token", stdout=output)
        marker = "ONE-TIME INITIAL GM BOOTSTRAP TOKEN (valid for 10 minutes):\\n"
        self.assertIn(marker, output.getvalue())
        return output.getvalue().split(marker, 1)[1].splitlines()[0].strip()

    def _otp_from_output(self, output, at):
        text = output.getvalue()
        uri = next(line for line in text.splitlines() if line.startswith("otpauth://totp/"))
        secret = parse_qs(urlparse(uri).query)["secret"][0]
        return totp_code(secret, timestamp=at.timestamp())

    def test_issue_command_persists_only_hash_and_ten_minute_expiry(self):
        raw = self._issue_token()
        row = SecurityBootstrapToken.objects.get(purpose=SecurityBootstrapToken.INITIAL_GM)
        self.assertEqual(len(row.token_hash), 64)
        self.assertNotEqual(row.token_hash, raw)
        self.assertEqual(row.expires_at - row.issued_at, timedelta(minutes=10))
        self.assertNotIn(raw, row.token_hash)

    def test_bootstrap_creates_the_first_gm_only_after_totp_confirmation(self):
        raw_token = self._issue_token()
        now = timezone.now() + timedelta(seconds=2)
        output = StringIO()
        calls = iter([raw_token, "Strong-GM-Password-2026!", "Strong-GM-Password-2026!"])

        def hidden_prompt(_prompt):
            try:
                return next(calls)
            except StopIteration:
                return self._otp_from_output(output, now)

        with (
            patch("security.management.commands.bootstrap_gm._require_tty"),
            patch("security.management.commands.bootstrap_gm.getpass.getpass", side_effect=hidden_prompt),
            patch("builtins.input", return_value="initial-gm"),
            patch("security.management.commands.bootstrap_gm.timezone.now", return_value=now),
        ):
            call_command("bootstrap_gm", stdout=output)

        User = get_user_model()
        gm = User.objects.get(username="initial-gm")
        self.assertTrue(gm.is_active)
        self.assertTrue(gm.is_staff)
        self.assertFalse(gm.is_superuser)
        slot = GMRoleSlot.objects.get(code="GM")
        self.assertEqual(slot.assignment.user_id, gm.pk)
        device = SecurityMFADevice.objects.get(user=gm)
        self.assertEqual(device.status, MFADeviceStatus.ACTIVE)
        self.assertEqual(
            SecurityRecoveryCode.objects.filter(user=gm, used_at__isnull=True).count(),
            10,
        )
        token = SecurityBootstrapToken.objects.get(purpose=SecurityBootstrapToken.INITIAL_GM)
        self.assertIsNotNone(token.consumed_at)
        self.assertIn("Initial GM bootstrap succeeded", output.getvalue())
        self.assertEqual(
            AuditEvent.objects.filter(user=gm, entity="GM_BOOTSTRAP").count(),
            1,
        )

    def test_invalid_totp_rolls_back_user_and_does_not_consume_token(self):
        raw_token = self._issue_token()
        now = timezone.now() + timedelta(seconds=2)
        output = StringIO()
        calls = iter([raw_token, "Strong-GM-Password-2026!", "Strong-GM-Password-2026!", "not-a-code"])
        with (
            patch("security.management.commands.bootstrap_gm._require_tty"),
            patch("security.management.commands.bootstrap_gm.getpass.getpass", side_effect=lambda _p: next(calls)),
            patch("builtins.input", return_value="bad-bootstrap-gm"),
            patch("security.management.commands.bootstrap_gm.timezone.now", return_value=now),
            self.assertRaises(CommandError),
        ):
            call_command("bootstrap_gm", stdout=output)

        self.assertFalse(get_user_model().objects.filter(username="bad-bootstrap-gm").exists())
        token = SecurityBootstrapToken.objects.get(purpose=SecurityBootstrapToken.INITIAL_GM)
        self.assertIsNone(token.consumed_at)
        self.assertIsNone(GMRoleSlot.objects.get(code="GM").assignment_id)

    def test_second_initial_bootstrap_is_refused_without_overwriting_holder(self):
        holder = get_user_model().objects.create_user(
            username="already-provisioned-gm",
            password="Strong-GM-Password-2026!",
        )
        assignment = UserRoleAssignment.objects.create(
            user=holder,
            role=self.gm_role,
            start_at=timezone.now(),
            reason="existing owner-approved GM",
        )
        claim_gm_slot(assignment)
        with patch("security.management.commands.issue_gm_bootstrap_token._require_tty"):
            with self.assertRaises(CommandError):
                call_command("issue_gm_bootstrap_token", stdout=StringIO())
        self.assertEqual(GMRoleSlot.objects.get(code="GM").assignment.user_id, holder.pk)
