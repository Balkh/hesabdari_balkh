"""Fiscal period lifecycle and the single authoritative posting-date gate.

Phase 3.1 (Phase 0 §12). Every financial posting — current (journals,
reversals) and future (purchase, sales, payments, ...) — validates its
posting date through ``assert_posting_date_open``. There is exactly one
gate; no per-module copies.

D1 bootstrap rule (user-approved): while the period table is EMPTY, posting
is permitted (legacy-open mode) so the frozen Phase 2 suite and pre-period
history keep working byte-identical. The moment the first period exists,
every posting date must resolve to exactly one OPEN period — no fallback.

No new engines: dates via the frozen coercion, timestamps via
``core.dates.utc_timestamp``, audit via ``security.services``, integrity
via ``accounting.services.verify_entry_totals``.
"""

from django.contrib.auth import get_user_model
from django.db import transaction

from accounting.models import JournalEntry
from core.dates import utc_timestamp
from security.models import AuditAction
from security.services import record_audit_event

from .models import FiscalPeriod, PeriodStatus


class PeriodValidationError(ValueError):
    """Deterministic fiscal-period rejection (service-error convention)."""


# ---------------------------------------------------------------------------
# Shared helpers (reuse frozen utilities — no forks, no new engines)
# ---------------------------------------------------------------------------

def _coerce_date(value, field_name):
    """Shared ISO/Gregorian date coercion.

    Imported lazily: ``accounting.services`` imports this module for the
    posting gate, so a top-level import back would cycle.
    """
    from accounting.services import _as_date
    try:
        return _as_date(value, field_name)
    except ValueError as exc:
        raise PeriodValidationError(str(exc)) from exc


def _require_user(user, action):
    if user is None:
        raise PeriodValidationError(
            f"Authorization required to {action}: an authenticated user is required."
        )
    if not isinstance(user, get_user_model()):
        raise PeriodValidationError(f"Authorization required to {action}: user must be a user.")
    return user


def _require_reason(reason):
    if not isinstance(reason, str) or not reason.strip():
        raise PeriodValidationError("Reason is required to reopen/unlock fiscal period.")
    return reason.strip()


def _coerce_period(period):
    if not isinstance(period, FiscalPeriod) or period.pk is None:
        raise PeriodValidationError("A persisted fiscal period is required.")
    return period


def _locked_period(pk):
    try:
        return FiscalPeriod.objects.select_for_update().get(pk=pk)
    except FiscalPeriod.DoesNotExist:
        raise PeriodValidationError("Fiscal period does not exist.") from None


def _snapshot(period):
    return {
        "id": period.id,
        "name": period.name,
        "start_date": str(period.start_date),
        "end_date": str(period.end_date),
        "status": period.status,
        "closed_at": period.closed_at.isoformat() if period.closed_at else None,
    }


def _audit_transition(*, user, period, previous_state, reason):
    record_audit_event(
        user=user, action=AuditAction.UPDATE, entity="FiscalPeriod",
        entity_id=period.id, reference=period.name,
        previous_state=previous_state, new_state=_snapshot(period),
        reason=reason or "",
    )


# ---------------------------------------------------------------------------
# Period resolution — the single authoritative gate
# ---------------------------------------------------------------------------

def find_period_for_date(value):
    """Return the one period covering ``value``, or None.

    Raises PeriodValidationError when several periods cover the date:
    ambiguous resolution is a data-integrity failure and is never guessed.
    """
    day = _coerce_date(value, "posting_date")
    matches = list(
        FiscalPeriod.objects.filter(start_date__lte=day, end_date__gte=day).order_by("id")
    )
    if len(matches) > 1:
        raise PeriodValidationError(
            "Ambiguous fiscal period resolution for "
            f"{day}: " + ", ".join(p.name for p in matches) + "."
        )
    return matches[0] if matches else None


