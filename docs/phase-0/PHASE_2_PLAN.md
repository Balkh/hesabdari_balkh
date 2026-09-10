# Phase 2 — Accounting Core: Implementation Plan

**Contract:** `docs/phase-0/PHASE_0_CONTRACT_V2.1.md` §16.4 (Phase 2) + Section 1 + G1–G12
**Gate per stage (§16.5):** Implement → Unit Tests → Golden Tests → Failure/Rollback →
Reconciliation → Historical Integrity → Evidence Report → USER REVIEW → APPROVED → FROZEN → next

---

## Stage 2.1 — Canonical Chart of Accounts (§1.6)

**Scope**
- COA seed: all V1 four-digit accounts with canonical codes, names (EN + FA),
  account types, parent links, `is_posting` flags.
- Group (non-posting) accounts: 1000, 1100, 1200, 1300, 1400, 2000, 2100,
  3000, 4000, 4100, 5000, 6000.
- Posting accounts: 1110, 1120, 1210, 1220, 1310, 1410, 1420, 1500, 1900,
  2110, 2200, 2900, 3100, 3900, 3950, 4110, 4120, 4200, 5100, 5200,
  6100, 6200, 6300, 8100, 8200.
- 2400 Tax Payable: created as **inactive** (V2-reserved, §16.3), cannot receive postings.
- COA rules enforced: stable codes, group accounts reject postings (already in
  `post_journal`; extended with tests for every group account), future expansion safe.

**Tests**
- Seed idempotency: running the seed twice changes nothing (no duplicates).
- Every canonical code exists with correct type/parent/posting flags.
- Posting to each group account is rejected; posting to each posting account succeeds.
- 2400 rejects postings while inactive.

**Evidence:** seed test run + full account listing query output.

---

## Stage 2.2 — Journal Contract Completion (§1.8) + Money Precision (§3.11–3.12)

**Scope**
- `JournalEntry`: add transaction currency (FK → Currency), AFN equivalent totals,
  rate snapshot (rate + rate date + direction text), stored `total_debit`/`total_credit`,
  `created_by` (FK → user, nullable for system).
- `JournalLine`: add optional `reference` field.
- Central money module (`core/money.py`): Half-Up rounding, `LINE_TOTAL(qty × price, 2)`,
  `COGS(qty × AVCO, 2)`, `FX_EQUIVALENT(amount × rate, 2)`; rate display precision 4.
- Migration preserves existing Phase 1 journals (defaults/backfill, no history rewrite).

**Tests**
- Stored totals always equal sum of lines; mismatch → rejection.
- Currency context required; AFN equivalent computed with Half-Up.
- Rounding golden vectors (§3.12), incl. 0.5-up edge cases.
- Existing Phase 1 journals still readable after migration.

**Evidence:** migration run + rounding vector output + journal totals proof.

---

## Stage 2.3 — Posting Integrity: Idempotency + Immutability + Reversal + Audit (§1.9, G4)

**Scope**
- `post_journal(..., idempotency_key=...)`: same key returns the original entry,
  never a duplicate (reuses `core/idempotency.py` + unique key on entry).
- Posted-immutability guard: any `save()`/`delete()` on a POSTED entry or its lines
  raises (model `save/delete` overrides + service checks); corrections only via reversal.
- `reverse_journal(entry, reason, user)`: creates a linked reversing entry
  (mirrored lines, negative-effect), marks original REVERSED; reversal of a reversal
  is rejected (one-level); DRAFT cannot be reversed (only cancelled/deleted pre-post).
- Audit: every post/reversal writes an `AuditEvent` (user, timestamp UTC, action,
  entity, previous/new state, reason).

**Tests**
- Double-submit with same key → 1 entry, identical response.
- Edit/delete POSTED entry or line → blocked at model AND service level.
- Reversal balances, links both directions, preserves original lines byte-identical.
- Double reversal rejected; audit rows exist for post + reversal + blocked attempts.

**Evidence:** idempotency proof + immutability proof + reversal ledger output + audit listing.

---

## Stage 2.4 — Balances, Trial Balance & Source Traceability (§1.2, §1.8)

**Scope**
- `account_balance(account, date_from=None, date_to=None)`: posted lines only,
  signed by normal balance (§1.4); DRAFT excluded; REVERSED originals still count
  (their reversal nets them — history preserved, G4/G6).
- `trial_balance(date_to)`: all accounts with posted activity; MUST prove
  `Σ Debit = Σ Credit`; returns per-account debit/credit/balance.
- Source traceability: `entry.source_type/source_id` indexed; `trace_source(entry)`
  resolves the source document reference; journals queryable by source.

**Tests**
- Balance math per account type incl. contra accounts (4200 Sales Returnsdebit-normal
  under Revenue; 5200 Purchase Returns credit-normal under COGS).
- Trial Balance balanced on a multi-entry fixture incl. a reversal.
- DRAFT entries never affect balances; backdated POSTED entries do (chronology
  Posting Date → Document Sequence → Entry ID, §2.8).
- Source → journals → lines round-trip.

**Evidence:** trial-balance report output + traceability demo.

---

## Stage 2.5 — FX Realization Pattern (§1.10–1.12) + §1.13 Golden Suite

**Scope**
- Realized FX helper: given historical obligation (amount, currency, historical rate)
  and settlement (amount, currency, settlement rate), compute FX difference and post
  the gain/loss leg to 8100/8200. Unrealized revaluation explicitly NOT implemented
  (V2, §1.10).
- Full §1.13 golden suite executed end-to-end (16 scenarios), each printing its
  journals + balances + reconciliation line.

**Tests (golden, each with printed evidence)**
1. Balanced journal 2. Unbalanced rejection 3. Customer receivable (Dr 1310 / Cr 4100)
4. Supplier payable (Dr 1410 / Cr 2110) 5. Customer receipt (Dr 1110 / Cr 1310)
6. Supplier payment (Dr 2110 / Cr 1110) 7. Purchase 8. Sale + COGS pair
9. COGS math 10. Exchange-house movement (Dr 1210 / Cr 1110)
11. FX gain (Dr 1310-equivalent… / Cr 8100 pattern) 12. FX loss (Dr 8200…)
13. Historical rate preservation (rate change does not touch old journals)
14. Duplicate posting prevention 15. Atomic rollback (mid-post failure → zero rows)
16. Source-document traceability.

**Evidence:** golden-suite run log + per-scenario journal printouts.

---

## Phase 2 completion checklist (§16.5)

- [ ] Stages 2.1–2.5 implemented, each reviewed and frozen
- [ ] Full regression: Phase 1 suite + Phase 2 suite green on SQLite AND PostgreSQL job
- [ ] Reconciliation proof: Trial Balance balanced; subledger hooks ready for Phase 5
- [ ] Failure/rollback proofs collected
- [ ] Evidence report written → USER REVIEW → APPROVED → FROZEN → Phase 3

---

## Explicitly NOT in Phase 2 (per §16.4 order)

Fiscal periods (Phase 3), master data (Phase 4), party ledgers/advances (Phase 5),
AVCO engine (Phase 6), purchase/sales/payment/return workflows (Phases 7–10),
cash/exchange-house ledgers (Phase 11), remittance (Phase 12), printing (Phase 13),
reporting (Phase 14). Phase 2 proves the *accounting patterns* those phases will use.
