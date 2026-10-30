"""Safely initialize the canonical accounting master data on a fresh database.

This command is intentionally manual. It is never invoked during app startup or
as part of schema migrations.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounting.coa import CANONICAL_COA, seed_chart_of_accounts
from accounting.models import Account
from currencies.models import Currency
from security.models import AuditAction, AuditEvent
from security.services import record_audit_event


CURRENCY_DEFINITIONS = (
    # code, name, symbol, decimal_places, is_base, is_active
    ("AFN", "Afghani", "؋", 2, True, True),
    ("USD", "US Dollar", "$", 2, False, True),
)

BOOTSTRAP_AUDIT_ENTITY = "SystemBootstrap"
BOOTSTRAP_AUDIT_REFERENCE = "fresh-database-v1"


def _verify_existing_configuration():
    """Verify canonical rows and the bootstrap audit record without mutation."""
    errors = []
    accounts_by_code = {a.code: a for a in Account.objects.select_related("parent").all()}
    for code, name, name_fa, account_type, parent_code, is_posting, is_active in CANONICAL_COA:
        account = accounts_by_code.get(code)
        if account is None:
            errors.append(f"missing canonical account {code}")
            continue
        actual = (
            account.name,
            account.name_fa,
            str(account.account_type),
            account.parent.code if account.parent_id else None,
            account.is_posting,
            account.is_active,
        )
        expected = (name, name_fa, str(account_type), parent_code, is_posting, is_active)
        if actual != expected:
            errors.append(f"canonical account {code} differs from its approved definition")

    currencies_by_code = {c.code: c for c in Currency.objects.all()}
    for code, name, symbol, decimal_places, is_base, is_active in CURRENCY_DEFINITIONS:
        currency = currencies_by_code.get(code)
        if currency is None:
            errors.append(f"missing required currency {code}")
            continue
        actual = (
            currency.name,
            currency.symbol,
            currency.decimal_places,
            currency.is_base,
            currency.is_active,
        )
        expected = (name, symbol, decimal_places, is_base, is_active)
        if actual != expected:
            errors.append(f"currency {code} differs from its approved definition")

    if Currency.objects.filter(is_base=True).exclude(code="AFN").exists():
        errors.append("a currency other than AFN is marked as base")

    audit_events = AuditEvent.objects.filter(
        entity=BOOTSTRAP_AUDIT_ENTITY,
        reference=BOOTSTRAP_AUDIT_REFERENCE,
    )
    if audit_events.count() != 1:
        errors.append(
            "expected exactly one bootstrap audit event "
            f"for {BOOTSTRAP_AUDIT_REFERENCE}; found {audit_events.count()}"
        )
    elif audit_events.get().action != AuditAction.CREATE:
        errors.append("bootstrap audit event has an unexpected action")

    return errors


class Command(BaseCommand):
    help = (
        "Initialize canonical V1 chart of accounts and AFN/USD currencies "
        "on a fresh database; refuses partial or divergent existing setup."
    )

    def handle(self, *args, **options):
        with transaction.atomic():
            has_accounts = Account.objects.exists()
            has_currencies = Currency.objects.exists()

            if has_accounts or has_currencies:
                errors = _verify_existing_configuration()
                if errors:
                    details = "; ".join(errors)
                    raise CommandError(
                        "Bootstrap refused: existing accounting master data is "
                        "partial or differs from the canonical contract. No rows "
                        f"were changed. Review manually: {details}"
                    )
                self.stdout.write(
                    self.style.SUCCESS(
                        "Bootstrap already present: canonical COA, AFN/USD, and "
                        "the single bootstrap audit event verified; no data changed."
                    )
                )
                return

            # Fresh database only. The existing seed function is called only
            # after proving both master tables are empty, so it cannot silently
            # overwrite accountant edits on an established database.
            coa_result = seed_chart_of_accounts()
            for code, name, symbol, decimal_places, is_base, is_active in CURRENCY_DEFINITIONS:
                Currency.objects.create(
                    code=code,
                    name=name,
                    symbol=symbol,
                    decimal_places=decimal_places,
                    is_base=is_base,
                    is_active=is_active,
                )

            record_audit_event(
                action=AuditAction.CREATE,
                entity=BOOTSTRAP_AUDIT_ENTITY,
                reference=BOOTSTRAP_AUDIT_REFERENCE,
                new_state={
                    "chart_of_accounts": coa_result,
                    "currencies": [definition[0] for definition in CURRENCY_DEFINITIONS],
                },
                reason="Manual fresh-database bootstrap",
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Bootstrap completed: "
                f"{coa_result['created']} accounts created, "
                f"{len(CURRENCY_DEFINITIONS)} currencies created, "
                "audit event recorded."
            )
        )
