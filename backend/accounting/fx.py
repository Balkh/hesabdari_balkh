"""Realized foreign-exchange settlement pattern (Stage 2.5 — §1.10, §1.11, §1.12).

REALIZED FX ONLY. Deliberately NOT implemented here (V2 / later phases, §1.10):

* period-end unrealized revaluation of open receivables/payables,
* automatic FX restatement / rewriting of historical rows,
* unrealized gain or loss of any kind,
* cross-currency settlement (rejected below, §5),
* party subledgers, allocation machinery, advances (Phase 5).

--------------------------------------------------------------------------
The accounting rule (§6)
--------------------------------------------------------------------------
An obligation denominated in a foreign currency is carried in the books at the
AFN value of its HISTORICAL rate snapshot. At settlement the settlement asset
moves at the AFN value of the SETTLEMENT rate snapshot. The gap between those
two AFN values is the realized result::

    carrying_value   = Round(settled_amount x historical_rate, 2)
    settlement_value = Round(settled_amount x settlement_rate, 2)
    difference       = |settlement_value - carrying_value|

Only the SETTLED portion is revalued (§7): the unsettled remainder keeps its
own historical carrying value and books nothing.

Direction (§6.1 / §6.2)::

    receivable: settlement > carrying -> GAIN (Cr 8100)
                settlement < carrying -> LOSS (Dr 8200)
    payable:    settlement > carrying -> LOSS (Dr 8200)
                settlement < carrying -> GAIN (Cr 8100)
    equal:      NO FX line at all (§13)

--------------------------------------------------------------------------
Currency representation — why the settlement journal is in the BASE currency
--------------------------------------------------------------------------
The frozen journal carries exactly ONE transaction currency (§1.8 / Stage 2.2)
and derives ``afn_total`` as ``Round(total x rate, 2)``. The lines demanded by
§6.1/§6.2/§28 are AFN book values (Dr settlement 7200 / Cr receivable 7000 /
Cr 8100 200). Posting those amounts under a USD journal would multiply them by
the rate a second time and corrupt the AFN equivalent, so the settlement
journal is denominated in the base currency (AFN): rate snapshot ``1.0000``,
direction ``AFN->AFN``, ``afn_total`` equal to its total.

Rate snapshots are preserved as follows (§1.12, §10):

* the HISTORICAL rate stays on the obligation journal — frozen and immutable;
* the SETTLEMENT rate is a **manual transaction-time rate** (user ruling L1). It
  is persisted as STRUCTURED data on :class:`~accounting.models.FXSettlement`
  (``settlement_rate``, 4dp) together with the source/target currencies and
  amounts, the rate direction, the transaction date and both accounts. It is
  never read from — and never updated by — the ``ExchangeRate`` table. The
  journal's ``description`` and the lines' ``reference`` fields repeat it for
  human readability, but they are never its only home;
* neither rate is ever recomputed from later rate data, and nothing here
  rewrites history.

Revenue is posted to **4110** (user ruling L2): 4100 is a non-posting group
account in the frozen canonical COA and stays that way.

Cross-currency settlement (obligation currency != settlement currency) is
REJECTED with a domain error: the frozen single-currency journal cannot
represent it, and faking it (silent conversion, hidden bridge journals, a new
multi-currency model) is forbidden by §5.

--------------------------------------------------------------------------
Reuse
--------------------------------------------------------------------------
Every amount is Decimal through ``core.money`` (Half-Up, 2dp money / 4dp
rates). Every journal goes through the canonical ``post_journal`` (Stage 2.2 +
2.3): balanced, currency-checked, AFN-equivalent computed, audited, atomic,
idempotent, immutable. There is no second posting engine, no second rounding
rule and no new schema here.
"""

from decimal import Decimal

from django.db import transaction as db_transaction

from core.money import fx_equivalent, format_rate, normalize_rate, quantize_half_up, to_decimal
from currencies.models import Currency

from .models import Account, AccountType, FXSettlement
from .services import JournalValidationError, _as_date, post_journal

