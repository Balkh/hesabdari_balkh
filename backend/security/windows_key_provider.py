"""Candidate Windows Credential Manager KeyProvider for the local desktop runtime.

Credentials are stored as CRED_TYPE_GENERIC in the current user's vault with
CRED_PERSIST_LOCAL_MACHINE. Despite the Win32 constant's name, this persistence
scope means subsequent logon sessions of the same user on the same computer;
it is not a machine-wide credential. Never run the desktop backend as
LocalSystem or another service account.

This provider is deliberately not selected by config.settings.production.
It is for the Windows desktop profile only, pending real Windows 10/11 client
validation and Tauri sidecar identity verification.
"""
from __future__ import annotations

import ctypes
import hmac
import os
import re
import secrets
from contextlib import contextmanager
from ctypes import wintypes

from security.crypto import KEY_BYTES, KeyUnavailableError

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
CRED_MAX_CREDENTIAL_BLOB_SIZE = 5_120
ERROR_NOT_FOUND = 1168
WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080
WAIT_TIMEOUT = 0x00000102
DEFAULT_NAMESPACE = "HesabdariBalkh:Desktop"
DEFAULT_KEY_ID = "windows-credential-manager-aes256-v1"
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")


class _FileTime(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class _CredentialW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FileTime),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _require_windows() -> None:
    if os.name != "nt":
        raise KeyUnavailableError("Windows Credential Manager is available only on Windows")


def _win_error(operation: str) -> KeyUnavailableError:
    return KeyUnavailableError(
        f"{operation} failed with Windows error {ctypes.get_last_error()}"
    )


def _credential_api():
    _require_windows()
    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi32.CredWriteW.argtypes = [
        ctypes.POINTER(_CredentialW),
        wintypes.DWORD,
    ]
    advapi32.CredWriteW.restype = wintypes.BOOL
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_CredentialW)),
    ]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredDeleteW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    advapi32.CredDeleteW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None
    return advapi32


def _read_generic(target: str) -> bytes | None:
    api = _credential_api()
    pointer = ctypes.POINTER(_CredentialW)()
    if not api.CredReadW(
        target,
        CRED_TYPE_GENERIC,
        0,
        ctypes.byref(pointer),
    ):
        error = ctypes.get_last_error()
        if error == ERROR_NOT_FOUND:
            return None
        raise KeyUnavailableError(
            f"Windows Credential Manager read failed with error {error}"
        )
    try:
        item = pointer.contents
        if item.CredentialBlobSize > CRED_MAX_CREDENTIAL_BLOB_SIZE:
            raise KeyUnavailableError("Windows Credential Manager returned an oversized credential")
        if item.CredentialBlobSize and not item.CredentialBlob:
            raise KeyUnavailableError("Windows Credential Manager returned an invalid credential")
        return ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize)
    finally:
        api.CredFree(ctypes.cast(pointer, ctypes.c_void_p))


def _write_generic(target: str, blob: bytes, *, comment: str) -> None:
    api = _credential_api()
    if not isinstance(blob, bytes) or not blob or len(blob) > CRED_MAX_CREDENTIAL_BLOB_SIZE:
        raise KeyUnavailableError("credential material has an invalid size")
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    record = _CredentialW()
    record.Flags = 0
    record.Type = CRED_TYPE_GENERIC
    record.TargetName = target
    record.Comment = comment
    record.LastWritten = _FileTime(0, 0)
    record.CredentialBlobSize = len(blob)
    record.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    # CRED_PERSIST_LOCAL_MACHINE is per-user storage: it persists across
    # subsequent logons of this same user on this same computer.
    record.Persist = CRED_PERSIST_LOCAL_MACHINE
    record.AttributeCount = 0
    record.Attributes = None
    record.TargetAlias = None
    record.UserName = "Hesabdari Balkh"
    if not api.CredWriteW(ctypes.byref(record), 0):
        raise _win_error("CredWriteW(Generic)")


def _delete_generic(target: str) -> bool:
    api = _credential_api()
    if api.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
        return True
    error = ctypes.get_last_error()
    if error == ERROR_NOT_FOUND:
        return False
    raise KeyUnavailableError(
        f"Windows Credential Manager delete failed with error {error}"
    )


