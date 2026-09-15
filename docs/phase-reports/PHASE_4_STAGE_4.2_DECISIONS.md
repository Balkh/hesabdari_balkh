# Phase 4.2 — Architecture Discovery Record (ANALYSIS ONLY — NO IMPLEMENTATION)

**Date (UTC):** 2026-09-15
**Branch:** `phase/4` (HEAD `60dfaf7`, 4.1 FROZEN — untouched)
**Status:** discovery complete. FINAL USER RULINGS recorded 2026-09-15
(section 10). Architecture APPROVED; implementation BLOCKED by the
Remote CI gate (section 11). No model, migration, service, API, UI commit.
**Method:** every claim below cites contract section + line, or repo path.

---

## 1. CONTRACT EVIDENCE (exact sources)

| # | Finding | Source |
|---|---|---|
| C1 | Payment header carries BOTH `Party` and `Party Type` as separate fields | §7.3, L1430–1445 (esp. L1433–1434) |
| C2 | Balance identity key is `Party + Currency + Balance Type`; e.g. `Customer A / USD / Receivable` AND `Customer A / USD / Credit` | §2.5, L548–565 (esp. L551–562) |
| C3 | Authoritative chain flows into ONE `Party/Subsidiary Ledger` | §2.1, L495–501 |
| C4 | Shared flows reference role-neutral `Party` (Payment §7.2 L1407–1412; Return §8.2 L1557–1564; appendix Payment→Party L3302, Return→Party L3308); directional flows reference `Supplier` (§5.1) / `Customer` (§6.1) | L1407–1412, L1557–1564, L1140–1145, L1273–1281, L3296–3309 |
| C5 | `Customer Payment` / `Supplier Payment` are *payment types*, not master tables | §7.1, L1400–1405 |
| C6 | One `Party Ledger` reconciles to (plural) control accounts; `Party ledger ↔ control account` | §15.7 L2790–2808, §15.8 L2826–2833 |
| C7 | Customer/supplier NET positions are separate formulas (Receivable−Credit; Payable−Advance) — separation lives in the FINANCIAL layer, not identity | §2.3 L518–531, §2.4 L536–545 |
| C8 | Cash sale posts `Dr Cash / Cr Sales Revenue` — no receivable, no customer leg | §6.4 L1319–1331. No "cash customer" master exists anywhere |
| C9 | Golden-test naming is mixed: `Inactive supplier` (§5 list L1264) vs `Inactive party` (§7.10 L1542) | L1264, L1542 — AMBIGUOUS (see analysis) |
| C10 | Roadmap lists `Customers` + `Suppliers` as separate scope bullets (scope list, not a data model) | Phase 4 roadmap L3142–3143 |
| C11 | §13.2 ROLES = user roles (Administrator, Accountant, …), NOT party roles — no help, no conflict | L2533–2541 |
| C12 | ZERO master fields specified for Customer/Supplier/Party: no code, name, phone, address, contact, tax id anywhere. `Address/Phone` hits are company letterhead in print templates (§10.5 L2063–2067). `Unique code` appears ONLY for Product (§4.1 L916) | full-text search; L2063–2067, L916 |
| C13 | NO statement anywhere on whether one party can be both customer and supplier | full-text search (negative result) |
| C14 | Period closing `Preserves party history` — historical references must survive | §12.5 L2443–2451 |

Reading notes: C1+C2 are the strongest signals — transactions qualify a
shared Party by Type, and balances key off (Party, Currency, Balance Type).
C9 cuts both ways but is consistent with A (role-view naming on directional
flows, shared naming on shared flows). C10 is the only pro-separate signal
and describes SCOPE, not tables.

## 2. REPOSITORY EVIDENCE (exact paths)

| # | Finding | Source |
|---|---|---|
| R1 | `backend/parties/` = `.gitkeep` only; NOT installed; zero baked assumptions | `backend/parties/` |
| R2 | Zero Customer/Supplier/Party logic in code. Only hits: COA names `1500 Supplier Advances`, `2200 Customer Advances / Credits`, and an `fx.py` comment deferring subledgers to Phase 5 | `backend/accounting/coa.py:41,47`, `backend/fx.py:9` |
| R3 | Journals link to sources via generic `source_type`/`source_id` CharFields + index — role-agnostic, constrains nothing | `backend/accounting/models.py:50-51,73` |
| R4 | No party FK exists anywhere; 1310/2110 appear only in COA + tests | repo-wide search (negative result) |
| R5 | Master conventions (4.1 + Account): `name` + `name_fa`, `is_active` default True, `created_at`, BigAutoField PK, PROTECT FKs, audit CREATE/UPDATE via `record_audit_event`, no abstract bases anywhere | `backend/categories/`, `backend/uom/`, `backend/products/`, `backend/accounting/models.py:30-37` |
| R6 | 4.1 rulings: NO code where contract is silent (U-2/U-3); NO auto-numbering (`NumberSequence` is document-scoped); inert free-text storage acceptable, permanent UNIQUE rules are not | `PHASE_4_STAGE_4.1_DECISIONS.md` |
| R7 | Phase 5 exists ONLY as roadmap mentions (`Party Ledgers`, `Reconciliation`, `subledger hooks ready`) — no design contract to conform to or contradict | `docs/phase-0/PHASE_2_PLAN.md:128,136`, Phase 2/3 evidences |

