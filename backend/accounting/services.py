from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import Account, JournalEntry, JournalLine, JournalStatus


class JournalValidationError(ValueError):
    pass


def post_journal(*, number, posting_date, description, lines, source_type="", source_id=""):
    """Create and atomically post one balanced journal entry."""
    if not lines:
        raise JournalValidationError("A journal entry requires at least one line")
    debit_total = sum((Decimal(str(line.get("debit", 0))) for line in lines), Decimal("0"))
    credit_total = sum((Decimal(str(line.get("credit", 0))) for line in lines), Decimal("0"))
    if debit_total != credit_total:
        raise JournalValidationError("Total debit must equal total credit")
    if debit_total <= 0:
        raise JournalValidationError("A posted journal entry must have a positive total")

    with transaction.atomic():
        entry = JournalEntry.objects.create(
            number=number, posting_date=posting_date, description=description,
            source_type=source_type, source_id=str(source_id), status=JournalStatus.POSTED,
            posted_at=timezone.now(),
        )
        for line in lines:
            account = line["account"]
            if not isinstance(account, Account):
                raise JournalValidationError("Journal line account must be an Account")
            if not account.is_active or not account.is_posting:
                raise JournalValidationError("Journal line account is not usable for posting")
            JournalLine.objects.create(
                entry=entry, account=account,
                debit=Decimal(str(line.get("debit", 0))),
                credit=Decimal(str(line.get("credit", 0))),
                description=line.get("description", ""),
            )
        return entry
