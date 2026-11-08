from __future__ import annotations

import base64
import os
import subprocess
import sys
import uuid

import pytest

from security.crypto import KeyUnavailableError
from security.windows_key_provider import WindowsCredentialManagerKeyProvider, _delete_generic


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="Credential Manager provider tests require Windows",
)


def _cleanup(provider):
    for target in (
        provider._active_target(),
        provider._key_target(provider.KEY_ID),
        provider._django_secret_target(),
    ):
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
