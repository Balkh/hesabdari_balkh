from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from security.windows_key_custody_eval import (
    WindowsKeyCustodyProbeError,
    credential_manager_delete_generic,
    credential_manager_read_generic,
    credential_manager_write_generic,
    dpapi_protect_current_user,
    dpapi_unprotect_current_user,
)


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="Windows OS key-custody probes run only on Windows",
)


def test_dpapi_current_user_roundtrip_and_wrong_entropy_denial():
    plaintext = os.urandom(32)
    entropy = os.urandom(32)
    protected = dpapi_protect_current_user(plaintext, entropy)
    assert protected
    assert protected != plaintext
    assert dpapi_unprotect_current_user(protected, entropy) == plaintext
    with pytest.raises(WindowsKeyCustodyProbeError):
        dpapi_unprotect_current_user(protected, os.urandom(32))


def test_dpapi_current_user_protected_blob_survives_a_new_process():
    plaintext = os.urandom(32)
    entropy = os.urandom(32)
    protected = dpapi_protect_current_user(plaintext, entropy)
    script = (
        "import base64, pathlib, sys; "
        "from security.windows_key_custody_eval import dpapi_unprotect_current_user; "
        "cipher=pathlib.Path(sys.argv[1]).read_bytes(); "
        "entropy=base64.b64decode(sys.argv[2]); "
        "print(base64.b64encode(dpapi_unprotect_current_user(cipher, entropy)).decode('ascii'))"
    )
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "dpapi-probe.bin"
        path.write_bytes(protected)
        result = subprocess.run(
            [sys.executable, "-c", script, str(path), base64.b64encode(entropy).decode("ascii")],
            check=True,
            capture_output=True,
            text=True,
        )
    assert base64.b64decode(result.stdout.strip()) == plaintext


def test_credential_manager_generic_credential_roundtrip_and_new_process_read():
    target = "HesabdariBalkh:W0-2C:Evaluation:" + uuid.uuid4().hex
    payload = os.urandom(32)
    try:
        credential_manager_write_generic(target, payload)
        assert credential_manager_read_generic(target) == payload
        script = (
            "import base64, sys; "
            "from security.windows_key_custody_eval import credential_manager_read_generic; "
            "value=credential_manager_read_generic(sys.argv[1]); "
            "print('MISSING' if value is None else base64.b64encode(value).decode('ascii'))"
        )
        result = subprocess.run(
            [sys.executable, "-c", script, target],
            check=True,
            capture_output=True,
            text=True,
        )
        assert base64.b64decode(result.stdout.strip()) == payload
    finally:
        credential_manager_delete_generic(target)