__all__ = [
    "OBLIGATION_RECEIVABLE",
    "OBLIGATION_PAYABLE",
    "OBLIGATION_KINDS",
    "FX_GAIN_ACCOUNT_CODE",
    "FX_LOSS_ACCOUNT_CODE",
    "FX_GAIN",
    "FX_LOSS",
    "FX_NONE",
    "FX_CONVERSION",
    "compute_realized_fx",
    "post_realized_fx_settlement",
    "post_fx_conversion",
]


OBLIGATION_RECEIVABLE = "RECEIVABLE"
OBLIGATION_PAYABLE = "PAYABLE"
OBLIGATION_KINDS = (OBLIGATION_RECEIVABLE, OBLIGATION_PAYABLE)

# A manual-rate conversion with no obligation being released (e.g. AFN -> USD).
FX_CONVERSION = "CONVERSION"

FX_GAIN_ACCOUNT_CODE = "8100"
FX_LOSS_ACCOUNT_CODE = "8200"

FX_GAIN = "GAIN"
FX_LOSS = "LOSS"
FX_NONE = "NONE"

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Validation helpers (thin, no duplicated money logic)
# ---------------------------------------------------------------------------

def _require_account(value, label, *, expected_type=None, expected_code=None):
    if not isinstance(value, Account) or value.pk is None:
        raise JournalValidationError(f"A persisted Account is required for {label}")
    if not value.is_active:
        raise JournalValidationError(f"Account {value.code} is inactive and cannot receive postings")
    if not value.is_posting:
        raise JournalValidationError(f"Account {value.code} is not a posting account")
    if expected_code is not None and value.code != expected_code:
        raise JournalValidationError(
            f"Invalid {label}: account {value.code} is not the canonical {expected_code}"
        )
    if expected_type is not None and str(value.account_type) != str(expected_type):
        raise JournalValidationError(
            f"Invalid {label}: account {value.code} is {value.account_type}, expected {expected_type}"
        )
    return value


def _require_currency(value, label):
    if not isinstance(value, Currency) or value.pk is None:
        raise JournalValidationError(f"A persisted Currency is required for {label}")
    if not value.is_active:
        raise JournalValidationError(f"Currency {value.code} is not active")
    return value


def _require_amount(value, label):
    amount = quantize_half_up(to_decimal(value), 2)
    if amount <= 0:
        raise JournalValidationError(f"{label} must be greater than zero")
    return amount


def _require_rate(value, currency, label):
    """Positive 4dp rate; a base-currency rate must be exactly 1 (§1.11)."""
    if value is None:
        raise JournalValidationError(f"{label} is required for {currency.code} obligations")
    try:
        rate = normalize_rate(value)
    except TypeError:
        raise
    if rate <= 0:
        raise JournalValidationError(f"{label} must be greater than zero")
    if currency.is_base and rate != Decimal("1.0000"):
        raise JournalValidationError(
            f"A {currency.code} (base currency) {label} must be 1.0000"
        )
    return rate


def _resolve_fx_account(provided, canonical_code, expected_type, label):
    """Resolve/validate the gain or loss account (§3.5: 8100 gain, 8200 loss)."""
    if provided is None:
        account = Account.objects.filter(code=canonical_code).first()
        if account is None:
            raise JournalValidationError(
                f"Canonical {label} account {canonical_code} is missing from the chart of accounts"
            )
        return _require_account(account, label, expected_type=expected_type, expected_code=canonical_code)
    return _require_account(provided, label, expected_type=expected_type, expected_code=canonical_code)


# ---------------------------------------------------------------------------
# Pure calculation — no database writes, safe to call for reporting
# ---------------------------------------------------------------------------

