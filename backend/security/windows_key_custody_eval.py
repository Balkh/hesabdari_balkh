"""Windows OS key-custody evaluation probes.

This module is test/evaluation tooling only. It is NOT a production KeyProvider,
does not provision ERP keys automatically, and must not be wired into production
until Windows 10/11 identity, persistence, profile-loss, and recovery tests pass.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


class WindowsKeyCustodyProbeError(RuntimeError):
    """A Windows key-custody probe failed closed."""


def _require_windows() -> None:
    if os.name != "nt":
        raise WindowsKeyCustodyProbeError("Windows key-custody probes require Windows")


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _data_blob(value: bytes):
    if not isinstance(value, bytes) or not value:
        raise ValueError("probe payload must be non-empty bytes")
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    blob = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def _winerror(operation: str) -> WindowsKeyCustodyProbeError:
    return WindowsKeyCustodyProbeError(
        f"{operation} failed with Windows error {ctypes.get_last_error()}"
    )


def dpapi_protect_current_user(plaintext: bytes, entropy: bytes) -> bytes:
    """Protect test bytes with DPAPI CurrentUser; never use LOCAL_MACHINE scope."""
    _require_windows()
    if not entropy:
        raise ValueError("DPAPI evaluation requires explicit optional entropy")
    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    protect = crypt32.CryptProtectData
    protect.argtypes = [
        ctypes.POINTER(_DataBlob), wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    protect.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    source, source_buffer = _data_blob(plaintext)
    optional_entropy, entropy_buffer = _data_blob(entropy)
    output = _DataBlob()
    # CRYPTPROTECT_UI_FORBIDDEN only. Do not set CRYPTPROTECT_LOCAL_MACHINE.
    if not protect(
        ctypes.byref(source),
        "Hesabdari Balkh W0-2C evaluation",
        ctypes.byref(optional_entropy),
        None, None, 0x1, ctypes.byref(output),
    ):
        raise _winerror("CryptProtectData(CurrentUser)")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        if output.pbData:
            local_free(ctypes.cast(output.pbData, ctypes.c_void_p))


def dpapi_unprotect_current_user(ciphertext: bytes, entropy: bytes) -> bytes:
    """Unprotect a DPAPI CurrentUser test payload with matching entropy."""
    _require_windows()
    if not entropy:
        raise ValueError("DPAPI evaluation requires explicit optional entropy")
    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    unprotect = crypt32.CryptUnprotectData
    unprotect.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    unprotect.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    source, source_buffer = _data_blob(ciphertext)
    optional_entropy, entropy_buffer = _data_blob(entropy)
    output = _DataBlob()
    if not unprotect(
        ctypes.byref(source), None, ctypes.byref(optional_entropy),
        None, None, 0x1, ctypes.byref(output),
    ):
        raise _winerror("CryptUnprotectData(CurrentUser)")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        if output.pbData:
            local_free(ctypes.cast(output.pbData, ctypes.c_void_p))


class _FileTime(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


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


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
CRED_MAX_CREDENTIAL_BLOB_SIZE = 5120
ERROR_NOT_FOUND = 1168


def _credential_api():
    _require_windows()
    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi32.CredWriteW.argtypes = [ctypes.POINTER(_CredentialW), wintypes.DWORD]
    advapi32.CredWriteW.restype = wintypes.BOOL
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_CredentialW)),
    ]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi32.CredDeleteW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None
    return advapi32


def credential_manager_write_generic(target: str, blob: bytes) -> None:
    """Write a temporary generic credential for the current-user evaluation."""
    api = _credential_api()
    if not isinstance(target, str) or not target:
        raise ValueError("credential target is required")
    if not isinstance(blob, bytes) or not blob or len(blob) > CRED_MAX_CREDENTIAL_BLOB_SIZE:
        raise ValueError("credential probe blob has an invalid size")
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    record = _CredentialW()
    record.Flags = 0
    record.Type = CRED_TYPE_GENERIC
    record.TargetName = target
    record.Comment = "Temporary W0-2C OS key-custody evaluation probe"
    record.LastWritten = _FileTime(0, 0)
    record.CredentialBlobSize = len(blob)
    record.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    # Persist between logons for this same user on this same computer only.
    record.Persist = CRED_PERSIST_LOCAL_MACHINE
    record.AttributeCount = 0
    record.Attributes = None
    record.TargetAlias = None
    record.UserName = "Hesabdari Balkh evaluation"
    if not api.CredWriteW(ctypes.byref(record), 0):
        raise _winerror("CredWriteW(Generic)")


def credential_manager_read_generic(target: str) -> bytes | None:
    """Read a generic credential from the current user's Windows vault."""
    api = _credential_api()
    pointer = ctypes.POINTER(_CredentialW)()
    if not api.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        code = ctypes.get_last_error()
        if code == ERROR_NOT_FOUND:
            return None
        raise WindowsKeyCustodyProbeError(f"CredReadW(Generic) failed with Windows error {code}")
    try:
        item = pointer.contents
        if item.CredentialBlobSize > CRED_MAX_CREDENTIAL_BLOB_SIZE:
            raise WindowsKeyCustodyProbeError("Credential Manager returned an oversized blob")
        if item.CredentialBlobSize and not item.CredentialBlob:
            raise WindowsKeyCustodyProbeError("Credential Manager returned a null blob")
        return ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize)
    finally:
        api.CredFree(ctypes.cast(pointer, ctypes.c_void_p))


def credential_manager_delete_generic(target: str) -> bool:
    """Delete one temporary evaluation credential; never enumerate the user's vault."""
    api = _credential_api()
    if api.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
        return True
    code = ctypes.get_last_error()
    if code == ERROR_NOT_FOUND:
        return False
    raise WindowsKeyCustodyProbeError(f"CredDeleteW(Generic) failed with Windows error {code}")
