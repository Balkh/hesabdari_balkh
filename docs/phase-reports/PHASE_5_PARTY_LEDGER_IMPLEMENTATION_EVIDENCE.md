# PHASE 5 — PARTY LEDGER IMPLEMENTATION EVIDENCE

## 1. Scope

Party Ledger as a derived subsidiary attribution/read layer over posted
accounting truth (§0): per-line Party attribution + dynamic derivation +
controlled opening balances + reconciliation. No second posting/balance/
currency/FX/audit/idempotency system. No invoice/payment/return/
allocation engines. Service-level only (no API — §44 boundary: Phase-4
masters are domain-only; only fiscal-periods exposes serializers).

## 2. Baseline

Branch `phase/4`, base `7dd8d6d` (4.4 frozen), all frozen ancestors
verified (60dfaf7/3362748/083d925/09199d2). origin/main `646e35e`
untouched. Snapshot flap repaired content-identically (script modes +
stray zip); venv rebuilt (Django 5.2.17); PostgreSQL reinstalled
(17.11, role/db `erp_afghanistan`).

## 3. Approved decisions

OD-5-01 A (link table, no frozen change) · OD-5-02 A (per-line) ·
OD-5-03 A (controlled opening via `post_journal`, no one-shot) ·
OD-5-04 A (dynamic derivation, zero stored balances) · OD-5-05 A
(allocation records OUT). All honored verbatim; no unfreeze needed.

## 4. Files changed

`backend/party_ledger/` (10 files: app + models + services + ledger +
0001 + 40 unit + 12 golden tests) + 1 `INSTALLED_APPS` line + Phase-5
docs. Nothing else.

## 5. Architecture implemented

`PartyLedgerAttribution(journal_line OneToOne PROTECT, party FK PROTECT,
created_at)`; immutable save/delete via reused
`PostedImmutabilityError`; single `PARTY_LEDGER_ACCOUNTS` mapping
(1310/2110/2200/1500 → RECEIVABLE/PAYABLE/CUSTOMER_CREDIT/
SUPPLIER_ADVANCE); `services.py` (attribute + opening); `ledger.py`
(balance/statement/net/recon — read-only).

## 6. Attribution model

One link per journal line (DB OneToOne, §10/§31); eligibility =
POSTED/REVERSED status + party-account code (§11; DRAFT/cash/revenue/
3900 rejected loudly); CREATE audit via `record_audit_event`
(master-style); anonymous actor rejected, None allowed.

## 7. Derivation rules

Effective lines (POSTED+REVERSED) + attribution, grouped by
(Party, Currency, account-derived type); signs via reused
`normal_balance_of`; order = reused `CHRONOLOGY_ORDER` + line id (§19);
currency + type REQUIRED on every call (merging refused, never silent);
no mutation anywhere (§18).

## 8. Opening balance behavior

`open_party_balance` validates (party/currency/type/amount/actor) →
resolves party + 3900 accounts → party leg follows normal-balance side →
`post_journal` ("JE" system-number precedent, source OPENING_BALANCE,
rate passthrough, idempotency-key passthrough) → attributes party leg —
ALL in one atomic transaction (§14). Caller-owned `number` supported so
idempotent retries reproduce the fingerprint. Retry with same key+number
returns the original entry and skips existing same-party attribution;
different-party conflict re-raises loudly. Repeated openings allowed.

## 9. Currency behavior

Centralized Currency only; per-currency derivation; AFN equivalent
supplemental (frozen snapshot); mixed-currency summation refused at both
layers; no new currency/FX artifact (§26/§27).

## 10. Reconciliation invariant

`reconcile_party_ledger(currency)` compares, per account: GL sums vs
attributed sums, reporting unattributed legacy lines explicitly (§43).
`reconciled` ⟺ zero unattributed effect. Proven True with reversal
history (test 39, G51-12); proven honest-False with legacy lines (test
40). Party ↔ GL equality holds exactly when fully attributed (§37).

## 11. Test matrix

40 unit tests (§35.1–40: attribution 7, derivation 10, dual-role 3, net
5, opening 6, immutability 4, traceability 3, recon 2) + 12 goldens
(G51-01..12 per §36; future flows use clearly-marked SIMULATED journals
+ attribution only — no future entity invented; G51-11 pins the
allocation boundary by API absence).

## 12. Golden results

12 PASS / 0 FAIL (27-line trail:
`docs/phase-reports/PHASE_5_PARTY_LEDGER_GOLDEN_OUTPUT.txt`).

## 13. SQLite evidence

pytest 572 passed (520 + 52 new) · Django 17 OK + 555 OK · check 0
issues · makemigrations --check clean · migration zero→0001→zero→0001
OK · golden 12/0 · focused 52/52.

## 14. PostgreSQL evidence

Real PG 17.11 (`config.settings.postgres`): pytest 572 · Django 17 +
555 OK · check 0 · migration fwd/rev OK. No SQLite substitution.

## 15. Django checks

`check`: 0 issues both engines. `makemigrations --check`: clean.

## 16. Migration evidence

`party_ledger/0001_initial` only; FK-necessitated deps
(accounting 0007, parties 0001); no frozen migration touched, rewritten,
or squashed; forward/reverse verified on both engines.

## 17. Frozen-phase integrity evidence

`git diff 7dd8d6d` over accounting/parties/fiscal_periods/categories/
uom/products/warehouses/cash_accounts/exchange_houses/currencies/
documents/security/core/frontend/scripts = **0 lines**. No STOP
condition (§50) triggered. `diff --check` clean.

## 18. Known limitations

(a) Opening-number prefix "JE" reuses the reversal precedent — no
opening-specific prefix is contract-specified. (b) Legacy pre-Phase-5
journals stay unattributed by design (§42/§43) and surface via recon,
not fabrication. (c) `attribute_journal_line` accepts no update path by
design (§9). (d) No API/UI (service-level boundary, §44).

## 19. Future boundaries

Invoice/payment/return/allocation/refund-flow/cash/EH/inventory/report
engines untouched (§32/§33). Future posting flows call
`post_journal` + `attribute_journal_line` (§12); FX via frozen `fx.py`.

## 20. Exact commit SHAs

- 1319086f7c06232d3e08d11246172e766191902b — docs: discovery
- 9953e2965c3949d1ea9fa57057c8c2be35ee0062 — feat (9 files +1317/−1)
- 3afdc520bf0d572fe2cd145c662742bae3a6e6b7 — test: golden (+283)
- C3: this evidence commit ("docs: record phase 5 implementation evidence").

## 21. Working-tree status

Clean at C3 (verified post-commit).

## 22. Final status

```text
IMPLEMENTATION COMPLETE → AWAITING USER REVIEW
```
