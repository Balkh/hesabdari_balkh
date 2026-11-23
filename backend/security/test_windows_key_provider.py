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
    targets = [
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
        assert key_id == provider.KEY_ID
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
        expected_key = provider.get_key(provider.KEY_ID)
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
        assert result == {
            "backup_encryption_key_id": provider.BACKUP_ENCRYPTION_KEY_ID,
            "checkpoint_signing_key_id": provider.CHECKPOINT_SIGNING_KEY_ID,
        }
        assert len(provider.get_backup_encryption_key(result["backup_encryption_key_id"])) == 32
        private = provider.get_checkpoint_signing_private_key(result["checkpoint_signing_key_id"])
        public = provider.get_checkpoint_signing_public_key(result["checkpoint_signing_key_id"])
        assert len(private) == 32
        assert len(public) == 32
        assert provider.active_backup_encryption_key_id() == result["backup_encryption_key_id"]
        assert provider.active_checkpoint_signing_key_id() == result["checkpoint_signing_key_id"]
        assert private != provider.get_key(provider.KEY_ID)
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
