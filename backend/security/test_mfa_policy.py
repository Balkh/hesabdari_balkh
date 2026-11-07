from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from security.mfa_models import MFADeviceStatus, SecurityMFADevice, SecurityMFARequirement
from security.mfa_policy import set_employee_mfa_requirement, user_requires_mfa
from security.models import AuditAction, AuditEvent, GMRoleSlot, Role, UserRoleAssignment


class EmployeeMFAPolicyTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gm = User.objects.create_user(username="policy-gm")
        self.employee = User.objects.create_user(username="policy-employee")
        role, _ = Role.objects.get_or_create(
            code="GM", defaults={"name": "General Manager", "is_active": True}
        )
        assignment = UserRoleAssignment.objects.create(user=self.gm, role=role)
        slot = GMRoleSlot.objects.get(code="GM")
        slot.assignment = assignment
        slot.save(update_fields=["assignment", "updated_at"])

    def _active_device(self, user):
        SecurityMFADevice.objects.create(
            user=user,
            status=MFADeviceStatus.ACTIVE,
            secret_format_version=1,
            secret_key_id="test-only",
            secret_nonce=b"N" * 12,
            secret_ciphertext=b"C" * 16,
            confirmed_at=timezone.now(),
        )

    def test_gm_mfa_is_always_required_and_employee_is_optional_by_default(self):
        self.assertTrue(user_requires_mfa(self.gm))
        self.assertFalse(user_requires_mfa(self.employee))

    def test_only_gm_can_enable_employee_mfa_after_enrollment(self):
        self._active_device(self.employee)
        before = AuditEvent.objects.count()
        policy = set_employee_mfa_requirement(
            self.gm, self.employee, required=True, reason="security policy"
        )
        self.assertTrue(policy.is_required)
        self.assertTrue(user_requires_mfa(self.employee))
        audit = AuditEvent.objects.latest("id")
        self.assertEqual(audit.action, AuditAction.UPDATE)
        self.assertEqual(audit.entity, "MFA_REQUIREMENT")
        self.assertEqual(AuditEvent.objects.count(), before + 1)
        policy = set_employee_mfa_requirement(
            self.gm, self.employee, required=False, reason="policy changed"
        )
        self.assertFalse(policy.is_required)
        self.assertFalse(user_requires_mfa(self.employee))

    def test_employee_cannot_require_mfa_for_another_employee(self):
        self._active_device(self.employee)
        with self.assertRaises(PermissionDenied):
            set_employee_mfa_requirement(
                self.employee, self.gm, required=True, reason="unauthorized"
            )

    def test_mfa_cannot_be_required_before_device_enrollment(self):
        with self.assertRaises(ValidationError):
            set_employee_mfa_requirement(
                self.gm, self.employee, required=True, reason="enroll first"
            )
