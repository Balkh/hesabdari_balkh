"""Phase 3.2 — fiscal period operational/API integration tests.

Proves the thin REST layer is exactly that: shape validation + delegation.
Every behavior asserted here must come from the frozen services; the views
add no rules. Covers API list/create, the four lifecycle actions, bypass
impossibility (no PUT/PATCH/DELETE/status-write surface), uniform error
shape, anonymous rejection (403 per the security-test precedent), D1 empty
bootstrap compatibility, and posted immutability after API reopen.
Frozen Phase 2/3.1 tests are untouched.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounting.coa import seed_chart_of_accounts
from accounting.models import Account, JournalEntry, PostedImmutabilityError
from accounting.services import post_journal
from currencies.models import Currency
from security.models import AuditAction, AuditEvent

from .models import FiscalPeriod, PeriodStatus
from .services import create_period


class ApiFixture:
    COLLECTION = "/api/v1/fiscal-periods/"

    def setUp(self):
        seed_chart_of_accounts()
        self.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        self.user = get_user_model().objects.create_user("p32user", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.n = 0

    def _number(self, prefix="JE-P32"):
        self.n += 1
        return f"{prefix}-{self.n:05d}"

    def _post(self, posting_date, number=None, **kwargs):
        params = dict(
            number=number or self._number(),
            posting_date=posting_date,
            description="api probe",
            lines=[
                {"account": Account.objects.get(code="1110"), "debit": "100.00"},
                {"account": Account.objects.get(code="4110"), "credit": "100.00"},
            ],
            currency=self.afn,
        )
        params.update(kwargs)
        return post_journal(**params)

    def _period(self, name="FY 2026", start="2026-01-01", end="2026-12-31", **kwargs):
        return create_period(name=name, start_date=start, end_date=end, **kwargs)

    def _close_url(self, pk):
        return f"{self.COLLECTION}{pk}/close/"

    def _reopen_url(self, pk):
        return f"{self.COLLECTION}{pk}/reopen/"

    def _lock_url(self, pk):
        return f"{self.COLLECTION}{pk}/lock/"

    def _unlock_url(self, pk):
        return f"{self.COLLECTION}{pk}/unlock/"

    def assertErrorShape(self, response, code="http_400"):
        body = response.json()
        self.assertIn("error", body)
        self.assertEqual(body["error"]["code"], code)
        self.assertTrue(body["error"]["message"])


class PeriodApiListCreateTests(ApiFixture, TestCase):
    def test_list_empty_returns_empty_array_and_creates_nothing(self):
        response = self.client.get(self.COLLECTION)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        self.assertEqual(FiscalPeriod.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_list_returns_authoritative_fields(self):
        period = self._period(user=self.user)
        response = self.client.get(self.COLLECTION)
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["id"], period.pk)
        self.assertEqual(row["name"], "FY 2026")
        self.assertEqual(row["start_date"], "2026-01-01")
        self.assertEqual(row["end_date"], "2026-12-31")
        self.assertEqual(row["status"], PeriodStatus.OPEN)
        self.assertTrue(row["start_date_jalali"])
        self.assertTrue(row["end_date_jalali"])
        self.assertNotEqual(row["start_date_jalali"], row["end_date_jalali"])

    def test_list_rejects_anonymous(self):
        self._period(user=self.user)
        response = APIClient().get(self.COLLECTION)
        self.assertEqual(response.status_code, 403)

    def test_create_valid_returns_201_open_with_audit(self):
        response = self.client.post(
            self.COLLECTION,
            {"name": "FY 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["name"], "FY 2026")
        self.assertEqual(body["status"], PeriodStatus.OPEN)
        self.assertIsNone(body["closed_at"])
        period = FiscalPeriod.objects.get(pk=body["id"])
        self.assertEqual(str(period.start_date), "2026-01-01")
        event = AuditEvent.objects.get(
            action=AuditAction.CREATE, entity="FiscalPeriod", entity_id=str(period.pk)
        )
        self.assertEqual(event.user, self.user)

    def test_create_invalid_range_returns_400_without_row_or_audit(self):
        response = self.client.post(
            self.COLLECTION,
            {"name": "Bad", "start_date": "2026-12-31", "end_date": "2026-01-01"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertErrorShape(response)
        self.assertIn("cannot be after", response.json()["error"]["message"])
        self.assertEqual(FiscalPeriod.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_create_overlap_returns_400_without_row_or_audit(self):
        self._period(name="First", user=self.user)
        response = self.client.post(
            self.COLLECTION,
            {"name": "Second", "start_date": "2026-06-01", "end_date": "2026-12-31"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertErrorShape(response)
        self.assertIn("overlaps", response.json()["error"]["message"])
        self.assertEqual(FiscalPeriod.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action=AuditAction.CREATE).count(), 1)

    def test_create_rejects_anonymous_without_side_effects(self):
        response = APIClient().post(
            self.COLLECTION,
            {"name": "FY 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(FiscalPeriod.objects.count(), 0)

    def test_create_missing_field_returns_400_without_row(self):
        response = self.client.post(
            self.COLLECTION, {"name": "Shapeless"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertErrorShape(response)
        self.assertEqual(FiscalPeriod.objects.count(), 0)


class PeriodApiLifecycleTests(ApiFixture, TestCase):
    def test_close_open_returns_200_closed_with_audit(self):
        period = self._period(user=self.user)
        self._post("2026-03-15")
        response = self.client.post(
            self._close_url(period.pk), {"reason": "year-end"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], PeriodStatus.CLOSED)
        self.assertIsNotNone(body["closed_at"])
        period.refresh_from_db()
        self.assertEqual(period.status, PeriodStatus.CLOSED)
        event = AuditEvent.objects.get(
            action=AuditAction.UPDATE, entity="FiscalPeriod", entity_id=str(period.pk)
        )
        self.assertEqual(event.user, self.user)
        self.assertIn("journals_verified", event.new_state or {})

    def test_close_repeat_returns_200_without_new_audit(self):
        period = self._period(user=self.user)
        url = self._close_url(period.pk)
        first = self.client.post(url, {"reason": "year-end"}, format="json")
        self.assertEqual(first.status_code, 200)
        audits_before = AuditEvent.objects.count()
        second = self.client.post(url, {"reason": "again"}, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["status"], PeriodStatus.CLOSED)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_close_corrupt_journal_returns_400_and_stays_open(self):
        period = self._period(user=self.user)
        entry = self._post("2026-03-15")
        JournalEntry.objects.filter(pk=entry.pk).update(total_debit="1.00")
        response = self.client.post(
            self._close_url(period.pk), {"reason": "year-end"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertErrorShape(response)
        self.assertIn("integrity check", response.json()["error"]["message"])
        period.refresh_from_db()
        self.assertEqual(period.status, PeriodStatus.OPEN)
        self.assertFalse(
            AuditEvent.objects.filter(
                action=AuditAction.UPDATE, entity="FiscalPeriod"
            ).exists()
        )

    def test_close_rejects_anonymous_and_stays_open(self):
        period = self._period(user=self.user)
        response = APIClient().post(
            self._close_url(period.pk), {"reason": "year-end"}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        period.refresh_from_db()
        self.assertEqual(period.status, PeriodStatus.OPEN)

    def test_reopen_with_reason_returns_200_open_with_audit(self):
        period = self._period(user=self.user)
        self.client.post(self._close_url(period.pk), {"reason": "year-end"}, format="json")
        response = self.client.post(
            self._reopen_url(period.pk), {"reason": "correction"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], PeriodStatus.OPEN)
        event = AuditEvent.objects.filter(
            action=AuditAction.UPDATE, entity="FiscalPeriod", entity_id=str(period.pk)
        ).order_by("id").last()
        self.assertEqual(event.user, self.user)
        self.assertIn("correction", event.reason)

    def test_reopen_without_reason_returns_400_and_stays_closed(self):
        period = self._period(user=self.user)
        self.client.post(self._close_url(period.pk), {"reason": "year-end"}, format="json")
        audits_before = AuditEvent.objects.count()
        response = self.client.post(self._reopen_url(period.pk), {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertErrorShape(response)
        self.assertIn("Reason is required", response.json()["error"]["message"])
        period.refresh_from_db()
        self.assertEqual(period.status, PeriodStatus.CLOSED)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_reopen_rejects_anonymous_and_stays_closed(self):
        period = self._period(user=self.user)
        self.client.post(self._close_url(period.pk), {"reason": "year-end"}, format="json")
        response = APIClient().post(
            self._reopen_url(period.pk), {"reason": "correction"}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        period.refresh_from_db()
        self.assertEqual(period.status, PeriodStatus.CLOSED)

    def test_posted_rows_stay_immutable_after_api_reopen(self):
        period = self._period(user=self.user)
        entry = self._post("2026-03-15")
        self.client.post(self._close_url(period.pk), {"reason": "year-end"}, format="json")
        reopened = self.client.post(
            self._reopen_url(period.pk), {"reason": "correction"}, format="json"
        )
        self.assertEqual(reopened.status_code, 200)
        entry.description = "mutated after reopen"
        with self.assertRaises(PostedImmutabilityError):
            entry.save()

    def test_lock_open_returns_200_locked_then_rejects_close(self):
        period = self._period(user=self.user)
        locked = self.client.post(
            self._lock_url(period.pk), {"reason": "freeze"}, format="json"
        )
        self.assertEqual(locked.status_code, 200)
        self.assertEqual(locked.json()["status"], PeriodStatus.LOCKED)
        refused = self.client.post(
            self._close_url(period.pk), {"reason": "year-end"}, format="json"
        )
        self.assertEqual(refused.status_code, 400)
        self.assertIn("LOCKED", refused.json()["error"]["message"])

    def test_lock_closed_returns_400_and_stays_closed(self):
        period = self._period(user=self.user)
        self.client.post(self._close_url(period.pk), {"reason": "year-end"}, format="json")
        response = self.client.post(
            self._lock_url(period.pk), {"reason": "freeze"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("CLOSED", response.json()["error"]["message"])
        period.refresh_from_db()
        self.assertEqual(period.status, PeriodStatus.CLOSED)

    def test_unlock_with_reason_returns_200_open(self):
        period = self._period(user=self.user)
        self.client.post(self._lock_url(period.pk), {"reason": "freeze"}, format="json")
        response = self.client.post(
            self._unlock_url(period.pk), {"reason": "resume"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], PeriodStatus.OPEN)

    def test_unlock_without_reason_returns_400_and_stays_locked(self):
        period = self._period(user=self.user)
        self.client.post(self._lock_url(period.pk), {"reason": "freeze"}, format="json")
        audits_before = AuditEvent.objects.count()
        response = self.client.post(self._unlock_url(period.pk), {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Reason is required", response.json()["error"]["message"])
        period.refresh_from_db()
        self.assertEqual(period.status, PeriodStatus.LOCKED)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_unlock_closed_returns_400_and_stays_closed(self):
        period = self._period(user=self.user)
        self.client.post(self._close_url(period.pk), {"reason": "year-end"}, format="json")
        response = self.client.post(
            self._unlock_url(period.pk), {"reason": "resume"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("CLOSED", response.json()["error"]["message"])
        period.refresh_from_db()
        self.assertEqual(period.status, PeriodStatus.CLOSED)

    def test_status_has_no_write_surface_anywhere(self):
        period = self._period(user=self.user)
        attempts = [
            ("put", self.COLLECTION, {"status": "CLOSED"}),
            ("patch", self.COLLECTION, {"status": "CLOSED"}),
            ("delete", self.COLLECTION, None),
            ("put", self._close_url(period.pk), {"status": "OPEN"}),
            ("patch", self._reopen_url(period.pk), {"status": "CLOSED"}),
            ("delete", self._lock_url(period.pk), None),
            ("get", self._close_url(period.pk), None),
        ]
        for method, url, payload in attempts:
            with self.subTest(method=method, url=url):
                caller = getattr(self.client, method)
                kwargs = {"format": "json"}
                if payload is not None:
                    kwargs["data"] = payload
                response = caller(url, **kwargs)
                self.assertEqual(response.status_code, 405)
        period.refresh_from_db()
        self.assertEqual(period.status, PeriodStatus.OPEN)

    def test_unknown_period_and_action_return_404(self):
        missing = self.client.post(
            self._close_url(424242), {"reason": "x"}, format="json"
        )
        self.assertEqual(missing.status_code, 404)
        self.assertErrorShape(missing, code="http_404")
        unknown = self.client.post(
            f"{self.COLLECTION}{1}/explode/", {"reason": "x"}, format="json"
        )
        self.assertEqual(unknown.status_code, 404)


class PeriodApiBootstrapTests(ApiFixture, TestCase):
    def test_d1_empty_state_stays_stable_until_first_create(self):
        first_list = self.client.get(self.COLLECTION)
        second_list = self.client.get(self.COLLECTION)
        self.assertEqual(first_list.json(), [])
        self.assertEqual(second_list.json(), [])
        self.assertEqual(FiscalPeriod.objects.count(), 0)
        created = self.client.post(
            self.COLLECTION,
            {"name": "FY 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        listed = self.client.get(self.COLLECTION)
        self.assertEqual(len(listed.json()), 1)
        self.assertEqual(FiscalPeriod.objects.count(), 1)