## 3. ARCHITECTURE CANDIDATES

**Option A — Shared Party + roles (one table).** `Party` holds identity;
roles (`is_customer`, `is_supplier`) qualify it. Dual-role = both flags.

**Option B — Separate Customer and Supplier (two tables).** Each with own
identity columns; a dual-role business needs two records (or a cross-link).

**Option C — Shared base + role models.** Base identity table + per-role
extension tables. No repo precedent (R5: zero abstract/shared-base masters).

## 4. EVALUATION (14 criteria)

| Criterion | A: Shared Party | B: Separate | C: Base + roles |
|---|---|---|---|
| 1. Contract compatibility | STRONG: C1 (Party+Type), C2 (Party+Currency+BalanceType key), C3/C6 (singular Party Ledger) | WEAK: only C10 scope bullets; fights C2's key | NEUTRAL: nothing supports/contradicts |
| 2. Repo compatibility | GOOD: one `parties` placeholder (R1); generic source linkage (R3) | OK: needs 2 models + duplicated services | POOR: no shared-base precedent (R5) |
| 3. Future Phase 5 | NATURAL: ledger keys `(party_id, currency, balance_type)` = C2 verbatim | AWKWARD: `(customer_id XOR supplier_id)` or two ledgers vs singular C3/C6 | JOINS: workable, heavier |
| 4. Receivable/Payable separation | By balance type (contract's own mechanism, C2+C7) | By table (works, duplicates) | By balance type + joins |
| 5. Dual-role support | NATIVE (both flags) | FORCES duplicates — the exact evil §6 warns about | NATIVE-ish |
| 6. Historical integrity | ONE protect target | TWO targets (fine) | base+roles (fine) |
| 7. Duplicate identities | IMPOSSIBLE by construction | VIOLATED for dual-role traders (common in bazaar trade: same trader buys AND sells) | IMPOSSIBLE |
| 8. DB simplicity | ONE table | TWO near-identical tables | 2–3 tables + joins |
| 9. API simplicity (future) | ONE resource | TWO resources | NESTED |
| 10. Audit simplicity | ONE entity `Party` | TWO entities | 2–3 entities |
| 11. Reporting | ONE ledger query filtered by role/type (Customer/Supplier statements = role views, cf. §11.4 L2345–2346) | per-table queries + unions for party-wide views | joins |
| 12. Migration complexity | ONE 0001 | same 0001, 2 models | heavier |
| 13. Extensibility | add a role = add a flag (low weight: speculative) | new table per role | moderate |
| 14. Minimal footprint | WINS clearly | duplicates identity logic | most machinery |

C9 note: `Inactive supplier` vs `Inactive party` is consistent with A if
read as role-view vs shared-flow naming; under B both readings are also
possible. Treated as NEUTRAL — it does not decide.

## 5. DUAL-ROLE ANALYSIS (real ERP cases)

`ABC Trading` buys cooking oil from us (→ our RECEIVABLE on ABC) and sells
us rice (→ our PAYABLE to ABC). These are separate balance identities under
C2 (`ABC+AFN+Receivable`, `ABC+AFN+Payable`) — one legal party, two
positions. Forcing `ABC-Customer` + `ABC-Supplier` records (Option B) splits
contact data, doubles maintenance, breaks party-wide inquiry, and contradicts
the singular `Party Ledger` (C3/C6). Real ERPs (and this contract's C1/C2)
treat role as a QUALIFIER of identity, not identity itself. Master roles =
set; each transaction picks ONE type (C1 `Party Type`) — clean and complete.

## 6. IDENTITY / ROLE / LEDGER (kept separate)

```text
Party Identity  →  ONE record (who the business is)            [4.2]
Party Roles     →  customer / supplier / both (how we trade)   [4.2]
Ledger          →  (party, currency, balance type) → amounts    [Phase 5, NOT 4.2]
```

4.2 builds ONLY the top two layers. No balances, journals, accounts.

## 7. RECOMMENDED ARCHITECTURE (for user ruling — NOT final)

**Option A: one `Party` master in the `parties` app.**

- Identity: `name` required [T: a label is technically necessary];
  `name_fa` optional [A: mirrors 4.1 Cat/UOM]; NO code [U: same principle
  as 4.1 U-2/U-3 — silence ≠ permanent UNIQUE rule; safely additive later
  since Phase 5 keys off `party_id`].
- Roles: `is_customer`, `is_supplier` booleans, default False, dual-role
  ALLOWED; ≥1 role required (service + DB check) [U: a role-less party
  contradicts the entity's purpose — structural, same defense as 4.1 R-3].
- Contact: `phone`, `address`, `note` — optional inert free text, no
  validation beyond type/length, no uniqueness [U: zero invented rules;
  ignorable by Phase 5]. Stricter alternative: omit entirely (user choice).
- Status: single `is_active` [A]; NO per-role flags (unspecified → minimal).
- OMITTED explicitly: tax id, credit limit, payment terms, currency,
  balances, ledger, accounts, auto-numbering, geo tables, CRM machinery.
- Audit CREATE/UPDATE via existing writer [C: §13.4]; PROTECT for all
  future FKs [A]; bilingual pair per convention [A].

## 8. UNRESOLVED QUESTIONS (user MUST rule)

1. Confirm Option A (vs B)? §8-class: no EXPLICIT master-architecture rule
   in contract (C1/C2 govern transactions/ledgers, not the 4.2 table shape),
   and the choice materially shapes Phase 5 → user decision required.
2. Confirm dual-role allowed (vs exclusive XOR)?
3. Confirm roles as two booleans + ≥1-required (vs alternatives)?
4. Code: omit (recommended) vs user-assigned unique code now?
5. Contact trio: inert free text (recommended) vs omit entirely?
6. `name_fa`: optional (recommended) vs required?
7. Single `is_active` (recommended) vs per-role flags?

## 9. SCOPE STATEMENT

This discovery added ONE uncommitted docs file. Models/migrations/services/
serializers/views/API/frontend/ledger/balance/receivable/payable/account
mapping: ZERO created. Frozen phases + 4.1 + CI + dependencies: ZERO
touched. No commit made.

---

## 10. FINAL USER RULINGS (2026-09-15 — APPROVED, implementation still BLOCKED)

**FR-1. Architecture: Option A — Shared Party + Roles.** One `Party` = one
business/legal identity. No separate Customer/Supplier identities.

**FR-2. Dual-role: fully ALLOWED.** `is_customer=True` + `is_supplier=True`
(e.g. ABC Trading) lives in ONE master record. Never two records.

**FR-3. Roles: `is_customer` / `is_supplier` booleans, default False.**
Invariant `is_customer OR is_supplier` enforced at BOTH service/validation
and database-constraint layers. Role-less parties are rejected.

**FR-4. NO party code.** No code field, no auto-numbering, no NumberSequence.
Contract requires none; no new business rule invented. Phase 5 identifies
parties by primary key/reference.

**FR-5. Names: `name` required + `name_fa` OPTIONAL (repo convention wins).**
User's conditional inspection resolved: `Category.name_fa` and
`UOM.name_fa` are `blank=True` (4.1 U-2/U-3, contract-silent masters —
the exact analog of Party), `Account.name_fa` likewise; only
`Product.name_fa` is required, and solely because contract §4.1 lists it
without "optional" (4.1 R-7). Party names are contract-silent (C12), so
the real repo convention governs: `name` required [T], `name_fa` optional
[A]. No translation engine.

**FR-6. Contact: `phone`, `address`, `note` — all optional, plain storage.**
No uniqueness, no complex validation, no CRM, no address subsystem, no
phone-normalization engine.

**FR-7. Status: single `is_active` (default True).** No per-role flags.
Deactivation deletes nothing, breaks no history, invalidates no future
references, deletes no ledger data.

**FR-8. Explicitly OUT of 4.2 scope:** code, auto-numbering, currency,
balance, receivable, payable, ledger, opening balance, credit limit,
payment terms, account mapping, journal, journal line, posting,
settlement, inventory, warehouse, invoice, payment, CRM, tax subsystem.

**FR-9. Financial layer deferred:** Identity + Roles in 4.2; all
Receivable/Payable/Ledger behavior belongs to Phase 5.

## 11. GATE STATUS

```text
Architecture Decision     APPROVED (this section 10, 2026-09-15)
Phase 4.1 Local verify    GREEN (evidence-committed, re-verified at freeze)
Phase 4.1 User approval   YES
Phase 4.1 Frozen          YES (60dfaf7)
Remote CI for Phase 4.1   NOT RUN  ← HARD GATE; implementation BLOCKED
```

No 4.2 model/migration/service/test/API/frontend/commit existed or was
authorized until the implementation block was LIFTED by explicit user
order (master implementation prompt, 2026-09-15). Remote CI for Phase 4.1
REMAINS: NOT RUN — kept as a separate release/integration gate; it must
never be reported GREEN/PASS/VERIFIED until truly executed. This file was
committed as the authorized 4.2 decisions record (see git log).
