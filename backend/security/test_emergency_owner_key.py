from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from security.emergency_owner_key_service import (
    EmergencyOwnerKeyInvalid,
    emergency_owner_key_digest,
    validate_current_gm_emergency_owner_key,
    generate_emergency_owner_key,
    issue_gm_emergency_owner_key,
    recover_existing_gm_offline,
)
from security.mfa import generate_totp_secret, totp_code
from security.mfa_models import (
    MFADeviceStatus,
    SecurityEmergencyOwnerKey,
    SecurityLoginSession,
    SecurityMFADevice,
    SecurityRecoveryCode,
)
from security.mfa_policy import is_active_gm_holder
from security.mfa_service import begin_mfa_enrollment, confirm_mfa_enrollment
from security.models import AuditEvent, GMRoleSlot, Role, UserRoleAssignment


class StaticMFAKeyProvider:
    def active_key_id(self):
        return "owner-key-test-v1"

    def get_key(self, key_id):
        if key_id != "owner-key-test-v1":
            raise KeyError(key_id)
        return b"Z" * 32


class EmergencyOwnerKeyLifecycleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="emergency-gm",
            password="Strong-old-GM-Password-2026!",
            is_active=True,
            is_staff=True,
            is_superuser=False,
        )
        role, _ = Role.objects.get_or_create(
            code="GM",
            defaults={"name": "General Manager", "is_active": True, "is_system": True},
        )
        assignment = UserRoleAssignment.objects.create(
            user=self.user,
            role=role,
            start_at=timezone.now() - timedelta(minutes=1),
            reason="test singleton GM",
        )
        slot = GMRoleSlot.objects.get(code="GM")
        slot.assignment = assignment
        slot.save(update_fields=["assignment", "updated_at"])
        self.assignment_id = assignment.pk
        self.slot_id = slot.pk
        self.provider = StaticMFAKeyProvider()
        self.now = timezone.now().replace(microsecond=0)
        started = begin_mfa_enrollment(self.user, provider=self.provider)
        self.old_secret = started["secret"]
        self.old_recovery_codes = confirm_mfa_enrollment(
            self.user,
            totp_code(self.old_secret, timestamp=self.now.timestamp()),
            provider=self.provider,
            at=self.now,
        )
        self.old_owner_key = generate_emergency_owner_key()
        self.old_owner_row = SecurityEmergencyOwnerKey.objects.create(
            scope=SecurityEmergencyOwnerKey.GM_RECOVERY,
            source=SecurityEmergencyOwnerKey.SOURCE_INITIAL_BOOTSTRAP,
            key_hash=emergency_owner_key_digest(self.old_owner_key),
            issued_at=self.now,
            issued_by=self.user,
        )
        self.session = SecurityLoginSession.objects.create(
            user=self.user,
            session_key_hash="a" * 64,
            slot_number=1,
            created_at=self.now,
            last_seen_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=15),
            absolute_expires_at=self.now + timedelta(hours=12),
        )

    def test_invalid_owner_key_changes_no_state(self):
        new_secret = generate_totp_secret()
        replacement_key = generate_emergency_owner_key()
        with self.assertRaises(EmergencyOwnerKeyInvalid):
            recover_existing_gm_offline(
                "A" * 43,
                new_owner_key=replacement_key,
                new_password="Strong-new-GM-Password-2026!",
                new_totp_secret=new_secret,
                new_totp_code=totp_code(new_secret, timestamp=self.now.timestamp()),
                provider=self.provider,
                at=self.now,
            )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Strong-old-GM-Password-2026!"))
        self.old_owner_row.refresh_from_db()
        self.assertIsNone(self.old_owner_row.consumed_at)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.revoked_at)
        self.assertEqual(GMRoleSlot.objects.get(code="GM").assignment_id, self.assignment_id)

    def test_emergency_recovery_preserves_gm_slot_and_replaces_all_factors(self):
        new_secret = __import__("security.mfa", fromlist=["generate_totp_secret"]).generate_totp_secret()
        new_owner_key = generate_emergency_owner_key()
        gm, new_codes, revoked_sessions, disabled_devices = recover_existing_gm_offline(
            self.old_owner_key,
            new_owner_key=new_owner_key,
            new_password="Strong-new-GM-Password-2026!",
            new_totp_secret=new_secret,
            new_totp_code=totp_code(new_secret, timestamp=self.now.timestamp()),
            provider=self.provider,
            at=self.now,
        )
        self.assertEqual(gm.pk, self.user.pk)
        self.assertTrue(gm.check_password("Strong-new-GM-Password-2026!"))
        self.assertFalse(gm.check_password("Strong-old-GM-Password-2026!"))
        self.assertEqual(len(new_codes), 10)
        self.assertEqual(revoked_sessions, 1)
        self.assertEqual(disabled_devices, 1)
        self.old_owner_row.refresh_from_db()
        self.assertIsNotNone(self.old_owner_row.consumed_at)
        replacement = SecurityEmergencyOwnerKey.objects.get(
            scope=SecurityEmergencyOwnerKey.GM_RECOVERY,
            consumed_at__isnull=True,
            revoked_at__isnull=True,
        )
        self.assertNotEqual(replacement.key_hash, self.old_owner_row.key_hash)
        self.assertEqual(replacement.key_hash, emergency_owner_key_digest(new_owner_key))
        self.assertEqual(replacement.source, SecurityEmergencyOwnerKey.SOURCE_EMERGENCY_RECOVERY)
        self.assertEqual(GMRoleSlot.objects.get(code="GM").assignment_id, self.assignment_id)
        self.assertTrue(is_active_gm_holder(gm, at=self.now))
        self.session.refresh_from_db()
        self.assertEqual(self.session.revoke_reason, "GM_EMERGENCY_RECOVERY")
        self.assertIsNotNone(self.session.revoked_at)
        self.assertEqual(
            SecurityMFADevice.objects.filter(user=gm, status=MFADeviceStatus.ACTIVE).count(),
            1,
        )
        self.assertTrue(
            SecurityMFADevice.objects.filter(
                user=gm,
                status=MFADeviceStatus.DISABLED,
            ).exists()
        )
        self.assertTrue(
            SecurityRecoveryCode.objects.filter(
                user=gm,
                used_at__isnull=False,
            ).count() >= 10
        )
        self.assertEqual(
            SecurityRecoveryCode.objects.filter(user=gm, used_at__isnull=True).count(),
            10,
        )
        event = AuditEvent.objects.filter(user=gm, entity="GM_EMERGENCY_RECOVERY").latest("id")
        self.assertEqual(event.new_state["gm_assignment_preserved"], self.assignment_id)
        self.assertEqual(event.new_state["gm_slot_preserved"], self.slot_id)
        self.assertNotIn(self.old_owner_key, str(event.new_state))
        self.assertNotIn(new_owner_key, str(event.new_state))

    def test_owner_key_rotation_requires_password_and_totp_and_preserves_old_key_on_failure(self):
        invalid_key = generate_emergency_owner_key()
        with self.assertRaises(EmergencyOwnerKeyInvalid):
            issue_gm_emergency_owner_key(
                self.user,
                password="wrong password",
                totp_code=totp_code(self.old_secret, timestamp=(self.now + timedelta(seconds=30)).timestamp()),
                provider=self.provider,
                new_owner_key=invalid_key,
                at=self.now + timedelta(seconds=30),
            )
        self.old_owner_row.refresh_from_db()
        self.assertIsNone(self.old_owner_row.revoked_at)

    def test_weak_new_password_is_rejected_before_any_recovery_state_changes(self):
        new_secret = __import__("security.mfa", fromlist=["generate_totp_secret"]).generate_totp_secret()
        with self.assertRaises(EmergencyOwnerKeyInvalid):
            recover_existing_gm_offline(
                self.old_owner_key,
                new_owner_key=generate_emergency_owner_key(),
                new_password="password",
                new_totp_secret=new_secret,
                new_totp_code=totp_code(new_secret, timestamp=self.now.timestamp()),
                provider=self.provider,
                at=self.now,
            )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Strong-old-GM-Password-2026!"))
        self.old_owner_row.refresh_from_db()
        self.assertIsNone(self.old_owner_row.consumed_at)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.revoked_at)

    def test_reusing_existing_owner_key_as_its_replacement_is_rejected(self):
        with self.assertRaises(EmergencyOwnerKeyInvalid):
            issue_gm_emergency_owner_key(
                self.user,
                password="Strong-old-GM-Password-2026!",
                totp_code=totp_code(self.old_secret, timestamp=(self.now + timedelta(seconds=30)).timestamp()),
                provider=self.provider,
                new_owner_key=self.old_owner_key,
                at=self.now + timedelta(seconds=30),
            )
        self.old_owner_row.refresh_from_db()
        self.assertIsNone(self.old_owner_row.revoked_at)
        self.assertEqual(
            SecurityEmergencyOwnerKey.objects.filter(
                scope=SecurityEmergencyOwnerKey.GM_RECOVERY,
                consumed_at__isnull=True,
                revoked_at__isnull=True,
            ).count(),
            1,
        )

    def test_invalid_new_totp_does_not_consume_owner_key_or_revoke_sessions(self):
        new_secret = __import__("security.mfa", fromlist=["generate_totp_secret"]).generate_totp_secret()
        with self.assertRaises(EmergencyOwnerKeyInvalid):
            recover_existing_gm_offline(
                self.old_owner_key,
                new_owner_key=generate_emergency_owner_key(),
                new_password="Strong-new-GM-Password-2026!",
                new_totp_secret=new_secret,
                new_totp_code="not-a-code",
                provider=self.provider,
                at=self.now,
            )
        self.old_owner_row.refresh_from_db()
        self.assertIsNone(self.old_owner_row.consumed_at)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.revoked_at)
        self.assertEqual(SecurityMFADevice.objects.filter(user=self.user, status=MFADeviceStatus.ACTIVE).count(), 1)

    def test_current_owner_key_validation_is_read_only_and_rejects_wrong_key(self):
        self.assertEqual(
            validate_current_gm_emergency_owner_key(self.old_owner_key, at=self.now),
            self.old_owner_row.pk,
        )
        with self.assertRaises(EmergencyOwnerKeyInvalid):
            validate_current_gm_emergency_owner_key("B" * 43, at=self.now)
        self.old_owner_row.refresh_from_db()
        self.assertIsNone(self.old_owner_row.consumed_at)
        self.assertIsNone(self.old_owner_row.revoked_at)

    def test_owner_key_rotation_revokes_old_key_and_keeps_only_one_live(self):
        now = self.now + timedelta(seconds=30)
        new_key = generate_emergency_owner_key()
        row = issue_gm_emergency_owner_key(
            self.user,
            password="Strong-old-GM-Password-2026!",
            totp_code=totp_code(self.old_secret, timestamp=now.timestamp()),
            provider=self.provider,
            new_owner_key=new_key,
            at=now,
        )
        self.old_owner_row.refresh_from_db()
        self.assertEqual(self.old_owner_row.revoke_reason, "ROTATED")
        self.assertIsNotNone(self.old_owner_row.revoked_at)
        self.assertEqual(row.key_hash, emergency_owner_key_digest(new_key))
        self.assertEqual(
            SecurityEmergencyOwnerKey.objects.filter(
                scope=SecurityEmergencyOwnerKey.GM_RECOVERY,
                consumed_at__isnull=True,
                revoked_at__isnull=True,
            ).count(),
            1,
        )
