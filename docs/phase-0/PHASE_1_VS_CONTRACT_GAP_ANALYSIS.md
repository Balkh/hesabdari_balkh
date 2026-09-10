# Phase 1 Foundation vs Phase 0 Contract — Gap Analysis

**Date:** 2026-09-09
**Contract:** `docs/phase-0/PHASE_0_CONTRACT_V2.1.md` (v2.1, consistency-locked)
**Baseline verified in this workspace:** Django check 0 issues, 17 Django tests PASS, 25 pytest PASS

---

## 1. What Phase 1 already satisfies

| Contract requirement | Phase 1 status | Evidence |
|---|---|---|
| G2 Double-entry balance check | ✅ DONE | `accounting/services.py::post_journal` rejects unbalanced journals; test `test_unbalanced_entry_is_rejected_without_entry` |
| G5 Atomicity (journal-level) | ✅ DONE | `transaction.atomic()` in `post_journal`; no entry left behind on failure |
| G12 Single source of truth (journal) | ✅ DONE | `JournalEntry` + `JournalLine` models with PROTECT relations |
| §1.4 Account types (5 types) | ✅ DONE | `AccountType` TextChoices |
| §1.6 COA structure (partial) | 🟡 PARTIAL | `Account` has code/name/type/parent/is_posting — but canonical V1 accounts NOT seeded, no hierarchy enforcement |
| §1.8 Journal contract (partial) | 🟡 PARTIAL | Has ID/date/source/description/status/timestamps; MISSING: currency context, stored totals, created_by |
| §1.9 Posting integrity (partial) | 🟡 PARTIAL | Atomic ✅, traceable (source_type/source_id) ✅; MISSING: idempotent posting key, audit event on post, posted-immutability enforcement |
| §3.1–3.2 AFN base + USD | ✅ DONE | `Currency` with `one_base_currency` constraint; test enforces AFN=base |
| §3.4 Directional historical rate | ✅ DONE | `ExchangeRate` source→target + effective_date + unique pair/date |
| §3.11–3.12 Precision/rounding | ❌ MISSING | No central money/rounding utilities; rate stored at 8dp, contract requires 4dp display + Half-Up rules |
| §10.2 Numbering | ✅ DONE | `next_document_number` with `select_for_update`, Jalali-year series |
| §10.3 Gregorian/UTC internal storage | ✅ DONE | `core/dates.py` boundary (ISO persistence, Jalali presentation, UTC timestamps) |
| §12 Fiscal periods | ❌ MISSING | `fiscal_periods/` is an empty placeholder — posting-date validation against Open period does not exist |
| §13 Audit foundation | 🟡 PARTIAL | `AuditEvent` model exists; NOT wired to posting; missing actions (REJECT, period events, adjustments) |
| G10/G11 Evidence gate | ✅ PROCESS | `scripts/verify_*.sh` + CI jobs; this analysis follows the same gate |

---

## 2. Gaps ordered by contract implementation order (§16.4)

### Phase 2 — Accounting Core (NEXT — nothing here may be skipped)

1. **Canonical COA seed (§1.6):** all V1 four-digit accounts (1000…8200) with correct
   type, parent hierarchy, `is_posting` flags (group accounts non-posting),
   `is_active` flags (2400 Tax = V2-reserved → inactive in V1).
2. **Journal Entry contract completion (§1.8):** add currency context (transaction
   currency + AFN equivalent + rate snapshot), stored `total_debit`/`total_credit`,
   `created_by` user reference.
3. **Posting engine hardening (§1.9):** idempotency key on post (duplicate command →
   same entry, no duplicate accounting), audit event per posting, reversal support
   (REVERSED status + reversing entry, never edit/delete), posted-immutability guard
   (model-level + service-level).
4. **Account balances (§1.2 chain):** validated balance computation per account
   (debit − credit by normal balance), Trial Balance query with Debit = Credit proof.
5. **Source-document traceability:** every journal traceable to its source document;
   journal → source navigation tested.
6. **FX accounts (§1.10):** 8100/8200 usable as posting accounts; realized FX posting
   pattern proven by golden tests (settlement rate ≠ historical rate).
7. **§1.13 Golden Tests:** all 16 accounting golden tests executed with evidence.
   (Customer/supplier/purchase/sale scenarios at Phase 2 level are proven with
   direct journal postings to 1310/2110/1410/4100/5100 — full workflows arrive in
   Phases 7/8/9.)

### Phase 3 — Fiscal Period (§12)

* `FiscalPeriod` model (name, start/end Gregorian dates, OPEN/CLOSED/LOCKED).
* `Posting Date ∈ Open Period` enforcement inside the posting engine.
* Close/Reopen/Unlock with authorization + reason + audit; reopen never unlocks posted rows.
* Historical balance queries (party/stock/cash on date X) — interfaces defined here,
  fully populated as later phases land.

### Phases 4–16 — per contract §16.4, in dependency order

Master data → Party ledgers → Inventory engine → Purchase → Sales → Payments →
Returns → Cash & Exchange House (+ internal currency exchange) → Remittance record →
Documents & Printing → Reporting & Reconciliation → Security & Audit → Backup.

### Phase 17–18 — Integration validation + Commercial readiness (gated, §16.5)

---

## 3. Forbidden-behavior checklist for Phase 2 (from §16.6)

Phase 2 implementation MUST be reviewed against items:
1 (unbalanced), 2–4 (history rewrite/delete/duplicate), 5–6 (currency merge, rate rewrite),
8 (partial posting), 21–22 (false success, silent reconciliation), 23 (Jalali storage).

---

## 4. Verdict

```text
Phase 1 foundation is COMPATIBLE with the Phase 0 contract.
No rework of Phase 1 is required; Phase 2 extends it.
Next step: Phase 2 — Accounting Core, in reviewable stages with golden-test evidence.
```

Plan: `docs/phase-0/PHASE_2_PLAN.md`