@contextmanager
def _provisioning_mutex(namespace: str):
    """Serialize first provisioning across processes in the current logon session."""
    _require_windows()
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    name = "Local\\HesabdariBalkh.CredentialProvision." + namespace.replace(":", ".")
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise _win_error("CreateMutexW")
    acquired = False
    try:
        wait = kernel32.WaitForSingleObject(handle, 15_000)
        if wait not in (WAIT_OBJECT_0, WAIT_ABANDONED):
            if wait == WAIT_TIMEOUT:
                raise KeyUnavailableError("Windows credential provisioning is already running")
            raise _win_error("WaitForSingleObject")
        acquired = True
        yield
    finally:
        if acquired:
            kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)


class WindowsCredentialManagerKeyProvider:
    """AES-256 KeyProvider backed by the current user's Credential Manager vault."""

    KEY_ID = DEFAULT_KEY_ID

    def __init__(self, *, namespace: str = DEFAULT_NAMESPACE):
        if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace):
            raise ValueError("invalid Windows credential namespace")
        self.namespace = namespace

    def _active_target(self) -> str:
        return f"{self.namespace}:MFA:ACTIVE_KEY_ID"

    def _key_target(self, key_id: str) -> str:
        if not isinstance(key_id, str) or not _KEY_ID_RE.fullmatch(key_id):
            raise KeyUnavailableError("requested security key identifier is invalid")
        return f"{self.namespace}:MFA:KEY:{key_id}"

    def _django_secret_target(self) -> str:
        return f"{self.namespace}:DJANGO:SECRET:v1"

    def active_key_id(self) -> str:
        raw = _read_generic(self._active_target())
        if raw is None:
            raise KeyUnavailableError("active Windows MFA key is not provisioned for this user")
        try:
            key_id = raw.decode("ascii")
        except UnicodeDecodeError:
            raise KeyUnavailableError("active Windows MFA key identifier is malformed") from None
        self.get_key(key_id)
        return key_id

    def get_key(self, key_id: str) -> bytes:
        raw = _read_generic(self._key_target(key_id))
        if raw is None or len(raw) != KEY_BYTES:
            raise KeyUnavailableError("requested Windows AES-256 key is unavailable or invalid")
        return raw

    def get_django_secret_key(self) -> str:
        """Read the separate Django signing key; never reuse the AES key."""
        raw = _read_generic(self._django_secret_target())
        if raw is None:
            raise KeyUnavailableError("desktop Django signing secret is not provisioned for this user")
        try:
            value = raw.decode("ascii")
        except UnicodeDecodeError:
            raise KeyUnavailableError("desktop Django signing secret is malformed") from None
        if len(value) < 50:
            raise KeyUnavailableError("desktop Django signing secret is too short")
        return value

    def provision(self) -> str:
        """Provision AES and Django signing secrets once for the current Windows user.

        This is a local first-run operation. Existing or partial records are
        never overwritten. Raw secret values are never returned or printed.
        """
        _require_windows()
        active_target = self._active_target()
        key_target = self._key_target(self.KEY_ID)
        django_target = self._django_secret_target()
        targets = (active_target, key_target, django_target)

        with _provisioning_mutex(self.namespace):
            if any(_read_generic(target) is not None for target in targets):
                raise KeyUnavailableError(
                    "Windows desktop secrets already exist or are partially provisioned; refusing to overwrite"
                )

            aes_key = secrets.token_bytes(KEY_BYTES)
            django_secret = secrets.token_urlsafe(64).encode("ascii")
            written: list[str] = []
            try:
                _write_generic(
                    key_target,
                    aes_key,
                    comment="Hesabdari Balkh AES-256 MFA encryption key",
                )
                written.append(key_target)
                _write_generic(
                    django_target,
                    django_secret,
                    comment="Hesabdari Balkh Django signing secret",
                )
                written.append(django_target)
                _write_generic(
                    active_target,
                    self.KEY_ID.encode("ascii"),
                    comment="Hesabdari Balkh active MFA key identifier",
                )
                written.append(active_target)

                read_key = _read_generic(key_target)
                read_secret = _read_generic(django_target)
                read_active = _read_generic(active_target)
                if (
                    read_key is None
                    or not hmac.compare_digest(read_key, aes_key)
                    or read_secret is None
                    or not hmac.compare_digest(read_secret, django_secret)
                    or read_active != self.KEY_ID.encode("ascii")
                ):
                    raise KeyUnavailableError(
                        "Windows desktop credential read-back verification failed"
                    )
                return self.KEY_ID
            except Exception:
                # Delete only entries this operation successfully created.
                for target in reversed(written):
                    try:
                        _delete_generic(target)
                    except Exception:
                        pass
                raise KeyUnavailableError(
                    "Windows desktop secret provisioning failed; inspect the current user's credential vault"
                ) from None
