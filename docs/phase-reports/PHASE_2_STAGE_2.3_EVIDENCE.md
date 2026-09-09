# PHASE 2 — STAGE 2.3 EVIDENCE REPORT: Posting Integrity

**Branch:** `phase/2`
**Starting frozen commit:** `ff03fce` (Stage 2.2; `main` untouched at `846a777`)
**Final commit:** single Stage 2.3 commit on `phase/2` (exact hash in review response + `git log`)
**Date:** 2026-09-09
**Authoritative scope:** Phase 0 §1.9 + G4; master prompt §4 (Stage 2.3 ONLY)
**Status:** IMPLEMENTED · TESTED · EXECUTED · EVIDENCE READY · **AWAITING USER REVIEW**

Classification: `EXECUTED` / `OBSERVED` / `VERIFIED` / `INFERRED` / `NOT VERIFIED` / `DEFERRED`.

---

## A. Required (§4)

Idempotent posting reusing `core/idempotency` · POSTED/REVERSED immutability at
model + service level · `reverse_journal(entry, reason, user)` with mirrored
balanced reversal + original preservation · POST/REVERSE audit reusing
`AuditEvent` · failure/rollback proofs · 27-item test matrix · evidence · commit · STOP.

## B. Implemented

1. `post_journal(..., idempotency_key=None)`: exact retry returns the original
   entry (no new rows, no new audit); key reuse for a different operation is
   rejected via request fingerprint; failed transactions release the reservation;
   genuine inner failures (e.g. duplicate number) are NOT masked as duplicates —
   the real cause is re-raised. Reuses `idempotent_operation` + `IdempotencyRecord`
   unmodified. `EXECUTED`
2. `JournalEntry.idempotency_key` (unique, nullable) + `reverses` self-FK
   (`reversals` reverse accessor; single linkage source, G12). `EXECUTED`
3. `save()`/`delete()` guards on entry + line raising `PostedImmutabilityError`.
   Sole bypass: POSTED→REVERSED status-only flip by `reverse_journal`, and line
   creation inside posting/reversal. DRAFT stays editable; DRAFT-with-lines delete
   still raises frozen `ProtectedError`. `EXECUTED`
4. `reverse_journal`: row lock + POSTED-only + no-double + no-chain + reason/user
   validation + pre-verify of original totals; reversal auto-numbered via reused
   `next_document_number("JE", jalali_year)`, inherits posting date/source/currency/
   snapshot, mirrors lines (Dr↔Cr), records user; original flips to REVERSED with
   every other field/line intact; ONE atomic txn incl. ONE REVERSE audit. `EXECUTED`
5. `security/services.record_audit_event` (thin writer; rejects unknown actions).
   Every post → POST audit (same txn); every reversal → REVERSE audit (same txn);
   retries write no audit; blocked/failed ops write no audit (contract requires
   none at this stage; §4.8 forbids partial audit state). Timestamps UTC. `EXECUTED`

## C. Files changed (D. why each)

| File | Change | Why |
|---|---|---|
| `accounting/models.py` | +2 fields, `PostedImmutabilityError`, 4 guard methods | §4.2–4.3 requirements |
| `accounting/services.py` | `_persist_entry` refactor (verbatim move), idempotency path, `reverse_journal`, audit helpers | §4.1/4.3/4.6; validation logic preserved line-for-line |
| `security/services.py` | NEW thin audit writer | §4.6 reuse of AuditEvent |
| `migrations/0005_posting_integrity_fields.py` | NEW, 2 additive AddFields | schema for §4.1/4.3 |
| `accounting/integrity_tests.py` | NEW, 34 tests | §4.7 matrix |
| `accounting/journal_tests.py` | legacy crafting via DRAFT+flip (assertions identical) | guards block direct POSTED line creation — strictly-required compat |
| this report | NEW | §4.9 |

NOT changed: `coa.py`, `coa_tests.py`, `tests.py`, `core/idempotency.py`,
`core/money.py`, `security/models.py`, old migrations, frontend, all other apps —
each verified via `git diff --quiet`. `VERIFIED`

## E–G. Tests added/executed/results

