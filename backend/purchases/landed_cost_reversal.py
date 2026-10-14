"""Compensating reversals for posted landed-cost documents.

A reversal is allowed only while no later stock/Transit/cost event depends on
the valuation layer. This conservative gate keeps posted movement snapshots and
downstream COGS immutable; if later events exist, the operator must resolve
that history through a separately reviewed valuation workflow.
"""
from datetime import date

from django.db import transaction

from accounting.models import JournalEntry
from accounting.services import post_journal, verify_entry_totals
from documents.services import next_document_number
from fiscal_periods.services import assert_posting_date_open
from inventory.models import StockMovement
from party_ledger.models import PartyLedgerAttribution
from party_ledger.services import attribute_journal_line
from security.models import AuditAction
from security.services import record_audit_event

from .models import (
    LandedCostDocument, LandedCostReversal, LandedCostReversalAdjustment,
    LandedCostStatus,
)
from .landed_cost_posting import LandedCostPostingError, _jalali_year


def _mirror_lines(entry):
    return [
        {
            "account": line.account,
            "debit": line.credit,
            "credit": line.debit,
            "reference": line.reference,
            "description": f"Compensating reversal: {line.description}",
        }
        for line in entry.lines.select_related("account").order_by("id")
    ]


def _copy_party_attributions(*, original, mirror, user):
    for attribution in PartyLedgerAttribution.objects.filter(
        journal_line__entry=original
    ).select_related("journal_line", "party").order_by("id"):
        source_line = attribution.journal_line
        target_line = mirror.lines.filter(
            account_id=source_line.account_id,
            debit=source_line.credit,
            credit=source_line.debit,
            reference=source_line.reference,
        ).first()
        if target_line is None:
            raise LandedCostPostingError(
                f"Cannot trace payable attribution while reversing journal {original.number}."
            )
        attribute_journal_line(target_line, party=attribution.party, user=user)


def _post_mirror(*, original, posting_date, description, source_type, source_id,
                 idempotency_key, user):
    verify_entry_totals(original)
    if original.status != "POSTED":
        raise LandedCostPostingError(
            f"Journal {original.number} is not POSTED and cannot be compensated by this workflow."
        )
    mirror = post_journal(
        number=next_document_number("JE", _jalali_year(posting_date)),
        posting_date=posting_date,
        description=description,
        lines=_mirror_lines(original),
        source_type=source_type,
        source_id=source_id,
        currency=original.currency,
        rate=original.rate,
        rate_date=original.rate_date,
        created_by=user,
        idempotency_key=idempotency_key,
    )
    _copy_party_attributions(original=original, mirror=mirror, user=user)
    return mirror


def _assert_no_later_activity(*, document):
    if document.posted_at is None:
        raise LandedCostPostingError("Posted landed-cost document has no posting timestamp.")
    product_ids = list(
        document.allocations.values_list("purchase_line__product_id", flat=True).distinct()
    )
    if not product_ids:
        raise LandedCostPostingError("Landed-cost reversal has no traceable source allocations.")

    if StockMovement.objects.filter(
        product_id__in=product_ids, created_at__gt=document.posted_at
    ).exists():
        raise LandedCostPostingError(
            "Cannot reverse this landed cost after a later stock movement; "
            "that movement may have consumed its AVCO layer."
        )

    from goods_in_transit.models import TransitReceipt
    from sales.models import TransitSaleAllocation

    if TransitReceipt.objects.filter(
        lot__purchase_line__product_id__in=product_ids,
        created_at__gt=document.posted_at,
    ).exists():
        raise LandedCostPostingError(
            "Cannot reverse this landed cost after a later Transit receipt/custody event."
        )
    if TransitSaleAllocation.objects.filter(
        transit_lot__purchase_line__product_id__in=product_ids,
        created_at__gt=document.posted_at,
    ).exists():
        raise LandedCostPostingError(
            "Cannot reverse this landed cost after a later Transit sale."
        )
    if LandedCostDocument.objects.filter(
        status=LandedCostStatus.POSTED,
        posted_at__gt=document.posted_at,
        allocations__purchase_line__product_id__in=product_ids,
        reversal__isnull=True,
    ).exclude(pk=document.pk).exists():
        raise LandedCostPostingError(
            "Cannot reverse this landed cost while a later active landed-cost layer exists "
            "for the same product."
        )