def compute_realized_fx(*, obligation_kind, obligation_account, obligation_amount,
                        obligation_currency, historical_rate, settlement_account,
                        settlement_amount, settlement_currency, settlement_rate,
                        gain_account=None, loss_account=None):
    """Compute the realized FX result and the exact journal lines to post.

    Returns a dict with the inputs echoed (normalized), the AFN carrying and
    settlement values, the difference, the direction, the resolved FX account
    and the fully-formed ``lines`` for :func:`post_realized_fx_settlement`.
    Pure: reads only the canonical FX accounts, writes nothing.
    """
    if obligation_kind not in OBLIGATION_KINDS:
        raise JournalValidationError("obligation_kind must be RECEIVABLE or PAYABLE")

    obligation = _require_account(obligation_account, "obligation account")
    settlement = _require_account(settlement_account, "settlement account")
    if obligation.pk == settlement.pk:
        raise JournalValidationError("obligation account and settlement account must differ")

    obligation_currency = _require_currency(obligation_currency, "obligation currency")
    settlement_currency = _require_currency(settlement_currency, "settlement currency")
    if obligation_currency.pk != settlement_currency.pk:
        raise JournalValidationError(
            "Cross-currency settlement is not supported by the frozen "
            f"single-currency journal contract: obligation {obligation_currency.code} "
            f"vs settlement {settlement_currency.code}"
        )

    total_amount = _require_amount(obligation_amount, "obligation amount")
    settled_amount = _require_amount(settlement_amount, "settlement amount")
    if settled_amount > total_amount:
        raise JournalValidationError(
            "settlement amount cannot exceed the obligation amount"
        )

    historical = _require_rate(historical_rate, obligation_currency, "historical rate")
    settlement_rate_value = _require_rate(settlement_rate, settlement_currency, "settlement rate")

    carrying_value = fx_equivalent(settled_amount, historical)
    settlement_value = fx_equivalent(settled_amount, settlement_rate_value)
    difference = (settlement_value - carrying_value).copy_abs()

    if difference == 0:
        direction = FX_NONE
    elif obligation_kind == OBLIGATION_RECEIVABLE:
        direction = FX_GAIN if settlement_value > carrying_value else FX_LOSS
    else:
        direction = FX_LOSS if settlement_value > carrying_value else FX_GAIN

    # Validate BOTH supplied FX accounts, whichever direction applies, so an
    # invalid account is always rejected rather than silently ignored (§14).
    gain = (_resolve_fx_account(gain_account, FX_GAIN_ACCOUNT_CODE, AccountType.REVENUE, "FX gain account")
            if gain_account is not None else None)
    loss = (_resolve_fx_account(loss_account, FX_LOSS_ACCOUNT_CODE, AccountType.EXPENSE, "FX loss account")
            if loss_account is not None else None)
    if direction == FX_GAIN and gain is None:
        gain = _resolve_fx_account(None, FX_GAIN_ACCOUNT_CODE, AccountType.REVENUE, "FX gain account")
    if direction == FX_LOSS and loss is None:
        loss = _resolve_fx_account(None, FX_LOSS_ACCOUNT_CODE, AccountType.EXPENSE, "FX loss account")

    settle_ref = f"{settlement_currency.code}@{format_rate(settlement_rate_value)}"
    carry_ref = f"{obligation_currency.code}@{format_rate(historical)}"

    lines = []
    if obligation_kind == OBLIGATION_RECEIVABLE:
        lines.append({
            "account": settlement, "debit": settlement_value, "credit": ZERO,
            "description": "Settlement value received",
            "reference": f"SETTLE {settle_ref}",
        })
        lines.append({
            "account": obligation, "debit": ZERO, "credit": carrying_value,
            "description": "Release historical carrying value",
            "reference": f"CARRY {carry_ref}",
        })
    else:
        lines.append({
            "account": obligation, "debit": carrying_value, "credit": ZERO,
            "description": "Release historical carrying value",
            "reference": f"CARRY {carry_ref}",
        })
        lines.append({
            "account": settlement, "debit": ZERO, "credit": settlement_value,
            "description": "Settlement value paid",
            "reference": f"SETTLE {settle_ref}",
        })

    if direction == FX_GAIN:
        lines.append({
            "account": gain, "debit": ZERO, "credit": difference,
            "description": "Realized foreign exchange gain",
            "reference": f"FX GAIN {carry_ref}->{settle_ref}",
        })
    elif direction == FX_LOSS:
        lines.append({
            "account": loss, "debit": difference, "credit": ZERO,
            "description": "Realized foreign exchange loss",
            "reference": f"FX LOSS {carry_ref}->{settle_ref}",
        })

    total_debit = sum((line["debit"] for line in lines), ZERO)
    total_credit = sum((line["credit"] for line in lines), ZERO)

    base_currency = Currency.objects.filter(is_base=True).first()
    if base_currency is None:
        raise JournalValidationError("No base currency is configured")

    return {
        "obligation_kind": obligation_kind,
        "currency_code": obligation_currency.code,
        "obligation_amount": total_amount,
        "settlement_amount": settled_amount,
        "unsettled_amount": quantize_half_up(total_amount - settled_amount, 2),
        # Structured settlement data (user ruling L1) — the settlement rate plus
        # the source/target legs it produced.
        "source_currency": obligation_currency,
        "source_amount": settled_amount,
        "target_currency": base_currency,
        "target_amount": settlement_value,
        "rate_direction": f"{obligation_currency.code}->{base_currency.code}",
        "obligation_account": obligation,
        "settlement_account": settlement,
        "historical_rate": historical,
        "settlement_rate": settlement_rate_value,
        "carrying_value": carrying_value,
        "settlement_value": settlement_value,
        "difference": difference,
        "direction": direction,
        "gain_account": gain,
        "loss_account": loss,
        "lines": lines,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "balanced": total_debit == total_credit,
    }


