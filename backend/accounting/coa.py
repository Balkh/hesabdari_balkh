"""Canonical V1 Chart of Accounts — the ONE authoritative COA definition (G12).

Contract: docs/phase-0/PHASE_0_CONTRACT_V2.1.md Section 1 (§1.6) and the
authoritative Phase 2 handoff §§8–14.

Stage 2.1 scope ONLY: canonical definitions + idempotent seed.
No balances, no FX logic, no workflows (Stages 2.2–2.5 and later phases).

Conventions:
- ``code`` is the stable account identity (G2). The seed looks rows up by code
  and NEVER modifies the code of an existing row.
- ``name`` is the English canonical name; ``name_fa`` is the Persian/Dari
  canonical name. The two languages are NEVER mixed in one field.
- Rows are ordered parents-first so one deterministic pass resolves parents.
"""

from django.db import transaction

from .models import Account, AccountType


class COASeedError(ValueError):
    """Raised when the canonical COA cannot be seeded deterministically."""


# (code, name_en, name_fa, account_type, parent_code, is_posting, is_active)
CANONICAL_COA = (
    # --- Assets -----------------------------------------------------------
    ("1000", "Assets", "دارایی‌ها", AccountType.ASSET, None, False, True),
    ("1100", "Cash & Bank", "نقد و بانک", AccountType.ASSET, "1000", False, True),
    ("1110", "Cash in Hand", "نقد در صندوق", AccountType.ASSET, "1100", True, True),
    ("1120", "Bank Accounts", "حسابات بانکی", AccountType.ASSET, "1100", True, True),
    ("1200", "Exchange House Accounts", "حسابات صرافی", AccountType.ASSET, "1000", False, True),
    ("1210", "Exchange House A", "صرافی الف", AccountType.ASSET, "1200", True, True),
    ("1220", "Exchange House B", "صرافی ب", AccountType.ASSET, "1200", True, True),
    ("1300", "Accounts Receivable", "حسابات دریافتنی", AccountType.ASSET, "1000", False, True),
    ("1310", "Trade Receivables", "دریافتنی‌های تجاری", AccountType.ASSET, "1300", True, True),
    ("1400", "Inventory", "موجودی کالا", AccountType.ASSET, "1000", False, True),
    ("1410", "Main Warehouse", "گدام اصلی", AccountType.ASSET, "1400", True, True),
    ("1420", "Secondary Warehouse", "گدام فرعی", AccountType.ASSET, "1400", True, True),
    ("1500", "Supplier Advances", "پیش‌پرداخت به تأمین‌کنندگان", AccountType.ASSET, "1000", True, True),
    ("1900", "Other Assets", "سایر دارایی‌ها", AccountType.ASSET, "1000", True, True),
    # --- Liabilities ------------------------------------------------------
    ("2000", "Liabilities", "بدهی‌ها", AccountType.LIABILITY, None, False, True),
    ("2100", "Accounts Payable", "حسابات پرداختنی", AccountType.LIABILITY, "2000", False, True),
    ("2110", "Trade Payables", "پرداختنی‌های تجاری", AccountType.LIABILITY, "2100", True, True),
    ("2200", "Customer Advances / Credits", "پیش‌پرداخت و اعتبار مشتریان", AccountType.LIABILITY, "2000", True, True),
    ("2400", "Tax Payable", "مالیات پرداختنی", AccountType.LIABILITY, "2000", False, False),
    ("2900", "Other Liabilities", "سایر بدهی‌ها", AccountType.LIABILITY, "2000", True, True),
    # --- Equity -----------------------------------------------------------
    ("3000", "Equity", "حقوق مالک", AccountType.EQUITY, None, False, True),
    ("3100", "Owner Capital", "سرمایه مالک", AccountType.EQUITY, "3000", True, True),
    ("3900", "Opening Balance Equity", "حساب توازن افتتاحیه", AccountType.EQUITY, "3000", True, True),
    ("3950", "Retained Earnings", "سود انباشته", AccountType.EQUITY, "3000", True, True),
    # --- Revenue ----------------------------------------------------------
    ("4000", "Revenue", "عواید", AccountType.REVENUE, None, False, True),
    ("4100", "Sales Revenue", "عواید فروش", AccountType.REVENUE, "4000", False, True),
    ("4110", "Wholesale Sales", "فروش عمده", AccountType.REVENUE, "4100", True, True),
    ("4120", "Retail Sales", "فروش پرچون", AccountType.REVENUE, "4100", True, True),
    ("4200", "Sales Returns", "برگشتی فروش", AccountType.REVENUE, "4000", True, True),
    # --- Cost of Goods Sold -----------------------------------------------
    ("5000", "Cost of Goods Sold", "بهای تمام‌شده فروش", AccountType.EXPENSE, None, False, True),
    ("5100", "COGS", "بهای تمام‌شده کالای فروش‌رفته", AccountType.EXPENSE, "5000", True, True),
    ("5200", "Purchase Returns", "برگشتی خرید", AccountType.EXPENSE, "5000", True, True),
    # --- Operating Expenses -----------------------------------------------
    ("6000", "Expenses", "مصارف", AccountType.EXPENSE, None, False, True),
    ("6100", "Operating Expenses", "مصارف عملیاتی", AccountType.EXPENSE, "6000", True, True),
    ("6200", "Freight & Transport", "کرایه و حمل‌ونقل", AccountType.EXPENSE, "6000", True, True),
    ("6300", "Salaries", "معاشات", AccountType.EXPENSE, "6000", True, True),
    # --- Foreign Exchange (top-level, no 8000 group) -----------------------
    ("8100", "Foreign Exchange Gain", "عاید تبادله ارز", AccountType.REVENUE, None, True, True),
    ("8200", "Foreign Exchange Loss", "ضرر تبادله ارز", AccountType.EXPENSE, None, True, True),
)

