from __future__ import annotations

import base64
import os
import subprocess
import sys
import uuid

import pytest

from security.errors import KeyUnavailableError
from security.windows_key_provider import WindowsCredentialManagerKeyProvider, _delete_generic


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="Credential Manager provider tests require Windows",
)


def _cleanup(provider):
    from security.windows_key_provider import _read_generic
    targets = []
    # Read active pointers before removing them, including partial vaults.
    for pointer, methods in (
        (provider._active_target(), (provider._key_target,)),
        (provider._backup_active_target(), (provider._backup_key_target,)),
        (provider._checkpoint_active_target(), (provider._checkpoint_private_target, provider._checkpoint_public_target)),
    ):
        raw = _read_generic(pointer)
        if raw is not None:
            targets.extend(method(raw.decode("ascii")) for method in methods)
    targets += [
        provider._active_target(),
        provider._key_target(provider.KEY_ID),
        provider._django_secret_target(),
    ]
    # W0-2E backup/checkpoint key records are separate from MFA and Django keys.
    for method_name, key_id in (
        ("_backup_active_target", None),
        ("_backup_key_target", getattr(provider, "BACKUP_ENCRYPTION_KEY_ID", None)),
        ("_checkpoint_active_target", None),
        ("_checkpoint_private_target", getattr(provider, "CHECKPOINT_SIGNING_KEY_ID", None)),
        ("_checkpoint_public_target", getattr(provider, "CHECKPOINT_SIGNING_KEY_ID", None)),
    ):
        method = getattr(provider, method_name, None)
        if callable(method):
            targets.append(method() if key_id is None else method(key_id))
    for target in targets:
        try:
            _delete_generic(target)
        except Exception:
            pass


def test_provider_provisions_two_distinct_secrets_and_reads_them_back():
    namespace = "HesabdariBalkh:ProviderTest:" + uuid.uuid4().hex
    provider = WindowsCredentialManagerKeyProvider(namespace=namespace)
    try:
        key_id = provider.provision()
        assert key_id.startswith(provider.KEY_ID + "-")
        aes_key = provider.get_key(key_id)
        django_secret = provider.get_django_secret_key()
        assert len(aes_key) == 32
        assert len(django_secret) >= 50
        assert aes_key.decode("latin1") != django_secret
        assert provider.active_key_id() == key_id
    finally:
        _cleanup(provider)


def test_provider_refuses_to_overwrite_an_existing_or_partial_vault():
    namespace = "HesabdariBalkh:ProviderPartialTest:" + uuid.uuid4().hex
    provider = WindowsCredentialManagerKeyProvider(namespace=namespace)
    try:
        from security.windows_key_provider import _write_generic

        _write_generic(
            provider._active_target(),
            provider.KEY_ID.encode("ascii"),
            comment="Partial provisioning test record",
        )
        with pytest.raises(KeyUnavailableError):
            provider.provision()
        # An active pointer without its referenced key is an invalid partial
        # vault; reads fail closed and the existing pointer is not overwritten.
        with pytest.raises(KeyUnavailableError):
            provider.active_key_id()
        from security.windows_key_provider import _read_generic
        assert _read_generic(provider._active_target()) == provider.KEY_ID.encode("ascii")
        assert _delete_generic(provider._active_target())
    finally:
        _cleanup(provider)


def test_provider_reads_the_same_user_vault_from_a_new_process():
    namespace = "HesabdariBalkh:ProviderProcessTest:" + uuid.uuid4().hex
    provider = WindowsCredentialManagerKeyProvider(namespace=namespace)
    try:
        provider.provision()
        expected_key = provider.get_key(provider.active_key_id())
        expected_secret = provider.get_django_secret_key()
        script = (
            "import base64,sys; "
            "from security.windows_key_provider import WindowsCredentialManagerKeyProvider; "
            "p=WindowsCredentialManagerKeyProvider(namespace=sys.argv[1]); "
            "print(base64.b64encode(p.get_key(p.active_key_id())).decode('ascii')); "
            "print(p.get_django_secret_key())"
        )
        result = subprocess.run(
            [sys.executable, "-c", script, namespace],
            capture_output=True,
            check=True,
            text=True,
        )
        lines = result.stdout.splitlines()
        assert base64.b64decode(lines[0]) == expected_key
        assert lines[1] == expected_secret
    finally:
        _cleanup(provider)


