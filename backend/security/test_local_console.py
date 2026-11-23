from unittest.mock import Mock
from django.test import SimpleTestCase
from security.local_console import LocalConsoleRequiredError, _is_active_physical_console, require_local_console

class _TTY:
    def isatty(self):
        return True

class LocalConsoleGuardTests(SimpleTestCase):
    def test_non_tty_is_rejected(self):
        with self.assertRaises(LocalConsoleRequiredError):
            require_local_console(
                stdin=Mock(isatty=Mock(return_value=False)), stdout=_TTY(),
                environ={}, platform_name="posix",
            )

    def test_ssh_environment_is_rejected_even_with_tty(self):
        with self.assertRaises(LocalConsoleRequiredError):
            require_local_console(
                stdin=_TTY(), stdout=_TTY(),
                environ={"SSH_CONNECTION": "192.0.2.10 5555 192.0.2.20 22"},
                platform_name="posix",
            )

    def test_windows_command_requires_process_in_physical_console_session(self):
        require_local_console(
            stdin=_TTY(), stdout=_TTY(), environ={}, platform_name="nt",
            session_ids=lambda: (7, 7),
        )
        with self.assertRaises(LocalConsoleRequiredError):
            require_local_console(
                stdin=_TTY(), stdout=_TTY(), environ={}, platform_name="nt",
                session_ids=lambda: (7, 8),
            )

    def test_missing_physical_console_is_rejected(self):
        self.assertFalse(_is_active_physical_console(0xFFFFFFFF, 7))
        self.assertFalse(_is_active_physical_console(7, 8))
        self.assertTrue(_is_active_physical_console(7, 7))
        with self.assertRaises(LocalConsoleRequiredError):
            require_local_console(
                stdin=_TTY(), stdout=_TTY(), environ={}, platform_name="nt",
                session_ids=lambda: (0xFFFFFFFF, 7),
            )

    def test_local_interactive_non_windows_terminal_remains_supported(self):
        require_local_console(
            stdin=_TTY(), stdout=_TTY(), environ={}, platform_name="posix",
        )
