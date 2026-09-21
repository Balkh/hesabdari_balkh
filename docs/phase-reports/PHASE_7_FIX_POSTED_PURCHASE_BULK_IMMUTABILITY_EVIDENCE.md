# Phase 7 Fix Mode Evidence
## Posted Purchase / PurchaseLine Bulk ORM Immutability

**Date:** 2026-09-19  
**Branch:** `phase/4`  
**Starting HEAD:** `c521fb4b6194330142c77bcefd9e9d9795f601d9`  
**Ending HEAD:** `c521fb4b6194330142c77bcefd9e9d9795f601d9`  
**Scope:** Narrow Fix Mode correction for posted Purchase and PurchaseLine bulk ORM mutation/deletion

## Fix status

Implemented and tested on SQLite. PostgreSQL verification remains blocked. Phase 7 was not frozen and Phase 8 was not started.

## Finding and root cause

The Comprehensive Phase 7 Review identified that `Purchase.save()`, `Purchase.delete()`, `PurchaseLine.save()`, and `PurchaseLine.delete()` protected instance operations but did not intercept Django QuerySet bulk operations.

Django QuerySet methods execute SQL directly and do not call each affected model instance's custom `save()` or `delete()` method:

```python
Purchase.objects.filter(...).update(...)
Purchase.objects.filter(...).delete()
PurchaseLine.objects.filter(...).update(...)
PurchaseLine.objects.filter(...).delete()
```

Therefore, posted Purchase history could previously be changed or deleted through bulk ORM paths.

## Production fix

Changed only:

```text
backend/purchases/models.py
```

Added narrow custom QuerySet classes:

- `PurchaseQuerySet`
- `PurchaseLineQuerySet`

The Purchase QuerySet now:

- rejects bulk updates when the selected queryset contains a POSTED Purchase;
- rejects all bulk status updates, preventing direct ORM lifecycle transitions;
- rejects bulk deletion when the selected queryset contains a POSTED Purchase.

The PurchaseLine QuerySet now:

- rejects bulk updates when selected lines belong to a POSTED Purchase;
- rejects bulk updates that would move lines onto a POSTED Purchase;
- rejects bulk deletion when selected lines belong to a POSTED Purchase.

The existing model-level instance guards remain in place. Draft queryset deletion remains usable by the existing draft update service, and validated draft edits continue to use `update_purchase()` and `update_purchase_line()`.

No accounting, inventory, fiscal, currency, PartyLedgerAttribution, audit, or idempotency implementation was changed.

## Regression tests added

Added to `backend/purchases/purchase_tests.py`:

- `test_stage77_posted_purchase_bulk_update_is_rejected`
- `test_stage77_posted_purchase_bulk_delete_is_rejected`
- `test_stage77_posted_purchase_line_bulk_update_is_rejected`
- `test_stage77_posted_purchase_line_bulk_delete_is_rejected`

These tests verify that:

- the forbidden operation raises `PostedImmutabilityError`;
- the Purchase remains POSTED;
- original Purchase fields remain unchanged;
- the Purchase remains present after bulk delete rejection;
- PurchaseLine records remain present after bulk delete rejection;
- original line values remain unchanged;
- no partial deletion occurs.

Existing draft and lifecycle tests remain unchanged and continue to cover:

- `update_purchase()` draft edits;
- `update_purchase_line()` draft edits;
- total and discount recalculation;
- final validation;
- posting;
- accounting;
- inventory;
- supplier attribution;
- idempotency;
- fiscal gating;
- posted instance immutability.

## Lifecycle preservation

The lifecycle remains:

```text
DRAFT
  → validated draft editing
  → final validation
  → fiscal gate
  → atomic posting
  → POSTED
  → immutable
```

The full focused Purchase suite continues to pass after the QuerySet protection was added. Existing draft editing tests continue to pass, including supplier, warehouse, currency/rate, line replacement, discount, freight, subtotal, and total behavior.

## Financial integrity protection

The fix does not change:

- `post_journal()`;
- `receive_stock()`;
- `attribute_journal_line()`;
- account `2110` payable behavior;
- account `6200` freight behavior;
- AFN or foreign-currency behavior;
- fiscal-period enforcement;
- Purchase posting atomicity;
- Purchase idempotency;
- PartyLedgerAttribution;
- StockMovement or AVCO.

No new accounting entries, inventory movements, supplier attribution, audit events, or financial idempotency records are created by the immutability fix.

## Test commands and results

### Focused Purchase suite

```text
$ cd backend && .venv/bin/pytest -q purchases/purchase_tests.py
..........................                                               [100%]
26 passed in 1.74s
```

### Full backend suite

```text
$ cd backend && .venv/bin/pytest -q
723 passed, 2 skipped in 84.73s (0:01:24)
```

### Django check

```text
$ cd backend && .venv/bin/python manage.py check
System check identified no issues (0 silenced).
```

### Migration check

```text
$ cd backend && .venv/bin/python manage.py makemigrations --check --dry-run
No changes detected
```

### Diff check

```text
$ git diff --check
# clean; no output
```

## Phase 6 concurrency command

Executed:

```text
$ cd backend && .venv/bin/python manage.py test \
    inventory.inventory_tests.Stage6ConcurrencyTests --verbosity 2

Ran 2 tests in 0.584s

OK (skipped=2)
```

Both tests were skipped because they require PostgreSQL row-level locking semantics. The Phase 6 PostgreSQL concurrency debt remains open.

## PostgreSQL status

```text
PostgreSQL verification: BLOCKED / NOT EXECUTED
Reason: PostgreSQL was unavailable at 127.0.0.1:5432.
```

SQLite results are not presented as PostgreSQL evidence.

## Migrations

No migration was required. The fix changes QuerySet/model Python behavior only.

```text
No changes detected
```

## Working tree and changed files

Final working-tree status:

```text
 M backend/config/settings/base.py
 M docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
?? backend/purchases/
?? docs/phase-reports/PHASE_7_STAGE_7.1_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.2_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.3_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.4_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.5_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.6_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.7_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_FIX_POSTED_PURCHASE_BULK_IMMUTABILITY_EVIDENCE.md
```

Because `backend/purchases/` is untracked working-tree work, the tracked-only `git diff --stat` does not list the new Python changes. The Fix Mode production/test changes are:

- `backend/purchases/models.py` — custom QuerySet protections;
- `backend/purchases/purchase_tests.py` — four bulk ORM regression tests;
- `docs/phase-reports/PHASE_7_FIX_POSTED_PURCHASE_BULK_IMMUTABILITY_EVIDENCE.md` — this report.

No unrelated files were changed by Fix Mode. The pre-existing settings and Phase 6 evidence changes were preserved.

No commit, merge, rebase, amend, reset, clean, stash, freeze, tag, or history rewrite was performed.

## Remaining debt

- PostgreSQL Purchase verification remains blocked.
- Phase 6 PostgreSQL concurrency verification remains pending.
- Phase 7 remains unfrozen and requires user review.

## Stop point

The targeted posted Purchase/PurchaseLine bulk ORM immutability fix and regression evidence are complete for this Fix Mode increment. No second comprehensive review was performed automatically. User review is required.
