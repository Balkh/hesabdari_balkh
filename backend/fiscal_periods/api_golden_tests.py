"""Phase 3.2 — golden API scenarios (printed, human-verifiable).

Each scenario drives the REAL HTTP boundary (APIClient through URL routing,
auth, serializers, views) into the frozen services and prints the
request/response/audit trail. Run with ``-s`` to capture the trail.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounting.coa import seed_chart_of_accounts
from accounting.models import Account, JournalEntry, PostedImmutabilityError
from accounting.services import post_journal
from currencies.models import Currency
from security.models import AuditEvent

from .models import FiscalPeriod, PeriodStatus


class GoldenApiFixture:
    COLLECTION = "/api/v1/fiscal-periods/"

    def setUp(self):
        seed_chart_of_accounts()
        self.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        self.user = get_user_model().objects.create_user("p32gold", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.n = 0

    def _number(self, prefix="JE-G32"):
        self.n += 1
        return f"{prefix}-{self.n:05d}"

    def _post(self, posting_date, number=None, **kwargs):
        params = dict(
            number=number or self._number(),
            posting_date=posting_date,
            description="golden api probe",
            lines=[
                {"account": Account.objects.get(code="1110"), "debit": "100.00"},
                {"account": Account.objects.get(code="4110"), "credit": "100.00"},
            ],
            currency=self.afn,
        )
        params.update(kwargs)
        return post_journal(**params)

    def _show(self, tag, response):
        print(f"  [{tag}] HTTP {response.status_code} -> {response.json()}")

    def _audits(self, entity_id):
        return list(
            AuditEvent.objects.filter(
                entity="FiscalPeriod", entity_id=str(entity_id)
            ).order_by("id")
        )


class ApiGoldenTests(GoldenApiFixture, TestCase):
    def test_g32_01_period_list_and_create(self):
        print("G32-01 list empty, create FY 2026, list again:")
        listed = self.client.get(self.COLLECTION)
        self._show("GET collection (empty)", listed)
        self.assertEqual(listed.json(), [])
        created = self.client.post(
            self.COLLECTION,
            {"name": "FY 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            format="json",
        )
        self._show("POST collection", created)
        self.assertEqual(created.status_code, 201)
        body = created.json()
        self.assertEqual(body["status"], PeriodStatus.OPEN)
        listed = self.client.get(self.COLLECTION)
        self._show("GET collection (one row)", listed)
        self.assertEqual(len(listed.json()), 1)
        print("PASS G32-01")

    def test_g32_02_close_through_boundary(self):
        print("G32-02 create, post balanced journal, close:")
        created = self.client.post(
            self.COLLECTION,
            {"name": "FY 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            format="json",
        )
        pk = created.json()["id"]
        entry = self._post("2026-04-10")
        print(f"  [journal] posted {entry.number} on 2026-04-10")
        closed = self.client.post(
            f"{self.COLLECTION}{pk}/close/", {"reason": "year-end"}, format="json"
        )
        self._show("POST close", closed)
        self.assertEqual(closed.json()["status"], PeriodStatus.CLOSED)
        for event in self._audits(pk):
            print(f"  [audit] {event.action} by={event.user} values={event.new_state}")
        self.assertEqual(len(self._audits(pk)), 2)
        print("PASS G32-02")

    def test_g32_03_reopen_with_reason_and_audit(self):
        print("G32-03 close then reopen with reason:")
        pk = self.client.post(
            self.COLLECTION,
            {"name": "FY 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            format="json",
        ).json()["id"]
        self.client.post(f"{self.COLLECTION}{pk}/close/", {"reason": "y"}, format="json")
        reopened = self.client.post(
            f"{self.COLLECTION}{pk}/reopen/", {"reason": "correction"}, format="json"
        )
        self._show("POST reopen", reopened)
        self.assertEqual(reopened.json()["status"], PeriodStatus.OPEN)
        last = self._audits(pk)[-1]
        print(f"  [audit] {last.action} reason={last.reason}")
        self.assertIn("correction", last.reason)
        print("PASS G32-03")

    def test_g32_04_lock(self):
        print("G32-04 lock an open period:")
        pk = self.client.post(
            self.COLLECTION,
            {"name": "FY 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            format="json",
        ).json()["id"]
        locked = self.client.post(
            f"{self.COLLECTION}{pk}/lock/", {"reason": "freeze"}, format="json"
        )
        self._show("POST lock", locked)
        self.assertEqual(locked.json()["status"], PeriodStatus.LOCKED)
        print("PASS G32-04")

    def test_g32_05_unlock_with_reason_and_audit(self):
        print("G32-05 lock then unlock with reason:")
        pk = self.client.post(
            self.COLLECTION,
            {"name": "FY 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            format="json",
        ).json()["id"]
        self.client.post(f"{self.COLLECTION}{pk}/lock/", {"reason": "f"}, format="json")
        unlocked = self.client.post(
            f"{self.COLLECTION}{pk}/unlock/", {"reason": "resume"}, format="json"
        )
        self._show("POST unlock", unlocked)
        self.assertEqual(unlocked.json()["status"], PeriodStatus.OPEN)
        last = self._audits(pk)[-1]
        print(f"  [audit] {last.action} reason={last.reason}")
        self.assertIn("resume", last.reason)
        print("PASS G32-05")

    def test_g32_06_unauthorized_rejection(self):
        print("G32-06 anonymous client is rejected everywhere:")
        pk = self.client.post(
            self.COLLECTION,
            {"name": "FY 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            format="json",
        ).json()["id"]
        anon = APIClient()
        probes = [
            ("GET collection", anon.get(self.COLLECTION)),
            ("POST collection", anon.post(self.COLLECTION, {"name": "X"}, format="json")),
            ("POST close", anon.post(f"{self.COLLECTION}{pk}/close/", {}, format="json")),
            ("POST reopen", anon.post(f"{self.COLLECTION}{pk}/reopen/", {}, format="json")),
            ("POST lock", anon.post(f"{self.COLLECTION}{pk}/lock/", {}, format="json")),
            ("POST unlock", anon.post(f"{self.COLLECTION}{pk}/unlock/", {}, format="json")),
        ]
        for tag, response in probes:
            self._show(tag, response)
            self.assertEqual(response.status_code, 403)
        self.assertEqual(FiscalPeriod.objects.count(), 1)
        print("PASS G32-06")

    def test_g32_07_domain_error_propagation(self):
        print("G32-07 domain rejections surface as the error shape:")
        pk = self.client.post(
            self.COLLECTION,
            {"name": "FY 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            format="json",
        ).json()["id"]
        overlap = self.client.post(
            self.COLLECTION,
            {"name": "Clash", "start_date": "2026-05-01", "end_date": "2026-08-01"},
            format="json",
        )
        self._show("POST overlapping", overlap)
        self.assertEqual(overlap.status_code, 400)
        self.assertEqual(overlap.json()["error"]["code"], "http_400")
        self.client.post(f"{self.COLLECTION}{pk}/lock/", {"reason": "f"}, format="json")
        bad_close = self.client.post(
            f"{self.COLLECTION}{pk}/close/", {"reason": "y"}, format="json"
        )
        self._show("POST close on LOCKED", bad_close)
        self.assertEqual(bad_close.status_code, 400)
        print("PASS G32-07")

    def test_g32_08_no_bypass(self):
        print("G32-08 mutation surface that must not exist:")
        pk = self.client.post(
            self.COLLECTION,
            {"name": "FY 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            format="json",
        ).json()["id"]
        attempts = [
            ("PUT collection", self.client.put(self.COLLECTION, {"status": "CLOSED"}, format="json")),
            ("PATCH collection", self.client.patch(self.COLLECTION, {"status": "CLOSED"}, format="json")),
            ("DELETE collection", self.client.delete(self.COLLECTION)),
            ("PUT close", self.client.put(f"{self.COLLECTION}{pk}/close/", {"status": "OPEN"}, format="json")),
            ("DELETE lock", self.client.delete(f"{self.COLLECTION}{pk}/lock/")),
            ("GET close", self.client.get(f"{self.COLLECTION}{pk}/close/")),
        ]
        for tag, response in attempts:
            print(f"  [{tag}] HTTP {response.status_code}")
            self.assertEqual(response.status_code, 405)
        period = FiscalPeriod.objects.get(pk=pk)
        self.assertEqual(period.status, PeriodStatus.OPEN)
        print("PASS G32-08")

    def test_g32_09_immutability_after_reopen(self):
        print("G32-09 posted rows stay immutable after API reopen:")
        pk = self.client.post(
            self.COLLECTION,
            {"name": "FY 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            format="json",
        ).json()["id"]
        entry = self._post("2026-04-10")
        self.client.post(f"{self.COLLECTION}{pk}/close/", {"reason": "y"}, format="json")
        reopened = self.client.post(
            f"{self.COLLECTION}{pk}/reopen/", {"reason": "fix"}, format="json"
        )
        self._show("POST reopen", reopened)
        entry.description = "mutated after reopen"
        with self.assertRaises(PostedImmutabilityError):
            entry.save()
        print("  [immutability] posted row mutation refused")
        print("PASS G32-09")

    def test_g32_10_d1_empty_compatibility(self):
        print("G32-10 empty database stays legacy-open until first create:")
        first = self.client.get(self.COLLECTION)
        self._show("GET collection (empty)", first)
        self.assertEqual(first.json(), [])
        created = self.client.post(
            self.COLLECTION,
            {"name": "FY 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            format="json",
        )
        self._show("POST first period", created)
        self.assertEqual(created.status_code, 201)
        print("PASS G32-10")