```text
pytest accounting/integrity_tests.py → 34 passed (10 idempotency, 7 immutability incl.
  limitation doc-test, 13 reversal incl. byte-integrity + atomicity + legacy, 4 audit)
pytest full                         → 95 passed (61 frozen + 34 new), 0 failed
manage.py test                      → Ran 17 — OK (assertions unchanged)
manage.py check                     → 0 issues
makemigrations --check --dry-run    → No changes detected
npm run build / npm test            → ✓ built; 4/4 pass (backend-only change, run once)
PostgreSQL / Tauri                  → NOT EXECUTED (no server; backend-only change)
```

All `EXECUTED`.

## H–I. Failure/rollback proof (all EXECUTED)

- Bad-account keyed post → error; 0 entries/records/audits; key reusable (test + counts).
- Duplicate number with fresh key → real `IntegrityError` re-raised (not masked); key reusable.
- Fingerprint mismatch (number or amount differs) → rejected; counts frozen.
- Orphaned idempotency record → `DuplicateOperationError` retry-signal, never a wrong result.
- Failed reversal (injected crash): 1 entry (still POSTED), 1 audit (original POST only),
  0 `NumberSequence` rows — full rollback incl. numbering.
- Corrupt original (totals tampered) → reversal refused; status stays POSTED.
- Every blocked op (7 mutation/deletion paths, double/chain/draft/blank-reason
  reversals, failed posts) → DB counts AND audit count provably unchanged.

## J. Historical integrity proof (EXECUTED)

- Pre/post field-by-field + line-by-line snapshot: original differs ONLY in
  `status` (POSTED→REVERSED). Test `test_original_intact_except_status`.
- Legacy NULL-currency entry reverses cleanly; reversal mirrors NULLs (nothing fabricated).
- Pair reconciliation: per-account net across original+reversal = 0; `verify_entry_totals`
  passes on both; live demo printed `pair net=0.00`.
- Migration `0005` forward/reverse/re-apply verified on scratch DB; graph shows
  accounting 0001→0005 all applied.

## K. Reconciliation proof (EXECUTED)

Live walkthrough transcript (fresh scratch DB):

```text
first post: id=1 status=POSTED
retry: same_id=True entries=1 lines=2 records=1 audits=1
key reuse different op: rejected (...), entries=1
posted mutation: blocked (POSTED/REVERSED journal entries are immutable)
reversal: number=JE-1405-00001 status=POSTED reverses=JE-D1 orig_status=REVERSED
pair net=0.00 audits=[('POST', '1'), ('REVERSE', '1')]
double reversal: rejected; audits=2
```

## L. NOT tested

True multi-thread race timing (SQLite sandbox; covered instead by: DB unique
constraint test, row-lock in code, in-progress retry-signal test). `NOT VERIFIED`
PostgreSQL concurrency semantics. `NOT VERIFIED`

## M. Deferred

Stages 2.4, 2.5 (gates), Phases 3–18. No 2.4+ code written. `DEFERRED`

## N. Commit / O. Tree / P. main

- Single focused commit on `phase/2` (exact hash in the review response and `git log`).
- `git diff --shortstat` (pre-report): 3 files, +291/−28 — all 28 removed lines
  are the `_persist_entry` verbatim move + legacy-craft lines; ZERO assertions removed.
- Untracked `docs/phase-0/` left untouched, NOT committed (pre-existing).
- `main` untouched at `846a777`. `VERIFIED`

## Q. Known issues

1. **Interpretation (§4.6):** blocked/failed ops deliberately write NO audit —
   the contract requires none at this stage and §4.8 forbids partial audit state.
   Needs review acknowledgement.
2. **Known limitation (tested + documented):** `QuerySet.update()`/`delete()`
   bypass model guards (Django-level fact). Service code never bulk-writes journals.
3. **Test-artifact fix:** `test_retry_preserves_original_byte_identical` first failed
   comparing in-memory string `posting_date` vs DB date (frozen passthrough);
   fixed with `refresh_from_db()`. Product code never at fault.
4. Reversal inherits the original's posting date (same-period netting; timestamps
   record when). Flagged: Phase 3 periods may add policy.
5. Reversal numbering reuses `next_document_number("JE", jalali_year)` — new
   `accounting → documents`/`core.dates` dependency, no cycles.

## R. Final status

```text
IMPLEMENTED
TESTED
EXECUTED
EVIDENCE READY
AWAITING USER REVIEW
```

(APPROVED / FROZEN / COMPLETE are the user's to declare — not claimed here.
No Stage 2.4 work started.)
