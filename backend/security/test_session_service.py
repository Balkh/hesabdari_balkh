from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from security.mfa_models import SecurityLoginSession
from security.session_service import (
    SESSION_IDLE_TIMEOUT,
    SessionAdmissionError,
    register_login_session,
    revoke_login_session,
    session_key_digest,
    touch_login_session,
)


class SessionRegistryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="session-quota")

    def test_only_two_active_sessions_are_admitted(self):
        first = register_login_session(self.user, "first-session-key")
        second = register_login_session(self.user, "second-session-key")
        self.assertEqual({first.slot_number, second.slot_number}, {1, 2})
        with self.assertRaises(SessionAdmissionError):
            register_login_session(self.user, "third-session-key")
        self.assertEqual(
            SecurityLoginSession.objects.filter(user=self.user, revoked_at__isnull=True).count(),
            2,
        )

    def test_revoked_session_releases_slot_without_deleting_history(self):
        first = register_login_session(self.user, "first-session-key")
        self.assertTrue(revoke_login_session(self.user, "first-session-key"))
        second = register_login_session(self.user, "second-session-key")
        self.assertEqual(second.slot_number, first.slot_number)
        self.assertEqual(SecurityLoginSession.objects.count(), 2)
        first.refresh_from_db()
        self.assertIsNotNone(first.revoked_at)

    def test_expired_session_is_closed_and_slot_reused(self):
        now = timezone.now()
        old = register_login_session(
            self.user, "old-session-key",
            at=now - SESSION_IDLE_TIMEOUT - timedelta(seconds=1),
        )
        fresh = register_login_session(self.user, "fresh-session-key", at=now)
        self.assertEqual(fresh.slot_number, old.slot_number)
        old.refresh_from_db()
        self.assertEqual(old.revoke_reason, "EXPIRED")
        self.assertIsNotNone(old.revoked_at)

    def test_touch_extends_idle_but_not_absolute_expiry(self):
        now = timezone.now()
        row = register_login_session(self.user, "touch-session-key", at=now)
        absolute = row.absolute_expires_at
        touched = touch_login_session(
            self.user, "touch-session-key", at=now + timedelta(minutes=5)
        )
        self.assertIsNotNone(touched)
        self.assertEqual(touched.idle_expires_at, min(
            now + timedelta(minutes=5) + SESSION_IDLE_TIMEOUT, absolute
        ))
        self.assertEqual(touched.absolute_expires_at, absolute)

    def test_only_hash_of_raw_session_key_is_persisted(self):
        raw = "non-secret-test-session-key"
        row = register_login_session(self.user, raw)
        self.assertEqual(row.session_key_hash, session_key_digest(raw))
        self.assertNotEqual(row.session_key_hash, raw)
        self.assertEqual(len(row.session_key_hash), 64)

    def test_session_is_bound_to_user(self):
        other = get_user_model().objects.create_user(username="other-session-user")
        register_login_session(self.user, "bound-session-key")
        self.assertIsNone(touch_login_session(other, "bound-session-key"))


class SessionAdmissionConcurrencyTests(TransactionTestCase):
    """Concurrent admissions must never exceed the DB-enforced two-slot cap."""

    def test_three_concurrent_logins_never_create_more_than_two_active_rows(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        from django.db import close_old_connections, connection

        User = get_user_model()
        user = User.objects.create_user(username="concurrent-session-admission")
        user_id = user.pk
        start = Barrier(3)

        def attempt(index):
            close_old_connections()
            try:
                thread_user = User.objects.get(pk=user_id)
                start.wait(timeout=10)
                register_login_session(
                    thread_user,
                    f"concurrent-session-key-{index}",
                )
                return True
            except SessionAdmissionError:
                return False
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(attempt, range(3)))

        active = SecurityLoginSession.objects.filter(
            user_id=user_id, revoked_at__isnull=True
        ).count()
        self.assertLessEqual(active, 2)
        self.assertEqual(active, sum(results))
        self.assertGreaterEqual(active, 1)
        if connection.features.has_select_for_update:
            self.assertEqual(active, 2)
            self.assertEqual(results.count(True), 2)
