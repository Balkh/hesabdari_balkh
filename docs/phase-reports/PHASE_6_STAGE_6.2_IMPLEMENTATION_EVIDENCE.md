# PHASE 6 — STAGE 6.2 — INVENTORY TRANSACTION FOUNDATION — EVIDENCE

## 1. Baseline HEAD

```text
Branch: phase/4 — HEAD: 2f65472 (docs: record phase 5 implementation evidence)
NOTE: the prompt-cited 6.1 commit 9ad7d90... does NOT exist in this
repository (verified: git cat-file fails). Stage 6.1 is present as
UNCOMMITTED work on 2f65472 (likely committed as 9ad7d90 on the user's
own machine). All 6.2 work builds on the inspected local tree.
Pre-6.2 tracked diff: base.py one-line INSTALLED_APPS addition (6.1)
+ .gitkeep deletion. All frozen dirs verified clean before starting.
```

## 2. Final HEAD

`2f65472` — NO new commit. Rationale (D-6.2-06): 6.2 edits files that
are themselves uncommitted (6.1); no coherent 6.2-only commit is
possible. The user commits on their own machine per standing process.

## 3. Exact Changed Files (6.2 delta only)

- `backend/inventory/models.py` — +1 field: `StockMovement.description`
  (CharField 500, blank, default "").
- `backend/inventory/services.py` — `description=""` param on
  `receive_stock`/`issue_stock` (open keeps its param, now also stored
  on the movement); `_clean_description` (text + strip + ≤500);
  fingerprint/snapshot/retry-match extended.
- `backend/inventory/migrations/0002_stockmovement_description.py` — new.
- `backend/inventory/inventory_tests.py` — +11 tests (55 → 66).
- This evidence file.

## 4. Architecture Summary

No new entities, engines, APIs, or UI. The 6.2 transaction layer IS the
6.1 primitive set (`receive_stock`/`issue_stock`/`open_stock` over the
immutable `StockMovement`), extended with the one missing §7/§11 minimum
datum: free-form `description/reason`, stored on the movement, audited,
and part of the idempotency fingerprint. Journals: none in 6.2 (6.1
opening journal unchanged); COGS/receipt journals belong to future
Sales/Purchase callers per contract §6.4/§5.2.

## 5. Business Rules Implemented

- D-6.2-01: description supported on receipt/issue/opening; blank by
  default; stripped; non-text and >500 chars rejected loudly (service
  enforces length for SQLite/PG parity); same key + different
  description = different operation → reject.
- D-6.2-02: no 6.2 journals (contract assigns COGS to Sales Accounting
  §6.4 L1339–1341 and purchase accounting to the Purchase flow §5.2).
- D-6.2-03: no secondary-UOM conversion (§6; contract requires storage
  only). D-6.2-04: no API/UI (§26; no approved requirement).

## 6. Tests Executed

- Focused: `pytest inventory/inventory_tests.py -q` (SQLite + PG).
- Full: `pytest -q` (SQLite + PG).
- Django: `manage.py test` (test + postgres settings).
- Checks: `manage.py check`, `makemigrations --check --dry-run`.
- Migrations: full fwd / inventory zero / inventory fwd (SQLite + PG).

## 7. SQLite Results

Focused **66 passed**; full **638 passed** (627 prior + 11 new);
Django runner **Ran 17 OK**; check **0 issues**; migrations-clean.

## 8. PostgreSQL Results (17.11, real server)

Focused **66 passed**; full **638 passed**; Django runner **Ran 17 OK**;
check **0 issues**; `PG-REV-OK` / `PG-FWD-OK` (0001+0002).

## 9. Django Checks

`System check identified no issues (0 silenced)` on both settings.

## 10. Migration Checks

`0002_stockmovement_description` (AddField, reversible): forward,
reverse-to-zero, forward-again all OK on SQLite and PG; `--check`
reports no missing changes.

## 11. Accounting Evidence

6.2 posts no journals (D-6.2-02). Fiscal-gate reuse proven through the
6.1 opening path: `test_open_period_posting_allowed` (OPEN → posts),
`test_closed_period_posting_rejected` (CLOSED → `PeriodValidationError`,
0 movements / 0 journals / 0 movement audits).

## 12. Idempotency Evidence

`test_retry_description_mismatch_rejected`: same key + changed
description → `InventoryValidationError`, movement count stays 1.
All 6.1 idempotency tests still pass (fingerprint extended uniformly).

## 13. Atomicity Evidence

`test_audit_failure_rolls_back_movement`: `record_audit_event` mocked
to raise → 0 new movements, 0 audits, 0 idempotency records (outer
atomic rolls back the key reservation too).

## 14. Immutability Evidence

Unchanged 6.1 behavior, all tests green: `save`/`delete` raise
`PostedImmutabilityError`; backdated test proves posted costs are never
rewritten (issue keeps post-time AVCO 10.0000 while replay yields
13.7500).

## 15. Negative-Stock Evidence

Unchanged 6.1 behavior, all tests green (allowed with ack + manual temp;
no reference-price substitution). No 6.2 change to negative logic.

## 16. AVCO Evidence

`test_backdated_receipt_replays_in_date_order`: post order
(RCV-C1, ISS-C1, RCV-C2) replays in date order (C1, C2, ISS);
stock 100; AVCO **13.7500**; historical issue cost preserved.
Zero-reset/hole-fill 6.1 tests all still green.

## 17. Frozen-Surface Diff

Tracked diff vs `2f65472`: ONLY the pre-existing 6.1 base.py one-liner
+ `.gitkeep` deletion. Zero changes (tracked or untracked) under
accounting, fiscal_periods, parties, categories, uom, products,
warehouses, cash_accounts, exchange_houses, currencies, documents,
security, core, scripts, .github. 627 pre-existing tests untouched
and passing on both engines.

## 18. Known Limitations

6.2 transactions carry no journal (by design); no Purchase/Sales docs;
primary-UOM quantities only; movement has no system number (reference
= caller identity); no API/UI.

## 19. Deferred Items

Purchase/Sales/Transfer/Adjustment/Return workflows and their journals;
shortage settlement; COGS posting on issue; secondary-UOM handling;
numbering prefixes; report suite; concurrent-duplicate stress test
(judged impractical: SQLite serializes writers; guarantee rests on the
DB UNIQUE key + reservation protocol, proven by sequential tests).

## 20. Exact Commands Used

```text
pytest inventory/inventory_tests.py -q            # SQLite: 66 passed
pytest -q                                         # SQLite: 638 passed
DJANGO_SETTINGS_MODULE=config.settings.test manage.py test        # 17 OK
DJANGO_SETTINGS_MODULE=config.settings.test manage.py check       # 0 issues
DJANGO_SETTINGS_MODULE=config.settings.test manage.py makemigrations --check --dry-run
DJANGO_SETTINGS_MODULE=config.settings.postgres pytest inventory/inventory_tests.py -q  # 66
DJANGO_SETTINGS_MODULE=config.settings.postgres pytest -q       # PG: 638 passed
DJANGO_SETTINGS_MODULE=config.settings.postgres manage.py test   # 17 OK
migrate inventory zero / migrate inventory        # SQLite + PG: REV/FWD OK
```