# ---------------------------------------------------------------------------
# Posting — one atomic, audited, idempotent journal through the frozen engine
# ---------------------------------------------------------------------------

def _settlement_defaults(*, plan, transaction_date, kind, obligation_account, settlement_account,
                         description="", reference=""):
    """Structured field values for one :class:`FXSettlement` row (user ruling L1)."""
    fx_account = plan["gain_account"] if plan["direction"] == FX_GAIN else (
        plan["loss_account"] if plan["direction"] == FX_LOSS else None)
    return dict(
        transaction_date=transaction_date,
        kind=kind,
        source_currency=plan["source_currency"],
        source_amount=plan["source_amount"],
        target_currency=plan["target_currency"],
        target_amount=plan["target_amount"],
        settlement_rate=plan["settlement_rate"],
        rate_direction=plan["rate_direction"],
        historical_rate=plan["historical_rate"],
        obligation_account=obligation_account,
        settlement_account=settlement_account,
        fx_account=fx_account,
        carrying_value=plan["carrying_value"],
        settlement_value=plan["settlement_value"],
        difference=plan["difference"],
        direction=plan["direction"],
        description=description,
        reference=reference,
    )


def post_realized_fx_settlement(*, number, posting_date, description="", source_type="",
                                source_id="", reference="", created_by=None,
                                idempotency_key=None, **compute_kwargs):
    """Post one realized-FX settlement journal through ``post_journal``.

    The journal is denominated in the BASE currency (see module docstring): its
    lines are AFN book values, so its ``rate`` snapshot stays ``1.0000`` /
    ``AFN->AFN``. The manually entered settlement rate is persisted
    structurally on :class:`FXSettlement` in the SAME transaction — it is
    transaction data, never derived from the ``ExchangeRate`` table and never
    updated afterwards (user ruling L1).

    ``number`` is required (as in ``post_journal``) so that an idempotent retry
    reproduces the identical request fingerprint (§14). An exact retry returns
    the original entry and leaves its settlement record untouched.
    """
    plan = compute_realized_fx(**compute_kwargs)

    base = Currency.objects.filter(is_base=True).first()
    if base is None:
        raise JournalValidationError("No base currency is configured")

    day = _as_date(posting_date, "posting_date")
    context = (
        f"Realized FX {plan['direction']}: {plan['settlement_amount']} {plan['currency_code']} "
        f"settled at {format_rate(plan['settlement_rate'])} "
        f"(historical {format_rate(plan['historical_rate'])}) "
        f"difference {plan['difference']}"
    )
    text = f"{description} | {context}" if description else context

    with db_transaction.atomic():
        entry = post_journal(
            number=number,
            posting_date=posting_date,
            description=text[:500],
            lines=plan["lines"],
            source_type=source_type,
            source_id=source_id,
            currency=base,
            rate_date=day,
            created_by=created_by,
            idempotency_key=idempotency_key,
        )
        # get_or_create: an idempotent retry returns the original entry, whose
        # immutable settlement record already exists.
        FXSettlement.objects.get_or_create(
            entry=entry,
            defaults=_settlement_defaults(
                plan=plan, transaction_date=day, kind=plan["obligation_kind"],
                obligation_account=plan["obligation_account"],
                settlement_account=plan["settlement_account"],
                description=description, reference=reference,
            ),
        )
    return entry