def test_provider_provisions_separate_backup_and_ed25519_checkpoint_keys():
    namespace = "HesabdariBalkh:BackupProviderTest:" + uuid.uuid4().hex
    provider = WindowsCredentialManagerKeyProvider(namespace=namespace)
    try:
        # The MFA AES key must already exist in the same user vault so this
        # assertion proves backup and checkpoint key custody remains separate.
        provider.provision()
        result = provider.provision_backup_keys()
        assert result["backup_encryption_key_id"].startswith(provider.BACKUP_ENCRYPTION_KEY_ID + "-")
        assert result["checkpoint_signing_key_id"].startswith(provider.CHECKPOINT_SIGNING_KEY_ID + "-")
        assert len(provider.get_backup_encryption_key(result["backup_encryption_key_id"])) == 32
        private = provider.get_checkpoint_signing_private_key(result["checkpoint_signing_key_id"])
        public = provider.get_checkpoint_signing_public_key(result["checkpoint_signing_key_id"])
        assert len(private) == 32
        assert len(public) == 32
        assert provider.active_backup_encryption_key_id() == result["backup_encryption_key_id"]
        assert provider.active_checkpoint_signing_key_id() == result["checkpoint_signing_key_id"]
        assert private != provider.get_key(provider.active_key_id())
    finally:
        _cleanup(provider)


def test_provider_refuses_partial_backup_or_checkpoint_key_overwrite():
    namespace = "HesabdariBalkh:BackupProviderPartialTest:" + uuid.uuid4().hex
    provider = WindowsCredentialManagerKeyProvider(namespace=namespace)
    try:
        from security.windows_key_provider import _write_generic

        _write_generic(
            provider._backup_active_target(),
            provider.BACKUP_ENCRYPTION_KEY_ID.encode("ascii"),
            comment="Partial backup-key provisioning test record",
        )
        with pytest.raises(KeyUnavailableError):
            provider.provision_backup_keys()
        assert provider._backup_active_target()
        from security.windows_key_provider import _read_generic
        assert _read_generic(provider._backup_active_target()) == provider.BACKUP_ENCRYPTION_KEY_ID.encode("ascii")
    finally:
        _cleanup(provider)


def test_checkpoint_public_key_survives_private_key_unavailability():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    namespace = "HesabdariBalkh:PublicOnlyTest:" + uuid.uuid4().hex
    provider = WindowsCredentialManagerKeyProvider(namespace=namespace)
    try:
        provider.provision_backup_keys()
        key_id = provider.active_checkpoint_signing_key_id()
        private = Ed25519PrivateKey.from_private_bytes(provider.get_checkpoint_signing_private_key(key_id))
        public = provider.get_checkpoint_signing_public_key(key_id)
        signature = private.sign(b"synthetic checkpoint")
        del private
        assert _delete_generic(provider._checkpoint_private_target(key_id))
        with pytest.raises(KeyUnavailableError):
            provider.get_checkpoint_signing_private_key(key_id)
        with pytest.raises(KeyUnavailableError):
            provider.active_checkpoint_signing_key_id()
        assert provider.get_checkpoint_signing_public_key(key_id) == public
        Ed25519PublicKey.from_public_bytes(public).verify(signature, b"synthetic checkpoint")
    finally:
        _cleanup(provider)