# Test-only counter-account for the posting-acceptance matrix (handoff §19).
# This constant names an account; it implements NO workflow.
TEST_COUNTER_ACCOUNT_CODE = "3900"


def seed_chart_of_accounts():
    """Converge the database to the canonical V1 COA, idempotently.

    - Deterministic: fixed row order, parents before children.
    - Idempotent: re-running changes nothing (returns created=0, updated=0).
    - Transactional: any failure rolls back the whole seed.
    - Non-destructive: never deletes rows; never touches non-canonical codes;
      never modifies the ``code`` of an existing row; never touches journals.

    Returns {"created": int, "updated": int, "total_canonical": int} where
    ``updated`` counts rows whose canonical attributes actually changed.
    """
    created = 0
    updated = 0
    with transaction.atomic():
        for code, name_en, name_fa, account_type, parent_code, is_posting, is_active in CANONICAL_COA:
            if parent_code is None:
                parent = None
            else:
                try:
                    parent = Account.objects.get(code=parent_code)
                except Account.DoesNotExist as exc:
                    raise COASeedError(
                        f"Canonical parent {parent_code} is missing for account {code}"
                    ) from exc
            wanted = {
                "name": name_en,
                "name_fa": name_fa,
                "account_type": str(account_type),
                "parent": parent,
                "is_posting": is_posting,
                "is_active": is_active,
            }
            try:
                account = Account.objects.get(code=code)
            except Account.DoesNotExist:
                Account.objects.create(code=code, **wanted)
                created += 1
                continue
            dirty = []
            for field, want in wanted.items():
                got = getattr(account, field)
                if field == "parent":
                    got = got.pk if got is not None else None
                    want = want.pk if want is not None else None
                elif field == "account_type":
                    got, want = str(got), str(want)
                if got != want:
                    dirty.append(field)
                    setattr(account, field, wanted[field])
            if dirty:
                account.save(update_fields=dirty)
                updated += 1
    return {"created": created, "updated": updated, "total_canonical": len(CANONICAL_COA)}
