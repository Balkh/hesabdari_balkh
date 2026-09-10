# Stage 2.2 data migration: backfill stored journal totals from each entry's
# own lines. Deterministic derivation — NOT a historical rewrite:
# - only total_debit/total_credit are written, computed from line sums;
# - currency/afn_total/rate snapshot stay NULL (legacy context is unknown and
#   MUST NOT be fabricated);
# - journals, lines, accounts are otherwise untouched.

from decimal import Decimal

from django.db import migrations


def backfill_totals(apps, schema_editor):
    JournalEntry = apps.get_model("accounting", "JournalEntry")
    JournalLine = apps.get_model("accounting", "JournalLine")
    for entry in JournalEntry.objects.all().order_by("id"):
        lines = JournalLine.objects.filter(entry_id=entry.id)
        debit = sum((line.debit for line in lines), Decimal("0"))
        credit = sum((line.credit for line in lines), Decimal("0"))
        JournalEntry.objects.filter(id=entry.id).update(total_debit=debit, total_credit=credit)


def zero_totals(apps, schema_editor):
    JournalEntry = apps.get_model("accounting", "JournalEntry")
    JournalEntry.objects.all().update(total_debit=Decimal("0.00"), total_credit=Decimal("0.00"))


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0003_journal_currency_contract"),
    ]

    operations = [
        migrations.RunPython(backfill_totals, reverse_code=zero_totals),
    ]