def test_desktop_profile_migrates_and_commits_audit_on_real_windows(tmp_path):
    namespace = "HesabdariBalkh:DesktopRuntimeTest:" + uuid.uuid4().hex
    provider = WindowsCredentialManagerKeyProvider(namespace=namespace)
    try:
        provider.provision()
        env = os.environ.copy()
        env["DJANGO_SETTINGS_MODULE"] = "config.settings.desktop"
        env["HESABDARI_DESKTOP_DATABASE_PATH"] = str(tmp_path / "desktop.sqlite3")
        script = r"""
import sys
from unittest.mock import patch
import django
from security.windows_key_provider import WindowsCredentialManagerKeyProvider
provider = WindowsCredentialManagerKeyProvider(namespace=sys.argv[1])
# Redirect only the vault namespace to a disposable fixture.
with patch("security.windows_key_provider.WindowsCredentialManagerKeyProvider", return_value=provider):
    django.setup()
from django.db import connection, transaction
from django.core.management import call_command
from security.audit_chain import verify_audit_chain, assert_audit_trigger_schema
from security.models import AuditAction
from security.services import record_audit_event
call_command("migrate", interactive=False, verbosity=0)
assert connection.transaction_mode == "IMMEDIATE"
with connection.cursor() as cursor:
    cursor.execute("PRAGMA busy_timeout")
    assert cursor.fetchone()[0] == 20000
before = verify_audit_chain()
with transaction.atomic():
    event = record_audit_event(action=AuditAction.CREATE, entity="DesktopRuntime")
assert_audit_trigger_schema()
after = verify_audit_chain()
assert after["event_count"] == before["event_count"] + 1
assert after["last_event_id"] == event.pk
connection.close()
assert verify_audit_chain() == after
connection.close()
print("DESKTOP RUNTIME: actual profile, migrations, committed audit and reconnect verified")
"""
        result = subprocess.run([sys.executable, "-c", script, namespace], env=env,
                                capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "DESKTOP RUNTIME:" in result.stdout
        print(result.stdout)
    finally:
        _cleanup(provider)


def test_fresh_vaults_use_distinct_key_ids_and_preserve_existing_vault():
    first = WindowsCredentialManagerKeyProvider(namespace="HesabdariBalkh:GenerationTest:" + uuid.uuid4().hex)
    second = WindowsCredentialManagerKeyProvider(namespace="HesabdariBalkh:GenerationTest:" + uuid.uuid4().hex)
    try:
        first_mfa = first.provision()
        first_ids = first.provision_backup_keys()
        second_mfa = second.provision()
        second_ids = second.provision_backup_keys()
        assert first_mfa != second_mfa
        assert first.get_django_secret_key() != second.get_django_secret_key()
        for field in first_ids:
            assert first_ids[field] != second_ids[field]
        with pytest.raises(KeyUnavailableError):
            second.get_key(first_mfa)
        with pytest.raises(KeyUnavailableError):
            second.get_backup_encryption_key(first_ids["backup_encryption_key_id"])
        with pytest.raises(KeyUnavailableError):
            second.get_checkpoint_signing_public_key(first_ids["checkpoint_signing_key_id"])
        with pytest.raises(KeyUnavailableError):
            first.provision()
        with pytest.raises(KeyUnavailableError):
            first.provision_backup_keys()
        assert first.active_key_id() == first_mfa
        assert first.active_backup_encryption_key_id() == first_ids["backup_encryption_key_id"]
        assert first.active_checkpoint_signing_key_id() == first_ids["checkpoint_signing_key_id"]
    finally:
        _cleanup(first)
        _cleanup(second)


def test_legacy_vault_identifiers_remain_readable_and_not_overwritten():
    from security.windows_key_provider import _write_generic
    provider = WindowsCredentialManagerKeyProvider(namespace="HesabdariBalkh:LegacyGenerationTest:" + uuid.uuid4().hex)
    try:
        _write_generic(provider._key_target(provider.KEY_ID), b"M" * 32, comment="Synthetic legacy key")
        _write_generic(provider._active_target(), provider.KEY_ID.encode("ascii"), comment="Synthetic legacy pointer")
        assert provider.active_key_id() == provider.KEY_ID
        assert provider.get_key(provider.KEY_ID) == b"M" * 32
        with pytest.raises(KeyUnavailableError):
            provider.provision()
        assert provider.get_key(provider.KEY_ID) == b"M" * 32
        _write_generic(provider._backup_key_target(provider.BACKUP_ENCRYPTION_KEY_ID), b"B" * 32, comment="Synthetic legacy partial key")
        with pytest.raises(KeyUnavailableError):
            provider.provision_backup_keys()
        assert provider.get_backup_encryption_key(provider.BACKUP_ENCRYPTION_KEY_ID) == b"B" * 32
    finally:
        _cleanup(provider)


def test_failed_key_cleanup_retains_active_pointer_and_refuses_reprovision(monkeypatch):
    from security import windows_key_provider as module
    provider = WindowsCredentialManagerKeyProvider(namespace="HesabdariBalkh:CleanupFailure:" + uuid.uuid4().hex)
    original_write = module._write_generic
    original_delete = module._delete_generic
    def fail_django_write(target, blob, *, comment):
        if target == provider._django_secret_target():
            raise KeyUnavailableError("synthetic write failure")
        return original_write(target, blob, comment=comment)
    def fail_key_delete(target):
        if target.startswith(provider.namespace + ":MFA:KEY:"):
            raise KeyUnavailableError("synthetic cleanup failure")
        return original_delete(target)
    try:
        with monkeypatch.context() as m:
            m.setattr(module, "_write_generic", fail_django_write)
            m.setattr(module, "_delete_generic", fail_key_delete)
            with pytest.raises(KeyUnavailableError):
                provider.provision()
        raw = module._read_generic(provider._active_target())
        assert raw is not None
        key_id = raw.decode("ascii")
        assert len(provider.get_key(key_id)) == 32
        assert module._read_generic(provider._django_secret_target()) is None
        with pytest.raises(KeyUnavailableError):
            provider.provision()
        assert module._read_generic(provider._active_target()) == raw
    finally:
        _cleanup(provider)
