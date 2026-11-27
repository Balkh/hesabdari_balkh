from __future__ import annotations

import os

import pytest

from security.local_console import (
    _windows_remote_session_state,
    _windows_session_ids,
)


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="native Windows session API probes run only on Windows",
)


def test_native_windows_session_identity_and_remote_state_apis():
    active_console_session_id, process_session_id = _windows_session_ids()

    assert isinstance(active_console_session_id, int)
    assert isinstance(process_session_id, int)
    assert 0 <= active_console_session_id <= 0xFFFFFFFF
    assert 0 <= process_session_id <= 0xFFFFFFFF

    is_remote_session, is_remotely_controlled, glass_session_id = (
        _windows_remote_session_state(process_session_id)
    )
    assert isinstance(is_remote_session, bool)
    assert isinstance(is_remotely_controlled, bool)
    assert isinstance(glass_session_id, int)
    assert 0 <= glass_session_id <= 0xFFFFFFFF
