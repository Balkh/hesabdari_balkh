# PHASE 2 — STAGE 2.4 EVIDENCE REPORT: Balances, Trial Balance & Source Traceability

**Branch:** `phase/2`
**Baseline commit:** `720ac03` (Stage 2.3; `main` untouched at `846a777`)
**Final commit:** single Stage 2.4 commit on `phase/2` (exact hash in review response + `git log`)
**Date:** 2026-09-09 — Status: IMPLEMENTED · TESTED · EXECUTED · EVIDENCE READY · **AWAITING USER REVIEW**

States used: PASS (executed) / FAIL / NOT EXECUTED / NOT APPLICABLE.
Claim classes: `EXECUTED` / `OBSERVED` / `VERIFIED` / `INFERRED` / `NOT VERIFIED` / `DEFERRED`.

## 1. Scope

Read-only accounting layer: `account_balance()`, `trial_balance()`,
`journals_by_source()`, `trace_source()` + source index. No workflows, no
periods, no ledgers, no UI. PASS `EXECUTED`

## 2. Baseline commit

`phase/2 @ 720ac03`, tree clean except pre-existing untracked `docs/phase-0/`
(left untouched, uncommitted). PASS `VERIFIED`

## 3. Files changed

- `M backend/accounting/models.py` (+3: `Meta.indexes` composite source index)
- `?? backend/accounting/balances.py` (NEW read layer, ~200 lines)
- `?? backend/accounting/balance_tests.py` (NEW 32 golden/failure tests)
- `?? backend/accounting/migrations/0006_source_trace_index.py` (NEW AddIndex)
- `?? this report` (NEW)
- Removed lines across the diff: **zero**. PASS `VERIFIED`

## 4. Implementation summary

`balances.py`: DB-aggregated posted-only sums; normal-balance signs with
4200/5200 contra overrides (COA types untouched); inclusive posting-date
ranges; mixed-currency refusal guard (§16.6-5); TB with loud imbalance failure
(`TrialBalanceError` carries `.result`); chronology-ordered source queries;
unresolved-safe trace shape for future resolvers. Single grouped query for TB
(no N+1). PASS `EXECUTED`

## 5. Account balance contract

`account_balance(account, date_from=None, date_to=None)` → dict with
code/name/type, `normal_balance`, `is_contra`, Decimal `total_debit`/
`total_credit`/`balance` (signed), `lines_count`, effective range. PASS `EXECUTED`

## 6. Trial balance contract

`trial_balance(date_to=None)` → rows (code-ordered, activity-only incl.
zero-net), totals, `difference`, `balanced`; raises `TrialBalanceError` on
difference != 0 with totals + rows attached. PASS `EXECUTED`

## 7. Normal-balance handling

ASSET/EXPENSE debit-normal; LIABILITY/EQUITY/REVENUE credit-normal; signed =
with-side minus against-side. Proven per type (G2/G4–G8 + equity). PASS `EXECUTED`

## 8. 4200 handling

Type stays REVENUE (asserted); effective normal DEBIT via explicit override;
Dr 100 → +100. PASS `EXECUTED`

## 9. 5200 handling

Type stays EXPENSE (asserted); effective normal CREDIT via explicit override;
Cr 100 → +100. PASS `EXECUTED`

## 10. Reversal handling

Originals (REVERSED) remain included; POSTED reversals offset; pair nets to
zero; both rows stay queryable; TB stays balanced with activity rows kept.
PASS `EXECUTED`

## 11. Draft exclusion

DRAFT lines excluded from balances + TB; after posting (status flip) included.
CANCELLED-shaped rows excluded via positive {POSTED, REVERSED} inclusion
(no CANCELLED status exists in the frozen model). PASS `EXECUTED`

## 12. Date filtering

Posting-date ranges, inclusive bounds, from-only/to-only/both; backdated posts
follow posting date, not creation order. PASS `EXECUTED`

## 13. Chronological ordering

Canonical order (posting_date, number, id) — "document sequence" interpreted
as the unique journal number (`INFERRED`, flagged). Proven: later-created
earlier-dated entry sorts first; same-date tie broken by number; source
queries use it. No ledger-listing API added (reporting territory). PASS `EXECUTED`

## 14. Source traceability

`journals_by_source(type, id)` → chronology-ordered list (empty, never error);
`trace_source(entry)` → stable dict, `resolved: False` for all types in 2.4
(no modules exist — nothing to resolve, nothing fabricated). Round trip,
multi-journal, missing/empty sources proven. PASS `EXECUTED`

## 15. Indexes

Exactly one: composite `(source_type, source_id)` (`je_src_type_id_idx`),
migration 0006. Single-column variants deliberately NOT added (redundant).
Status/date indexes deferred — no measured problem at this scale; FK/PK
indexes suffice. PASS `EXECUTED`

## 16. Golden test results

`accounting/balance_tests.py`: **32 passed, 0 failed** — G1–G22 + equity +
CANCELLED + mixed-currency refusal + imbalance diagnosis + reconciliation.
PASS `EXECUTED`

## 17. Failure/rollback results

Nonexistent account / bad date / from>to / corrupt line / unresolvable source /
no activity / draft-only / reversed history — all fail safely with domain
errors; TB imbalance raises with diagnostic payload; no silent zeros, no
repair. (Read layer performs no writes, so no rollback paths exist by
construction.) PASS `EXECUTED`

## 18. Reconciliation proof

Fixture (3 posts + reversal + draft + backdated): Σ account debits/credits ==
Σ posted-line debits/credits == TB totals; TB debit == credit; source-linked
data == direct fetch. Live demo: `TOTAL DEBIT=2000 TOTAL CREDIT=2000
DIFFERENCE=0`, pair `net=0`. PASS `EXECUTED`

## 19. Historical integrity proof

G21 full-table snapshot identical before/after all read calls; audit count
unchanged; legacy/REVERSED rows readable; migration 0006 forward/reverse/
re-apply verified; graph 0001→0006 applied. PASS `EXECUTED`

## 20. Full regression results

```text
manage.py check                  → 0 issues
pytest full                      → 127 passed (95 frozen + 32 new), 0 failed
pytest balance_tests             → 32 passed
manage.py test                   → Ran 17 — OK
makemigrations --check --dry-run → No changes detected
npm run build / npm test         → ✓ built; 4/4 pass
```

PASS `EXECUTED`

## 21. PostgreSQL status

NOT EXECUTED (no server/binary in sandbox). NOT EXECUTED

## 22. Tauri status

NOT EXECUTED (backend-only change; not applicable beyond frontend build/tests).
NOT EXECUTED / NOT APPLICABLE

## 23. Known limitations

1. Mixed-currency activity raises (by design, §16.6-5); currency-parameterized
   balances arrive with later ledger phases — designed extension point.
2. `trace_source().resolved` is always False until business modules exist.
3. "Document sequence" = journal number (interpretation, needs acknowledgement).
4. Test-artifact fix: imbalance message asserts numeric payload, not `"101.00"`
   string (SQLite drops NUMERIC scale; values are numerically exact).
5. `_as_date` imported from frozen `services.py` (shared coercion, no fork).

## 24. Exact commit hash

Single commit `feat(accounting): implement balances trial balance and source
traceability` on `phase/2` — exact hash in the review response and `git log`.