def post_fx_conversion(*, number, posting_date, source_account, source_amount, source_currency,
                       target_account, target_currency, settlement_rate, description="",
                       reference="", source_type="", source_id="", created_by=None,
                       idempotency_key=None):
    """Post a manual-rate currency CONVERSION (user ruling L1, Example A/C).

    ``50,000 AFN -> USD @ 70`` is the canonical case: the user enters the rate
    at conversion time, the system derives the target amount and posts an AFN
    book-value journal (Dr destination / Cr source), then snapshots the
    structured conversion data — source currency/amount, target currency/amount,
    the manually entered rate, the direction, the date and both accounts.

    Only the BASE -> FOREIGN direction is supported here: converting a foreign
    balance back into AFN releases a carrying value, which is the realized-FX
    settlement handled by :func:`post_realized_fx_settlement` (it needs the
    historical rate of that balance). Anything else is rejected, never guessed:
    no silent conversion, no hidden bridge account.
    """
    source = _require_account(source_account, "source account")
    target = _require_account(target_account, "destination account")
    if source.pk == target.pk:
        raise JournalValidationError("source account and destination account must differ")
    source_currency = _require_currency(source_currency, "source currency")
    target_currency = _require_currency(target_currency, "target currency")
    if source_currency.pk == target_currency.pk:
        raise JournalValidationError("A conversion requires two different currencies")
    if not source_currency.is_base:
        raise JournalValidationError(
            "Converting a foreign balance into the base currency releases a carrying "
            "value: use post_realized_fx_settlement with its historical rate"
        )
    if target_currency.is_base:
        raise JournalValidationError("Target currency must be the foreign currency of the conversion")

    amount = _require_amount(source_amount, "source amount")
    rate = _require_rate(settlement_rate, target_currency, "settlement rate")

    # §1.11: AFN / Rate = foreign equivalent (Half-Up, 2dp — core.money).
    target_amount = quantize_half_up(to_decimal(amount) / to_decimal(rate), 2)
    if target_amount <= 0:
        raise JournalValidationError("The conversion result must be greater than zero")

    day = _as_date(posting_date, "posting_date")
    context = (
        f"FX conversion {amount} {source_currency.code} -> {target_amount} "
        f"{target_currency.code} at {format_rate(rate)}"
    )
    text = f"{description} | {context}" if description else context

    lines = [
        {"account": target, "debit": amount, "credit": ZERO,
         "description": f"Receive {target_amount} {target_currency.code}",
         "reference": f"CONVERT IN {target_currency.code}@{format_rate(rate)}"},
        {"account": source, "debit": ZERO, "credit": amount,
         "description": f"Pay {amount} {source_currency.code}",
         "reference": f"CONVERT OUT {source_currency.code}"},
    ]

    with db_transaction.atomic():
        entry = post_journal(
            number=number,
            posting_date=posting_date,
            description=text[:500],
            lines=lines,
            source_type=source_type,
            source_id=source_id,
            currency=source_currency,  # base currency: AFN book values
            rate_date=day,
            created_by=created_by,
            idempotency_key=idempotency_key,
        )
        FXSettlement.objects.get_or_create(
            entry=entry,
            defaults=dict(
                transaction_date=day,
                kind=FX_CONVERSION,
                source_currency=source_currency,
                source_amount=amount,
                target_currency=target_currency,
                target_amount=target_amount,
                settlement_rate=rate,
                rate_direction=f"{source_currency.code}->{target_currency.code}",
                historical_rate=None,
                obligation_account=source,
                settlement_account=target,
                fx_account=None,
                carrying_value=amount,
                settlement_value=amount,
                difference=ZERO,
                direction=FX_NONE,
                description=description,
                reference=reference,
            ),
        )
    return entry
