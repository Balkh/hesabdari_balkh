"""Stage 2.3 — posting integrity tests (§1.9, G4).

Idempotent posting (reusing core/idempotency), POSTED/REVERSED immutability
(model + service level), reversal with byte-level original preservation, and
POST/REVERSE audit. Blocked operations must leave database AND audit state
untouched.
"""

from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import TestCase

from core.idempotency import DuplicateOperationError, IdempotencyRecord
from currencies.models import Currency
from documents.models import NumberSequence
from security.models import AuditAction, AuditEvent
from security.services import record_audit_event

from .coa import seed_chart_of_accounts
from .models import Account, JournalEntry, JournalLine, JournalStatus, PostedImmutabilityError
from .services import JournalValidationError, post_journal, reverse_journal, verify_entry_totals


class IntegrityHelpers:
    def _lines(self, amount=Decimal("100.00")):
        return [
            {"account": self.cash, "debit": amount},
            {"account": self.revenue, "credit": amount},
        ]

    def _post(self, number="JE-2301", key=None, amount=Decimal("100.00"), **kwargs):
        params = dict(
            number=number, posting_date="2026-09-09", description="integrity probe",
            lines=self._lines(amount), currency=self.afn,
        )
        params.update(kwargs)
        if key is not None:
            params["idempotency_key"] = key
        return post_journal(**params)

    def _seeded_currencies(self):
        seed_chart_of_accounts()
        afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        usd = Currency.objects.create(code="USD", name="US Dollar")
        return afn, usd


class IdempotentPostingTests(IntegrityHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd = cls._seeded_currencies(cls)
        cls.cash = Account.objects.get(code="1110")
        cls.revenue = Account.objects.get(code="4110")

    def test_first_post_with_key_creates_exactly_one(self):
        entry = self._post("JE-K1", key="k1")
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(JournalLine.objects.count(), 2)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)
        self.assertEqual(entry.idempotency_key, "k1")
        record = IdempotencyRecord.objects.get(key="k1")
        self.assertEqual(record.operation, "journal.post")
        self.assertEqual(record.response_body["journal_entry_id"], entry.id)
        self.assertEqual(len(record.response_body["fingerprint"]), 64)
        self.assertEqual(AuditEvent.objects.filter(action=AuditAction.POST).count(), 1)

    def test_exact_retry_returns_original(self):
        first = self._post("JE-K2", key="k2")
        retry = self._post("JE-K2", key="k2")
        self.assertEqual(retry.pk, first.pk)
        self.assertEqual(retry.number, first.number)
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(JournalLine.objects.count(), 2)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), 1)  # no new audit on retry

    def test_different_key_is_different_transaction(self):
        self._post("JE-KA", key="ka")
        self._post("JE-KB", key="kb")
        self.assertEqual(JournalEntry.objects.count(), 2)
        self.assertEqual(JournalLine.objects.count(), 4)
        self.assertEqual(IdempotencyRecord.objects.count(), 2)

    def test_retry_preserves_original_byte_identical(self):
        first = self._post("JE-K3", key="k3")
        first.refresh_from_db()  # compare persisted state, not in-memory passthrough
        before = [(f.name, getattr(first, f.name)) for f in JournalEntry._meta.concrete_fields]
        self._post("JE-K3", key="k3")
        first.refresh_from_db()
        after = [(f.name, getattr(first, f.name)) for f in JournalEntry._meta.concrete_fields]
        self.assertEqual(before, after)

    def test_failed_post_does_not_poison_key(self):
        bad_lines = [
            {"account": Account.objects.get(code="1000"), "debit": Decimal("10.00")},
            {"account": self.revenue, "credit": Decimal("10.00")},
        ]
        with self.assertRaises(JournalValidationError):
            post_journal(number="JE-K4", posting_date="2026-09-09", description="x",
                         lines=bad_lines, currency=self.afn, idempotency_key="k4")
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)  # reservation rolled back
        self.assertEqual(AuditEvent.objects.count(), 0)
        entry = self._post("JE-K4", key="k4")  # same key reusable after failure
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(entry.idempotency_key, "k4")

    def test_same_key_different_operation_rejected(self):
        self._post("JE-K5", key="k5")
        with self.assertRaises(JournalValidationError):
            self._post("JE-K5-OTHER", key="k5")  # different number
        with self.assertRaises(JournalValidationError):
            self._post("JE-K5", key="k5", amount=Decimal("999.00"))  # different amount
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(JournalLine.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.count(), 1)

    def test_key_validation(self):
        for bad in ("", "x" * 129, 12345):
            with self.subTest(key=repr(bad)[:20]):
                with self.assertRaises(JournalValidationError):
                    self._post("JE-K6", key=bad)
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    def test_unique_db_protection(self):
        IdempotencyRecord.objects.create(key="ku", operation="journal.post")
        with self.assertRaises(IntegrityError):
            IdempotencyRecord.objects.create(key="ku", operation="journal.post")

    def test_orphaned_record_signals_duplicate_not_wrong_result(self):
        first = self._post("JE-KP", key="kp")
        JournalLine.objects.filter(entry_id=first.pk).delete()
        JournalEntry.objects.filter(pk=first.pk).delete()
        with self.assertRaises(DuplicateOperationError):
            self._post("JE-KP", key="kp")

    def test_duplicate_number_with_fresh_key_raises_real_cause(self):
        self._post("JE-DUP")
        with self.assertRaises(IntegrityError):
            self._post("JE-DUP", key="kdup")
        self.assertEqual(IdempotencyRecord.objects.filter(key="kdup").count(), 0)
        self._post("JE-DUP2", key="kdup")  # key not poisoned
        self.assertEqual(JournalEntry.objects.count(), 2)