def assert_posting_date_open(value):
    """Allow posting only when ``value`` falls in an OPEN fiscal period.

    Returns the covering OPEN period. Returns None in D1 bootstrap mode
    (no periods defined at all). Raises PeriodValidationError otherwise —
    including when periods exist but none covers the date (no fallback).
    """
    day = _coerce_date(value, "posting_date")
    period = find_period_for_date(day)
    if period is not None:
        if period.status == PeriodStatus.OPEN:
            return period
        if period.status == PeriodStatus.CLOSED:
            raise PeriodValidationError(f"Fiscal period is CLOSED: {period.name}.")
        raise PeriodValidationError(f"Fiscal period is LOCKED: {period.name}.")
    if FiscalPeriod.objects.exists():
        raise PeriodValidationError(f"No fiscal period covers posting date: {day}.")
    return None


# ---------------------------------------------------------------------------
# Lifecycle (all transitions atomic + audited)
# ---------------------------------------------------------------------------

def create_period(*, name, start_date, end_date, user=None):
    """Create one OPEN period.

    Periods are always born OPEN; closing/locking are explicit audited
    transitions. Overlapping periods are rejected so resolution stays
    unambiguous (contract §12 is silent on overlap; ambiguity is forbidden,
    so overlap is refused at the service boundary).
    """
    if not isinstance(name, str) or not name.strip():
        raise PeriodValidationError("Fiscal period name is required.")
    if user is not None and not isinstance(user, get_user_model()):
        raise PeriodValidationError("created_by must be a user or None.")
    start = _coerce_date(start_date, "start_date")
    end = _coerce_date(end_date, "end_date")
    if start > end:
        raise PeriodValidationError("Fiscal period start_date cannot be after end_date.")
    with transaction.atomic():
        clash = FiscalPeriod.objects.filter(
            start_date__lte=end, end_date__gte=start
        ).order_by("id").first()
        if clash is not None:
            raise PeriodValidationError(
                f"Fiscal period overlaps existing period: {clash.name}."
            )
        period = FiscalPeriod.objects.create(
            name=name.strip(), start_date=start, end_date=end,
            status=PeriodStatus.OPEN,
        )
        record_audit_event(
            user=user, action=AuditAction.CREATE, entity="FiscalPeriod",
            entity_id=period.id, reference=period.name,
            previous_state=None, new_state=_snapshot(period), reason="",
        )
        return period


def _verify_range_balanced(period):
    """Close-validation (§12.5 "verifies balanced journals").

    Every posted/reversed journal in range must carry intact stored totals.
    Any mismatch rejects the close. Read-only: detection never repairs.
    (Per-entry checks mathematically imply a balanced range, with no
    currency merging — the frozen read layer's multi-currency refusal is
    respected by never summing across journals.)
    """
    from accounting.balances import EFFECTIVE_STATUSES
    from accounting.services import verify_entry_totals
    entries = JournalEntry.objects.filter(
        posting_date__gte=period.start_date, posting_date__lte=period.end_date,
        status__in=EFFECTIVE_STATUSES,
    ).order_by("id")
    checked = 0
    for entry in entries:
        try:
            verify_entry_totals(entry)
        except ValueError as exc:
            raise PeriodValidationError(
                "Cannot close fiscal period "
                f"{period.name}: journal {entry.number} failed integrity check."
            ) from exc
        checked += 1
    return checked


