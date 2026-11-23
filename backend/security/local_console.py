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
_SM_REMOTESESSION = 0x1000
_SM_REMOTECONTROL = 0x2001
_GLASS_SESSION_KEY = r"SYSTEM\CurrentControlSet\Control\Terminal Server"


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


def _windows_remote_session_state(process_session_id: int) -> tuple[bool, bool, int]:
    """Return (remote session, remotely controlled session, GlassSessionId).

    SM_REMOTESESSION alone misses some RemoteFX virtual-GPU sessions.
    Microsoft documents GlassSessionId as the local-session discriminator
    for that case. A missing/unreadable registry value fails closed.
    """
    try:
        import winreg

        user32 = ctypes.WinDLL("user32.dll", use_last_error=True)
        get_system_metrics = user32.GetSystemMetrics
        get_system_metrics.argtypes = [ctypes.c_int]
        get_system_metrics.restype = ctypes.c_int
        is_remote_session = bool(get_system_metrics(_SM_REMOTESESSION))
        is_remotely_controlled = bool(get_system_metrics(_SM_REMOTECONTROL))
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _GLASS_SESSION_KEY, 0, winreg.KEY_READ) as key:
            glass_session_id, value_type = winreg.QueryValueEx(key, "GlassSessionId")
        if value_type != winreg.REG_DWORD or not isinstance(glass_session_id, int):
            raise LocalConsoleRequiredError("Windows local-session identity is unavailable")
        return is_remote_session, is_remotely_controlled, glass_session_id
    except LocalConsoleRequiredError:
        raise
    except Exception:
        raise LocalConsoleRequiredError("Windows remote-session state could not be verified") from None


def _is_active_physical_console(active_console_session_id: int, process_session_id: int) -> bool:
    return active_console_session_id != _INVALID_SESSION_ID and process_session_id == active_console_session_id


def _is_uncontrolled_local_session(
    *,
    is_remote_session: bool,
    is_remotely_controlled: bool,
    process_session_id: int,
    glass_session_id: int,
) -> bool:
    return (
        not is_remote_session
        and not is_remotely_controlled
        and process_session_id == glass_session_id
    )


def require_local_console(
    *,
    stdin=None,
    stdout=None,
    environ=None,
    platform_name: str | None = None,
    session_ids=None,
    remote_session_state=None,
) -> None:
    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    environment = os.environ if environ is None else environ
    platform = os.name if platform_name is None else platform_name
    if not input_stream.isatty() or not output_stream.isatty():
        raise LocalConsoleRequiredError("This operation requires a local interactive terminal")
    if any(environment.get(name) for name in _REMOTE_SESSION_ENV):
        raise LocalConsoleRequiredError("Remote shell sessions are not permitted for this operation")
    if platform == "nt":
        active_session_id, process_session_id = (
            session_ids() if session_ids is not None else _windows_session_ids()
        )
        if not _is_active_physical_console(active_session_id, process_session_id):
            raise LocalConsoleRequiredError(
                "This operation must run in the Windows session attached to the physical console"
            )
        try:
            remote_state = (
                remote_session_state(process_session_id)
                if remote_session_state is not None
                else _windows_remote_session_state(process_session_id)
            )
            is_remote_session, is_remotely_controlled, glass_session_id = remote_state
        except LocalConsoleRequiredError:
            raise
        except Exception:
            raise LocalConsoleRequiredError(
                "Windows remote-session state could not be verified"
            ) from None
        if not _is_uncontrolled_local_session(
            is_remote_session=is_remote_session,
            is_remotely_controlled=is_remotely_controlled,
            process_session_id=process_session_id,
            glass_session_id=glass_session_id,
        ):
            raise LocalConsoleRequiredError(
                "Remote Desktop or remotely controlled Windows sessions are not permitted"
            )