@transaction.atomic
def reverse_landed_cost(*, cost_document, reversal_date, reason, user=None,
                        idempotency_key):
    """Post an immutable compensating reversal for one posted landed-cost document.

    The original source and valuation journals remain POSTED and unchanged.
    Reversal is fail-closed when later stock or Transit activity depends on the
    layer, because revaluing those later events requires a separate chronology
    replay rather than blindly undoing their accounting.
    """
    document_id = getattr(cost_document, "pk", cost_document)
    if user is not None and not getattr(user, "is_authenticated", False):
        raise LandedCostPostingError("Authenticated user required.")
    if not isinstance(reversal_date, date):
        raise LandedCostPostingError("A valid reversal date is required.")
    if not isinstance(reason, str) or not reason.strip():
        raise LandedCostPostingError("A reversal reason is required.")
    reason = reason.strip()
    if len(reason) > 500:
        raise LandedCostPostingError("Reversal reason must be at most 500 characters.")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise LandedCostPostingError("A valid idempotency key is required.")
    idempotency_key = idempotency_key.strip()
    if len(idempotency_key) > 128:
        raise LandedCostPostingError("Idempotency key must be at most 128 characters.")

    document = LandedCostDocument.objects.select_for_update(of=("self",)).select_related(
        "currency", "payee", "journal_entry"
    ).get(pk=document_id)

    existing_key = LandedCostReversal.objects.filter(
        idempotency_key=idempotency_key
    ).first()
    if existing_key is not None:
        if (
            existing_key.cost_document_id == document.pk
            and existing_key.reversal_date == reversal_date
            and existing_key.reason == reason
        ):
            return existing_key
        raise LandedCostPostingError("Idempotency key was already used for a different reversal.")

    if LandedCostReversal.objects.filter(cost_document=document).exists():
        raise LandedCostPostingError("This landed-cost document has already been reversed.")
    if document.status != LandedCostStatus.POSTED or document.journal_entry_id is None:
        raise LandedCostPostingError("Only a posted landed-cost document can be reversed.")
    if reversal_date < document.cost_date:
        raise LandedCostPostingError("Reversal date cannot precede the landed-cost date.")
    assert_posting_date_open(reversal_date)
    _assert_no_later_activity(document=document)

    source_reversal = _post_mirror(
        original=document.journal_entry,
        posting_date=reversal_date,
        description=f"Reversal of landed cost {document.document_number}: {reason}",
        source_type="LANDED_COST_REVERSAL",
        source_id=document.document_number,
        idempotency_key=f"landed-cost-reversal:{document.pk}:source",
        user=user,
    )
    reversal = LandedCostReversal.objects.create(
        cost_document=document,
        reversal_date=reversal_date,
        reason=reason,
        journal_entry=source_reversal,
        idempotency_key=idempotency_key,
        created_by=user,
    )

    for adjustment in document.valuation_adjustments.select_related(
        "journal_entry"
    ).order_by("id"):
        mirror = _post_mirror(
            original=adjustment.journal_entry,
            posting_date=reversal_date,
            description=(
                f"Reversal of landed-cost valuation adjustment "
                f"{adjustment.pk} for {document.document_number}: {reason}"
            ),
            source_type="LANDED_COST_REVERSAL_ADJUSTMENT",
            source_id=f"{document.document_number}:ADJ:{adjustment.pk}",
            idempotency_key=(
                f"landed-cost-reversal:{document.pk}:adjustment:{adjustment.pk}"
            ),
            user=user,
        )
        LandedCostReversalAdjustment.objects.create(
            reversal=reversal,
            original_adjustment=adjustment,
            journal_entry=mirror,
        )

    record_audit_event(
        user=user, action=AuditAction.REVERSE, entity="LandedCostReversal",
        entity_id=reversal.pk, reference=document.document_number,
        previous_state={"document_status": document.status, "is_reversed": False},
        new_state={
            "document_status": document.status,
            "is_reversed": True,
            "reversal_id": reversal.pk,
            "source_reversal_journal_id": source_reversal.pk,
            "adjustment_reversal_ids": list(
                reversal.adjustment_reversals.order_by("id").values_list("pk", flat=True)
            ),
        },
        reason=reason,
    )
    return reversal
