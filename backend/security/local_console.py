# Fail-closed gate for local interactive emergency/security commands.
from __future__ import annotations
import ctypes
import os
import sys
from ctypes import wintypes

class LocalConsoleRequiredError(RuntimeError):
    """The command is not running in an approved local console."""

_INVALID_SESSION_ID = 0xFFFFFFFF
_REMOTE_SESSION_ENV = ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY", "REMOTEHOST")

def _windows_session_ids() -> tuple[int, int]:
    if os.name != "nt":
        raise LocalConsoleRequiredError("Windows console identity is unavailable")
    try:
        kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        active_console = kernel32.WTSGetActiveConsoleSessionId
        active_console.argtypes = []
        active_console.restype = wintypes.DWORD
        process_to_session = kernel32.ProcessIdToSessionId
        process_to_session.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        process_to_session.restype = wintypes.BOOL
        active_session_id = int(active_console())
        process_session_id = wintypes.DWORD()
        if not process_to_session(os.getpid(), ctypes.byref(process_session_id)):
            raise LocalConsoleRequiredError("Windows could not determine the current process session")
        return active_session_id, int(process_session_id.value)
    except LocalConsoleRequiredError:
        raise
    except Exception:
        raise LocalConsoleRequiredError("Windows physical-console identity could not be verified") from None

def _is_active_physical_console(active_console_session_id: int, process_session_id: int) -> bool:
    return active_console_session_id != _INVALID_SESSION_ID and process_session_id == active_console_session_id

def require_local_console(*, stdin=None, stdout=None, environ=None, platform_name: str | None = None, session_ids=None) -> None:
    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    environment = os.environ if environ is None else environ
    platform = os.name if platform_name is None else platform_name
    if not input_stream.isatty() or not output_stream.isatty():
        raise LocalConsoleRequiredError("This operation requires a local interactive terminal")
    if any(environment.get(name) for name in _REMOTE_SESSION_ENV):
        raise LocalConsoleRequiredError("Remote shell sessions are not permitted for this operation")
    if platform == "nt":
        active_session_id, process_session_id = session_ids() if session_ids is not None else _windows_session_ids()
        if not _is_active_physical_console(active_session_id, process_session_id):
            raise LocalConsoleRequiredError("This operation must run in the Windows session attached to the physical console")