def close_period(period, *, user, reason=""):
    """OPEN → CLOSED, atomically: integrity-check the range, flip status,
    stamp closed_at, audit. Repeat on CLOSED is a no-op. From LOCKED is
    forbidden (§8: no LOCKED → CLOSED)."""
    _coerce_period(period)
    _require_user(user, "close fiscal period")
    if not isinstance(reason, str):
        raise PeriodValidationError("Close reason must be text.")
    with transaction.atomic():
        current = _locked_period(period.pk)
        if current.status == PeriodStatus.CLOSED:
            return current  # idempotent repeat: nothing happened, nothing audited
        if current.status == PeriodStatus.LOCKED:
            raise PeriodValidationError(
                "A LOCKED fiscal period cannot be closed; unlock it first."
            )
        if current.status != PeriodStatus.OPEN:
            raise PeriodValidationError(
                f"Cannot close fiscal period from status {current.status}."
            )
        checked = _verify_range_balanced(current)
        previous_state = _snapshot(current)
        current.status = PeriodStatus.CLOSED
        current.closed_at = utc_timestamp()
        current.save(update_fields=["status", "closed_at"])
        state = _snapshot(current)
        state["journals_verified"] = checked
        record_audit_event(
            user=user, action=AuditAction.UPDATE, entity="FiscalPeriod",
            entity_id=current.id, reference=current.name,
            previous_state=previous_state, new_state=state, reason=reason.strip(),
        )
        return current


def reopen_period(period, *, user, reason):
    """CLOSED → OPEN. Requires authenticated user + reason; audited.

    Reopening never makes posted journals editable (Phase 2 immutability
    is untouched); it only permits NEW postings with their own gate check.
    """
    _coerce_period(period)
    _require_user(user, "reopen fiscal period")
    clean_reason = _require_reason(reason)
    with transaction.atomic():
        current = _locked_period(period.pk)
        if current.status == PeriodStatus.OPEN:
            return current  # idempotent repeat
        if current.status == PeriodStatus.LOCKED:
            raise PeriodValidationError(
                "A LOCKED fiscal period cannot be reopened; unlock it first."
            )
        if current.status != PeriodStatus.CLOSED:
            raise PeriodValidationError(
                f"Cannot reopen fiscal period from status {current.status}."
            )
        previous_state = _snapshot(current)
        current.status = PeriodStatus.OPEN
        current.closed_at = None
        current.save(update_fields=["status", "closed_at"])
        _audit_transition(user=user, period=current, previous_state=previous_state,
                          reason=clean_reason)
        return current


def lock_period(period, *, user, reason=""):
    """OPEN → LOCKED. Repeat on LOCKED is a no-op. From CLOSED is
    forbidden (§8: no CLOSED → LOCKED)."""
    _coerce_period(period)
    _require_user(user, "lock fiscal period")
    if not isinstance(reason, str):
        raise PeriodValidationError("Lock reason must be text.")
    with transaction.atomic():
        current = _locked_period(period.pk)
        if current.status == PeriodStatus.LOCKED:
            return current  # idempotent repeat
        if current.status == PeriodStatus.CLOSED:
            raise PeriodValidationError(
                "A CLOSED fiscal period cannot be locked; reopen it first."
            )
        if current.status != PeriodStatus.OPEN:
            raise PeriodValidationError(
                f"Cannot lock fiscal period from status {current.status}."
            )
        previous_state = _snapshot(current)
        current.status = PeriodStatus.LOCKED
        current.save(update_fields=["status"])
        _audit_transition(user=user, period=current, previous_state=previous_state,
                          reason=reason.strip())
        return current


def unlock_period(period, *, user, reason):
    """LOCKED → OPEN. Requires authenticated user + reason; audited."""
    _coerce_period(period)
    _require_user(user, "unlock fiscal period")
    clean_reason = _require_reason(reason)
    with transaction.atomic():
        current = _locked_period(period.pk)
        if current.status == PeriodStatus.OPEN:
            return current  # idempotent repeat
        if current.status == PeriodStatus.CLOSED:
            raise PeriodValidationError(
                "A CLOSED fiscal period cannot be unlocked; reopen it first."
            )
        if current.status != PeriodStatus.LOCKED:
            raise PeriodValidationError(
                f"Cannot unlock fiscal period from status {current.status}."
            )
        previous_state = _snapshot(current)
        current.status = PeriodStatus.OPEN
        current.closed_at = None
        current.save(update_fields=["status", "closed_at"])
        _audit_transition(user=user, period=current, previous_state=previous_state,
                          reason=clean_reason)
        return current