class ImmutabilityTests(IntegrityHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd = cls._seeded_currencies(cls)
        cls.cash = Account.objects.get(code="1110")
        cls.revenue = Account.objects.get(code="4110")

    def setUp(self):
        self.entry = self._post()

    def test_posted_entry_mutation_rejected(self):
        cases = [
            ("description", "hacked"),
            ("number", "JE-HACK"),
            ("total_debit", Decimal("1.00")),
            ("rate_direction", "XXX"),
            ("source_id", "9"),
            ("currency", self.usd),
        ]
        for field, value in cases:
            with self.subTest(field=field):
                setattr(self.entry, field, value)
                with self.assertRaises(PostedImmutabilityError):
                    self.entry.save()
                self.entry.refresh_from_db()
        self.assertEqual(self.entry.description, "integrity probe")

    def test_posted_line_mutation_rejected(self):
        line = self.entry.lines.order_by("id").first()
        line.debit = Decimal("1.00")
        with self.assertRaises(PostedImmutabilityError):
            line.save()
        line.refresh_from_db()
        line.account = Account.objects.get(code="1120")
        with self.assertRaises(PostedImmutabilityError):
            line.save()
        line.refresh_from_db()
        line.reference = "hacked"
        with self.assertRaises(PostedImmutabilityError):
            line.save()
        draft = JournalEntry.objects.create(number="JE-D1", posting_date="2026-09-09", description="d")
        line.refresh_from_db()
        line.entry = draft
        with self.assertRaises(PostedImmutabilityError):
            line.save()
        stray = JournalLine.objects.create(entry=draft, account=self.cash, debit=Decimal("1.00"))
        stray.entry = self.entry
        with self.assertRaises(PostedImmutabilityError):
            stray.save()

    def test_posted_deletion_rejected(self):
        with self.assertRaises(PostedImmutabilityError):
            self.entry.delete()
        with self.assertRaises(PostedImmutabilityError):
            self.entry.lines.first().delete()
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(JournalLine.objects.count(), 2)

    def test_draft_fully_editable(self):
        draft = JournalEntry.objects.create(number="JE-D2", posting_date="2026-09-09", description="d")
        draft.description = "edited"
        draft.save()
        self.assertEqual(JournalEntry.objects.get(pk=draft.pk).description, "edited")
        line = JournalLine.objects.create(entry=draft, account=self.cash, debit=Decimal("3.00"))
        line.debit = Decimal("4.00")
        line.save()
        self.assertEqual(JournalLine.objects.get(pk=line.pk).debit, Decimal("4.00"))
        line.delete()
        self.assertEqual(JournalLine.objects.count(), 2)  # only posted lines remain
        draft.delete()
        self.assertFalse(JournalEntry.objects.filter(number="JE-D2").exists())

    def test_draft_with_lines_delete_blocked_by_protect(self):
        draft = JournalEntry.objects.create(number="JE-D3", posting_date="2026-09-09", description="d")
        JournalLine.objects.create(entry=draft, account=self.cash, debit=Decimal("3.00"))
        with self.assertRaises(ProtectedError):
            draft.delete()

    def test_line_creation_on_posted_blocked(self):
        with self.assertRaises(PostedImmutabilityError):
            JournalLine.objects.create(entry=self.entry, account=self.cash, debit=Decimal("1.00"))

    def test_bulk_update_bypass_is_a_known_limitation(self):
        """Model guards cover save()/delete(); QuerySet.update() bypasses them.

        This test documents the Django-level limitation. Service code MUST NOT
        use bulk writes on journal rows (only the 0004 backfill migration and
        tests do, by design).
        """
        JournalEntry.objects.filter(pk=self.entry.pk).update(description="bulk")
        self.assertEqual(JournalEntry.objects.get(pk=self.entry.pk).description, "bulk")


class ReversalTests(IntegrityHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd = cls._seeded_currencies(cls)
        cls.cash = Account.objects.get(code="1110")
        cls.revenue = Account.objects.get(code="4110")

    def _posted(self, number="JE-R1", **kwargs):
        return self._post(number, **kwargs)

    def test_valid_reversal_complete(self):
        user = get_user_model().objects.create_user("rev1", password="x")
        original = post_journal(
            number="JE-R1", posting_date="2026-09-09", description="sale",
            lines=[
                {"account": self.cash, "debit": Decimal("100.00"), "reference": "L1"},
                {"account": self.revenue, "credit": Decimal("100.00"), "reference": "L2"},
            ],
            currency=self.afn, source_type="TEST", source_id="S-1",
        )
        reversal = reverse_journal(original, "duplicate entry", user)

        original.refresh_from_db()
        self.assertEqual(original.status, JournalStatus.REVERSED)
        self.assertEqual(reversal.status, JournalStatus.POSTED)
        self.assertEqual(reversal.reverses_id, original.id)
        self.assertEqual(list(original.reversals.all()), [reversal])
        self.assertRegex(reversal.number, r"^JE-\d{4}-\d{5}$")
        self.assertNotEqual(reversal.number, original.number)
        self.assertEqual(reversal.posting_date, original.posting_date)
        self.assertIn("duplicate entry", reversal.description)
        self.assertIn(original.number, reversal.description)
        self.assertEqual(reversal.source_type, "TEST")
        self.assertEqual(reversal.source_id, "S-1")
        self.assertEqual(reversal.currency, self.afn)
        self.assertEqual(reversal.total_debit, original.total_credit)
        self.assertEqual(reversal.total_credit, original.total_debit)
        self.assertEqual(reversal.afn_total, original.afn_total)
        self.assertEqual(reversal.rate, original.rate)
        self.assertEqual(reversal.rate_date, original.rate_date)
        self.assertEqual(reversal.rate_direction, original.rate_direction)
        self.assertEqual(reversal.created_by, user)

        orig_lines = list(original.lines.all().order_by("id"))
        rev_lines = list(reversal.lines.all().order_by("id"))
        self.assertEqual(len(rev_lines), 2)
        for orig, rev in zip(orig_lines, rev_lines):
            self.assertEqual(rev.account_id, orig.account_id)
            self.assertEqual(rev.debit, orig.credit)
            self.assertEqual(rev.credit, orig.debit)
            self.assertEqual(rev.description, orig.description)
            self.assertEqual(rev.reference, orig.reference)
        verify_entry_totals(reversal)

        audits = AuditEvent.objects.filter(action=AuditAction.REVERSE)
        self.assertEqual(audits.count(), 1)
        audit = audits.get()
        self.assertEqual(audit.user, user)
        self.assertEqual(audit.entity, "JournalEntry")
        self.assertEqual(audit.entity_id, str(original.id))
        self.assertEqual(audit.reference, original.number)
        self.assertEqual(audit.reason, "duplicate entry")
        self.assertEqual(audit.previous_state["status"], "POSTED")
        self.assertEqual(audit.new_state["status"], "REVERSED")
        self.assertEqual(audit.new_state["reversal_id"], reversal.id)
        self.assertEqual(audit.new_state["reversal_number"], reversal.number)

    def test_reversal_of_usd_entry_mirrors_snapshot(self):
        original = self._post("JE-RU", currency=self.usd, rate="70", rate_date="2026-09-08")
        reversal = reverse_journal(original, "fx correction", None)
        self.assertEqual(reversal.currency, self.usd)
        self.assertEqual(reversal.rate, Decimal("70.0000"))
        self.assertEqual(reversal.rate_date, original.rate_date)
        self.assertEqual(reversal.rate_direction, "USD->AFN")
        self.assertEqual(reversal.afn_total, original.afn_total)
        self.assertIsNone(reversal.created_by)

    def _snapshot(self, entry):
        entry.refresh_from_db()
        fields = [(f.name, getattr(entry, f.name)) for f in JournalEntry._meta.concrete_fields]
        lines = [(l.account_id, l.debit, l.credit, l.description, l.reference)
                 for l in entry.lines.all().order_by("id")]
        return fields, lines

    def test_original_intact_except_status(self):
        original = self._posted()
        before_fields, before_lines = self._snapshot(original)
        reverse_journal(original, "intact check", None)
        after_fields, after_lines = self._snapshot(original)
        self.assertEqual(before_lines, after_lines)
        diff = [(name, b, a) for (name, b), (_, a) in zip(before_fields, after_fields) if b != a]
        self.assertEqual([(name, b, a) for name, b, a in diff],
                         [("status", JournalStatus.POSTED, JournalStatus.REVERSED)])

    def test_double_reversal_rejected(self):
        original = self._posted()
        reverse_journal(original, "first", None)
        with self.assertRaises(JournalValidationError):
            reverse_journal(JournalEntry.objects.get(pk=original.pk), "second", None)
        self.assertEqual(JournalEntry.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.filter(action=AuditAction.REVERSE).count(), 1)

    def test_reversal_of_reversal_rejected(self):
        original = self._posted()
        reversal = reverse_journal(original, "first", None)
        with self.assertRaises(JournalValidationError):
            reverse_journal(reversal, "chain", None)
        self.assertEqual(JournalEntry.objects.count(), 2)

    def test_draft_reversal_rejected(self):
        draft = JournalEntry.objects.create(number="JE-RD", posting_date="2026-09-09", description="d")
        with self.assertRaises(JournalValidationError):
            reverse_journal(draft, "nope", None)
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_blank_reason_rejected(self):
        original = self._posted()
        for bad in ("", "   "):
            with self.subTest(reason=repr(bad)):
                with self.assertRaises(JournalValidationError):
                    reverse_journal(original, bad, None)
        self.assertEqual(JournalEntry.objects.get(pk=original.pk).status, JournalStatus.POSTED)
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action=AuditAction.REVERSE).count(), 0)

    def test_invalid_user_rejected(self):
        original = self._posted()
        with self.assertRaises(JournalValidationError):
            reverse_journal(original, "reason", "not-a-user")
        self.assertEqual(JournalEntry.objects.count(), 1)

    def test_unpersisted_and_missing_rejected(self):
        with self.assertRaises(JournalValidationError):
            reverse_journal(JournalEntry(), "reason", None)
        ghost = JournalEntry(pk=999999)
        with self.assertRaises(JournalValidationError):
            reverse_journal(ghost, "reason", None)

    def test_corrupt_original_rejected(self):
        original = self._posted()
        JournalEntry.objects.filter(pk=original.pk).update(total_debit=Decimal("1.00"))
        with self.assertRaises(JournalValidationError):
            reverse_journal(JournalEntry.objects.get(pk=original.pk), "reason", None)
        self.assertEqual(JournalEntry.objects.get(pk=original.pk).status, JournalStatus.POSTED)
        self.assertEqual(JournalEntry.objects.count(), 1)

    def test_failed_reversal_atomic(self):
        original = self._posted()
        with mock.patch.object(JournalLine, "save", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                reverse_journal(original, "reason", None)
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(JournalEntry.objects.get(pk=original.pk).status, JournalStatus.POSTED)
        self.assertEqual(AuditEvent.objects.count(), 1)  # only the original POST audit
        self.assertEqual(NumberSequence.objects.count(), 0)  # numbering rolled back

    def test_legacy_null_currency_reversal(self):
        legacy = JournalEntry.objects.create(number="JE-LEG-R", posting_date="2026-09-01", description="legacy")
        JournalLine.objects.create(entry=legacy, account=self.cash, debit=Decimal("100.00"))
        JournalLine.objects.create(entry=legacy, account=self.revenue, credit=Decimal("100.00"))
        legacy.status = JournalStatus.POSTED
        legacy.save()
        JournalEntry.objects.filter(pk=legacy.pk).update(total_debit=Decimal("100.00"), total_credit=Decimal("100.00"))
        reversal = reverse_journal(JournalEntry.objects.get(pk=legacy.pk), "legacy fix", None)
        self.assertIsNone(reversal.currency)
        self.assertIsNone(reversal.afn_total)
        self.assertIsNone(reversal.rate)
        self.assertEqual(reversal.total_debit, Decimal("100.00"))

    def test_pair_nets_to_zero(self):
        original = self._posted()
        reversal = reverse_journal(original, "net check", None)
        for account in (self.cash, self.revenue):
            net = Decimal("0")
            for line in JournalLine.objects.filter(account=account):
                net += line.debit - line.credit
            self.assertEqual(net, Decimal("0"))
        verify_entry_totals(reversal)


class AuditTests(IntegrityHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd = cls._seeded_currencies(cls)
        cls.cash = Account.objects.get(code="1110")
        cls.revenue = Account.objects.get(code="4110")

    def test_posting_emits_post_audit(self):
        user = get_user_model().objects.create_user("aud1", password="x")
        entry = self._post("JE-A1", created_by=user)
        event = AuditEvent.objects.get(action=AuditAction.POST)
        self.assertEqual(event.user, user)
        self.assertEqual(event.entity, "JournalEntry")
        self.assertEqual(event.entity_id, str(entry.id))
        self.assertEqual(event.reference, entry.number)
        self.assertIsNone(event.previous_state)
        self.assertEqual(event.new_state["number"], "JE-A1")
        self.assertEqual(event.new_state["status"], "POSTED")
        self.assertEqual(event.new_state["currency"], "AFN")
        self.assertEqual(len(event.new_state["lines"]), 2)
        self.assertIsNotNone(event.created_at.tzinfo)
        self.assertEqual(event.created_at.utcoffset().total_seconds(), 0)

    def test_retry_emits_no_new_audit(self):
        self._post("JE-A2", key="aud-retry")
        self._post("JE-A2", key="aud-retry")
        self.assertEqual(AuditEvent.objects.count(), 1)

    def test_blocked_ops_emit_no_audit(self):
        entry = self._post("JE-A3")
        reverse_journal(entry, "valid", None)
        self.assertEqual(AuditEvent.objects.count(), 2)  # 1 POST + 1 REVERSE
        entry = JournalEntry.objects.get(number="JE-A3")
        with self.assertRaises(PostedImmutabilityError):
            entry.description = "x"
            entry.save()
        with self.assertRaises(PostedImmutabilityError):
            entry.delete()
        with self.assertRaises(PostedImmutabilityError):
            entry.lines.first().delete()
        with self.assertRaises(JournalValidationError):
            reverse_journal(entry, "double", None)
        draft = JournalEntry.objects.create(number="JE-A4", posting_date="2026-09-09", description="d")
        with self.assertRaises(JournalValidationError):
            reverse_journal(draft, "draft", None)
        with self.assertRaises(JournalValidationError):
            self._post("JE-A5", key="bad", lines=[
                {"account": Account.objects.get(code="1000"), "debit": Decimal("1.00")},
                {"account": self.revenue, "credit": Decimal("1.00")},
            ])
        self.assertEqual(AuditEvent.objects.count(), 2)

    def test_unknown_action_rejected(self):
        with self.assertRaises(ValueError):
            record_audit_event(user=None, action="BOGUS", entity="X")
