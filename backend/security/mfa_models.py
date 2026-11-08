"""Durable W0-2C MFA credential and authenticated-session records.

Only encrypted TOTP envelopes and one-way recovery-code hashes are stored.
Raw TOTP secrets, recovery codes, Django session keys, and bearer credentials
must never be persisted in these tables.
"""
from django.conf import settings
from django.db import models
from django.db.models import F, Q


class MFADeviceStatus(models.TextChoices):
    PENDING = "PENDING", "Pending enrollment"
    ACTIVE = "ACTIVE", "Active"
    DISABLED = "DISABLED", "Disabled"


class SecurityMFADevice(models.Model):
    """Encrypted TOTP credential bound to one user identity."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="security_mfa_devices",
    )
    status = models.CharField(
        max_length=10,
        choices=MFADeviceStatus.choices,
        default=MFADeviceStatus.PENDING,
    )
    secret_format_version = models.PositiveSmallIntegerField(default=1)
    secret_key_id = models.CharField(max_length=100)
    secret_nonce = models.BinaryField(max_length=12)
    secret_ciphertext = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_accepted_counter = models.BigIntegerField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(status=MFADeviceStatus.ACTIVE),
                name="security_mfa_one_active_device",
            ),
            models.CheckConstraint(
                condition=Q(secret_format_version=1),
                name="security_mfa_secret_version_v1",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status=MFADeviceStatus.PENDING, confirmed_at__isnull=True)
                    | Q(status=MFADeviceStatus.ACTIVE, confirmed_at__isnull=False)
                    | Q(status=MFADeviceStatus.DISABLED)
                ),
                name="security_mfa_status_confirmation_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "status"], name="security_mfa_user_status_idx"),
        ]


class SecurityRecoveryCode(models.Model):
    """Single-use salted hash of one recovery code; never the raw code."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="security_recovery_codes",
    )
    code_hash = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "code_hash"],
                name="security_recovery_user_hash_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "used_at"], name="sec_rec_usr_used_idx"),
        ]


class SecurityLoginSession(models.Model):
    """Server-side session registry; only a SHA-256 session-key digest is stored."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="security_login_sessions",
    )
    session_key_hash = models.CharField(max_length=64, unique=True)
    # Fixed admission slots turn the two-session cap into a DB invariant.
    slot_number = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    idle_expires_at = models.DateTimeField()
    absolute_expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=40, blank=True, default="")
    mfa_verified_at = models.DateTimeField(null=True, blank=True)
    user_agent_digest = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(absolute_expires_at__gt=F("created_at")),
                name="security_session_absolute_after_created",
            ),
            models.CheckConstraint(
                condition=Q(idle_expires_at__lte=F("absolute_expires_at")),
                name="security_session_idle_before_absolute",
            ),
            models.CheckConstraint(
                condition=Q(slot_number__in=(1, 2)),
                name="security_session_slot_1_2",
            ),
            models.UniqueConstraint(
                fields=["user", "slot_number"],
                condition=Q(revoked_at__isnull=True),
                name="sec_sess_usr_live_slot",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "revoked_at", "idle_expires_at"],
                name="sec_sess_usr_active_idx",
            ),
        ]


class SecurityMFARequirement(models.Model):
    """GM-controlled employee MFA requirement; GM MFA itself is always mandatory."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="security_mfa_requirement",
    )
    is_required = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="mfa_requirements_updated",
    )
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["is_required", "updated_at"], name="sec_mfa_req_active_idx"),
        ]


class SecurityBootstrapToken(models.Model):
    """Hash-only, one-time token for the first local GM bootstrap only."""

    INITIAL_GM = "INITIAL_GM"
    PURPOSE_CHOICES = ((INITIAL_GM, "Initial GM bootstrap"),)

    purpose = models.CharField(max_length=24, choices=PURPOSE_CHOICES, default=INITIAL_GM)
    token_hash = models.CharField(max_length=64, unique=True)
    issued_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("issued_at")),
                name="security_bootstrap_expiry_after_issue",
            ),
            models.CheckConstraint(
                condition=Q(consumed_at__isnull=True) | Q(revoked_at__isnull=True),
                name="security_bootstrap_one_terminal_state",
            ),
            models.UniqueConstraint(
                fields=["purpose"],
                condition=Q(consumed_at__isnull=True, revoked_at__isnull=True),
                name="security_bootstrap_one_live_token",
            ),
        ]
        indexes = [
            models.Index(fields=["purpose", "expires_at"], name="sec_boot_purpose_exp_idx"),
        ]

    def __str__(self):
        state = "consumed" if self.consumed_at else "revoked" if self.revoked_at else "live"
        return f"{self.purpose}:{state}"


class SecurityEmergencyOwnerKey(models.Model):
    """One-time offline owner key for emergency recovery of the existing GM."""

    GM_RECOVERY = "GM_RECOVERY"
    SOURCE_INITIAL_BOOTSTRAP = "INITIAL_BOOTSTRAP"
    SOURCE_ROTATION = "ROTATION"
    SOURCE_EMERGENCY_RECOVERY = "EMERGENCY_RECOVERY"
    SOURCE_CHOICES = (
        (SOURCE_INITIAL_BOOTSTRAP, "Initial GM bootstrap"),
        (SOURCE_ROTATION, "Local key rotation"),
        (SOURCE_EMERGENCY_RECOVERY, "Offline GM emergency recovery"),
    )

    scope = models.CharField(
        max_length=24,
        choices=((GM_RECOVERY, "GM emergency recovery"),),
        default=GM_RECOVERY,
    )
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES)
    key_hash = models.CharField(max_length=64, unique=True)
    issued_at = models.DateTimeField()
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="emergency_owner_keys_issued",
    )
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="emergency_owner_keys_consumed",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=40, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(scope="GM_RECOVERY"),
                name="sec_em_owner_gm_scope_only",
            ),
            models.CheckConstraint(
                condition=(
                    Q(consumed_at__isnull=True, consumed_by__isnull=True)
                    | Q(consumed_at__isnull=False, consumed_by__isnull=False)
                ),
                name="sec_em_owner_consumed_actor",
            ),
            models.CheckConstraint(
                condition=Q(consumed_at__isnull=True) | Q(revoked_at__isnull=True),
                name="sec_em_owner_one_terminal",
            ),
            models.UniqueConstraint(
                fields=["scope"],
                condition=Q(consumed_at__isnull=True, revoked_at__isnull=True),
                name="sec_em_owner_one_live",
            ),
        ]
        indexes = [
            models.Index(fields=["scope", "consumed_at", "revoked_at"], name="sec_em_owner_status_idx"),
        ]

    def __str__(self):
        state = "consumed" if self.consumed_at else "revoked" if self.revoked_at else "live"
        return f"{self.scope}:{state}"
