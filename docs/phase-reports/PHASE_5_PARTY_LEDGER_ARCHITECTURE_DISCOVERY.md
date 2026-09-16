# PHASE 5 — PARTY LEDGER ARCHITECTURE DISCOVERY (NO IMPLEMENTATION)

**Status:** DISCOVERY COMPLETE → AWAITING USER REVIEW. No models,
migrations, services, tests, or production code created or modified.
No commit. No merge. No push. `origin/main` untouched.
**Method:** every claim cites contract section + line, or repo path + line.

---

## A. EXECUTIVE SUMMARY

The contract (§2.1) fixes the architecture's spine: Business Transaction
→ Posted Accounting Transaction → **Party/Subsidiary Ledger** → Gross
Positions → Net Position → Display. The Party Ledger is therefore a
DERIVATION of posted accounting, never a second posting system (G3, L40).
Balance identity is exactly `Party + Currency + Balance Type` (§2.5
L550–553). Four balance types key off four existing posting accounts
(1310/2110/2200/1500). The ONE structural gap: journal lines reference
`Account` only — no party dimension exists — so Phase 5 must add a
party-ATTRIBUTION mechanism without touching frozen Phase 2. Five open
decisions (OD-5-01..OD-5-05) need user rulings; everything else is
evidence-settled. Recommended: per-line attribution link table (new
Phase-5 model, zero frozen changes) + fully derived balances + dynamic
read model; allocation records and refund workflows stay in future phases.

## B. REPOSITORY BASELINE

```text
Branch: phase/4 — HEAD: 7dd8d6d (4.4 closure) — tree: clean
4.1: 60dfaf7 ✓  4.2: 3362748 ✓  4.3: 083d925 ✓
4.4: 09199d2 (evidence; ancestor of HEAD ✓) + freeze 7dd8d6d
origin/main: 646e35e (untouched)
```

Pre-discovery dirt (transient, repaired WITHOUT content change): snapshot
had stripped script modes (100755→100644, all 4 CONTENT-OK vs HEAD) and
my own download-task zip had landed in repo root (untracked, removed).
venv + pg_isready are snapshot-absent; discovery executed nothing, so no
repair was performed. Frozen phases 1/2/3/4.1–4.4: zero diff, zero edits.

## C. CONTRACT EVIDENCE (C = mandatory, X = contextual)

| # | Finding | Source | Class |
|---|---|---|---|
| P1 | AUTHORITATIVE CHAIN: Business Txn → Posted Accounting Txn → Party/Subsidiary Ledger → Gross Positions → Net Position → Display | §2.1 L495–505 | C |
| P2 | Preserve separately: Gross Receivable/Payable; Credit/Advance; Net Position | §2.2 L508–513 | C |
| P3 | Customer Net = Receivable − Customer Credit; status DEBTOR/CREDITOR/ZERO | §2.3 L518–531 | C |
| P4 | Supplier Net = Payable − Supplier Advance | §2.4 L536–542 | C |
| P5 | Balance identity: `Party + Currency + Balance Type` (+ per-currency examples; never merged) | §2.5 L548–565 | C |
| P6 | AFN equivalent supplemental — never replaces original balance | §2.6 L568–579 + G8 | C |
| P7 | Previous balance DERIVED from posted history, never hand-typed on invoices | §2.7 L581–587 | C |
| P8 | Chronology: Posting Date → Document Sequence → Journal Entry ID | §2.8 L589–599 | C |
| P9 | Overpayment: warn + show excess + explicit confirm; reduce / convert-to-credit / controlled-refund; no choice = no posting | §2.9 L601–616 | C |
| P10 | V1 manual allocation only; no auto oldest-first | §2.10 L618–624 | C |
| P11 | Refund of credit/advance = controlled workflow | §2.11 L628–630 | C |
| P12 | OPENING: controlled opening transactions; counter-account `3900 Opening Balance Equity` | §2.12 L634–640 | C |
| P13 | §2.13 goldens: debtor, full/partial payment, credit, overpayment, payable, advance, multi-currency, historical + opening balance, negative-allocation rejection, **Party ↔ GL reconciliation** | L646–658 | C |
| P14 | Payment equation: Payment = Allocated + Unallocated/Credit; allocation shapes + rules (>0, ≤ outstanding, none to fully-paid) | §3.8–3.9 L750–790, §7.4–7.6 L1448–1472 | C |
| P15 | Cross-currency: V1 permitted; currencies + historical rate preserved; settlement rate recorded; FX calculated; preview before posting | §3.7/§3.10 L740–800, §7.9 L1513–1520, §15.11 L2883–2890 | C |
| P16 | Customer overpayment posting: Dr Cash/EH, Cr Customer Receivable, Cr Customer Credit | §7.7 L1474–1482 | C |
| P17 | Supplier overpayment posting: Dr Supplier Payable, Dr Supplier Advance, Cr Cash/EH | §7.8 L1484–1492 | C |
| P18 | Invoice postings: PI Dr Inventory/Expense Cr Supplier Payable (or Cash/EH); SI Dr Customer Receivable Cr Sales Revenue (+ COGS); cash sale Dr Cash | §5.6 L1236–1245, §6.4 L1320–1329 | C |
| P19 | Returns: outstanding→balance decreases; fully-paid→credit/advance created; partial→proportional settlement, no duplicate credit; Dr Sales Returns Cr Rec/Credit; Dr Pay/Adv Cr Inventory | §8.4–8.7 L1573–1630 | C |
| P20 | Realized FX when settlement rate ≠ historical obligation rate | L412; L754–819 | C |
| P21 | Flows: Payment → Party Ledger → Cash/EH → Accounting; Return → Inventory → Party Ledger → Accounting; Cash → Cash Ledger → Party Ledger if applicable | §15.3–15.5 L2742–2773 | X |
| P22 | Recon table: Party Ledger = Party Control Account (+ Inv/Cash/EH pairs); "Party ledger ↔ control account" | L2795–2810; L2832 | C |
| P23 | Phase 5 roadmap: Receivable, Payable, Customer credit, Supplier advance, Gross/net position, Opening balances, Reconciliation | L3150–3157 | X |
| P24 | Numbering `TYPE-YYYY-XXXXX` (SI/PI/PMT/RTN…); "Duplicate number" goldens; idempotency-family goldens (duplicate posting prevention, atomic rollback, source traceability) | §10.2 L1995–2010; §1.13 L470–488 | C |
| P25 | ZERO: Qarddar/Talabkar (only DEBTOR/CREDITOR L530–531), per-party COA leaves, party↔account mapping, netting/set-off, one-shot-opening rule, allocation-record schema | full-text negative | — |

## D. EXISTING ACCOUNTING INTEGRATION (all frozen, reuse-only)

- `post_journal(number, posting_date, description, lines, source_type, source_id, …)` (`services.py:152`): balance validation, fingerprint + idempotent retry (`:108–150`), POST audit (`:95`), OPEN-period gate (`:183`). Reverse via `reverse_journal` (`:247`), gate on ORIGINAL date (`:274`).
- Immutability in-model: POSTED/REVERSED JE/JL refuse save/delete except POSTED→REVERSED status flip (`models.py:76–140`).
- `balances.py`: `account_balance` (read-only, POSTED+REVERSED lines, **refuses mixed currencies** `:77–92`), `trial_balance`, **`journals_by_source` + `trace_source`** (`:190–214`) — source layer exists.
- `fx.py`: `compute_realized_fx(obligation_kind RECEIVABLE|PAYABLE, …)` (`:189`), `post_realized_fx_settlement` (`:357`), `post_fx_conversion` (`:415`); `FXSettlement` immutable, kinds CONVERSION/RECEIVABLE/PAYABLE (`models.py:143–213`). Phase 2.5 ALREADY owns realized-FX computation + posting.
- `core/idempotency.py`: `idempotent_operation(key, operation)` + `IdempotencyRecord`; JE `idempotency_key` unique-nullable.
- Audit: LOGIN/LOGOUT/CREATE/UPDATE/**POST/REVERSE**/APPROVE (`security/models.py:5–12`).
- Periods: `assert_posting_date_open`, `find_period_for_date` (`fiscal_periods/services.py:103–121`).
- **Gap (the crux):** JE has `source_type/source_id` (indexed) but NO party key; JL references `Account` only. No party dimension anywhere in accounting.

## E. EXISTING PARTY ARCHITECTURE (frozen 4.2 — untouched)

`Party(id, name, name_fa, is_customer, is_supplier, phone, address, note,
is_active, created_at)` + ≥1-role invariant at service + DB. Zero
financial fields (verified). Dual-role allowed → ledger MUST support
both directions per party simultaneously. No redesign, no split, no
balance fields (contract never requires them — P25).

## F. EXISTING COA FINDINGS (repo == contract §1.6; discovery only)

| Code | Name | Posting | Parent | Role in Phase 5 |
|---|---|---|---|---|
| 1300 Accounts Receivable | control | No | 1000 | control (recon target) |
| **1310 Trade Receivables** | leaf | **Yes** | 1300 | **Receivable lines** |
| **1500 Supplier Advances** | leaf | **Yes** | 1000 | **Supplier-advance lines** |
| 2100 Accounts Payable | control | No | 2000 | control (recon target) |
| **2110 Trade Payables** | leaf | **Yes** | 2100 | **Payable lines** |
| **2200 Customer Advances / Credits** | leaf | **Yes** | 2000 | **Customer-credit lines** |
| 3900 Opening Balance Equity | leaf | Yes | 3000 | opening counter-account (P12) |
| 4200 Sales Returns / 5200 Purchase Returns | leaves | Yes | 4000/5000 | return postings (P19) |
| 8100/8200 FX Gain/Loss | leaves | Yes | — | settlement FX (P20) |

No per-party leaves; none justified (P25). Balance TYPE derives from
WHICH of 1310/2110/2200/1500 a line hits.

## G. EXISTING CURRENCY / FX FINDINGS

Centralized `Currency` (code unique, `is_base` partial-unique) + directional
`ExchangeRate`; `JE.currency` FK nullable (legacy-unknown); JE snapshots
(afn_total/rate/rate_date/rate_direction); per-line currency via entry;
mixed-currency summation refused (D). No `Customer USD` masters (none
exist; P5 forbids merging). FX boundary: computation + posting stay in
frozen `fx.py`; Phase 5 only attributes + reads (settlement call-sites
belong to future payment flows).

## H. PARTY LEDGER ARCHITECTURE OPTIONS (D5-01 — see OD-5-01)

1. **Dedicated posting model:** REFUTED — P1/G3 forbid a second posting truth.
2. **Pure view over JournalLine:** REFUTED as sole mechanism — lines carry no party key (D-gap); shared 1310/2110 lines unattributable.
3. **Source-reference layer only:** INSUFFICIENT alone — transport exists (`journals_by_source`) but party resolution needs documents that don't exist until future phases; ledger unreadable in Phase 5.
4. **Attribution projection (RECOMMENDED):** NEW Phase-5 link rows mapping posted journal LINES → Party (+ currency denormalized or joined); balances always derived from posted lines; zero frozen changes. Type = f(account).

## I. BALANCE IDENTITY (D5-03 — SETTLED)

`Party + Currency + Balance Type` — contract-literal (P5). Multi-currency
mandatory; AFN equivalent supplemental display only (P6). Types:
{Receivable→1310, Payable→2110, CustomerCredit→2200, SupplierAdvance→1500}.
No "Supplier Credit"/"Customer Advance" distinct terms exist (P25) —
2200's slash covers customer-side wording.

## J. RECEIVABLE / PAYABLE SEMANTICS (D5-05 — SETTLED)

Gross directions from invoice-side postings (P18); dual-role parties
carry both simultaneously (E). Net positions per P3/P4; status
DEBTOR/CREDITOR/ZERO (P3). Display words (Qarddar/…) are NOT CONTRACT-
SPECIFIED — never in the accounting layer (P25).

## K. CREDIT / ADVANCE SEMANTICS (D5-04 — SETTLED)

Separate balance types AND separate accounts (P2/P5/P16/P17/F):
over/under-payment and fully-paid returns CREATE credit/advance postings
(never bare negatives on gross). Direction within a type = debit/credit;
net = gross − contra (P3/P4).

## L. OPENING BALANCE ANALYSIS (D5-06 — OD-5-03)

P12 + P13 put opening in the balance domain (Phase 5's roadmap P23
lists "Opening balances"). Mechanism = ordinary controlled journals
(Dr 1310 / Cr 3900, etc.) through frozen `post_journal` (period gate +
idempotency + POST audit automatic) + attribution links. OPEN: whether
"controlled" additionally means one-shot-per-identity (P25: silent).

## M. POSTING / JOURNAL INTEGRATION (D5-02 — SETTLED)

Balances derive EXCLUSIVELY from POSTED+REVERSED lines (P1/P7/P22/D):
originals stay visible (REVERSED), offsetting entries net the balance,
`reverses`-FK links them, reversals obey the period gate. Phase 5 posts
nothing except opening journals (via frozen pipeline) and NEVER stores
balances. Recon invariant: Σ party derivation == control balance (P22).

## N. SOURCE TRACEABILITY (§8 — SETTLED transport, OD-5-01 attribution)

`source_type/source_id` + index + `journals_by_source`/`trace_source`
suffice as transport for future invoice/payment/return/settlement docs
(numbering P24). They cannot attribute party — hence the link table.

## O. REVERSAL / IMMUTABLE HISTORY (§9 — SETTLED)

Frozen semantics reused verbatim: history visible, balance net-correct,
link via `reverses`, no party-ledger reversal engine, attribution links
immutable like the journals they annotate (else P22 recon breaks).

## P. CURRENCY RULES (§10 — SETTLED)

Per-currency derivation (P5 + mixed-currency refusal); original currency
never lost (JE snapshots + G8/P6); no new currency field/system/masters.

## Q. AUDIT / IDEMPOTENCY (§18/§19 — SETTLED)

Three layers stay distinct: master CREATE/UPDATE (attribution-link
creation), journal POST/REVERSE (frozen `_audit_post`), financial-flow
events (future phases, existing actions). Idempotency via
`idempotent_operation` + JE key + fingerprint retry — no new engine.

## R. CONCURRENCY / DATABASE CONSTRAINTS (§20 — design recorded)

Attribution rows immutable (O); uniqueness target: one link per journal
LINE for party-account lines (OD-5-02); (party, currency, type) is a
QUERY identity, not a stored row (no materialization — OD-5-04);
writes atomic with the journals they annotate (opening flow).

## S. PHASE BOUNDARY (§21)

Phase 5 = attribution + derivation + read model + opening support.
OUT: invoice/payment/return/cash/EH/remittance/bank engines, allocation
RECORDS (OD-5-05), refund WORKFLOW execution (P11 rule noted, flow
future), AVCO/stock/movements, printing/report suite, licensing, UI.
Future consumers: purchases/sales/payments/returns (post + attribute),
Phase 6 (untouched), Phase 11 (cash/EH legs of party journals).

## T. DECISION MATRIX (/30: Contract/Repo/Future/Scope/Simplicity/Integrity)

| Option | C | R | F | S | S | I | Total | Rec |
|---|---|---|---|---|---|---|---|---|
| OD-5-01 A: link table (no frozen change) | 5 (P1: subledger of posted) | 5 (projection pattern) | 5 | 5 | 4 | 5 | 29 | ✅ |
| OD-5-01 B: source-conventions only | 2 (unreadable w/o docs) | 3 | 2 | 4 | 5 | 2 | 18 | ❌ |
| OD-5-01 C: FK on frozen JE/JL | 3 | 1 (frozen break) | 4 | 1 | 4 | 4 | 17 | ❌ |
| OD-5-02 A: per-LINE links | 5 (P16/P17 multi-type journals) | 5 | 5 | 4 | 4 | 5 | 28 | ✅ |
| OD-5-02 B: per-journal + invariant | 2 (invariant NOT specified) | 3 | 3 | 5 | 5 | 3 | 21 | ❌ |
| OD-5-03 A: controlled journals, no one-shot | 4 (P12 literal) | 5 (frozen pipeline) | 4 | 5 | 5 | 4 | 27 | ✅ |
| OD-5-03 B: one-shot enforced | 2 (P25 silent = invention) | 3 | 3 | 3 | 3 | 4 | 18 | ❌ |
| OD-5-04 A: dynamic derivation | 5 (P1/P7/G3) | 5 (balances.py reads) | 4 | 5 | 5 | 5 | 29 | ✅ |
| OD-5-04 B: materialized balances | 1 (G3 forbids side truth) | 1 | 3 | 2 | 2 | 2 | 11 | ❌ |
| OD-5-05 A: allocation records OUT (future) | 4 (P14 = payment-flow data) | 5 | 5 | 5 | 5 | 5 | 29 | ✅ |
| OD-5-05 B: allocation schema now | 2 (entities don't exist) | 2 | 2 | 1 | 2 | 3 | 12 | ❌ |

## U. OPEN DECISIONS (user MUST rule — §29 class)

```text
OD-5-01
Question: By what mechanism are posted journal lines attributed to parties?
Contract evidence: P1 (subledger derives from posted); P22 (recon); D-gap (no party key).
Repository evidence: source layer exists (journals_by_source); JL has Account only; Phase 2 frozen.
Option A: NEW Phase-5 link table (posted line → Party). Zero frozen changes.
Option B: Structured source conventions only; party resolved via future documents (ledger unreadable until then).
Option C: Add FK to frozen JE/JL (requires explicit Phase-2 unfreeze).
Recommendation: A.
User decision required: YES
```

```text
OD-5-02
Question: Attribution granularity — per journal line or per journal entry?
Contract evidence: P16/P17 journals hit TWO balance types for one party (multi-type journals exist).
Repository evidence: lines are the balance unit (balances.py sums lines).
Option A: Per-LINE links (precise; type = f(account)).
Option B: Per-journal links + single-party-per-journal invariant (invariant NOT CONTRACT-SPECIFIED).
Option C: (none viable — per-account collapses to A in practice)
Recommendation: A.
User decision required: YES
```

```text
OD-5-03
Question: Does "controlled opening" (P12) include one-shot-per-(party, currency, type)?
Contract evidence: P12 literal (controlled transactions + 3900) + P13/P23 list opening in-domain; one-shot NOT CONTRACT-SPECIFIED (P25).
Repository evidence: frozen pipeline already gives period gate + idempotency + POST audit.
Option A: Controlled = explicit + audited + idempotent + open-period; repeats allowed as corrections-by-new-journal.
Option B: Enforce one-shot per identity (invented constraint).
Option C: Opening belongs to a later phase (weak: P23 lists it in Phase 5).
Recommendation: A.
User decision required: YES
```

```text
OD-5-04
Question: Dynamic derivation or materialized balances for the read model?
Contract evidence: P1/P7/G3 (derive; no side truth); P8 ordering; P22 recon.
Repository evidence: balances.py read-only derivation; mixed-currency refusal.
Option A: Dynamic (running balance calculated at read time).
Option B: Materialized/cache with rebuild (no scale evidence; G3-hostile).
Option C: (none — hybrid = A until proven otherwise)
Recommendation: A.
User decision required: YES
```

```text
OD-5-05
Question: Do payment↔invoice ALLOCATION records (§7.4/P14) belong to Phase 5?
Contract evidence: P14 shapes live in payment/allocation sections (§3.8/§7.4), not §2; P10/P11 workflows are payment-flow concerns.
Repository evidence: invoice/payment entities do not exist yet.
Option A: OUT — future payment engine owns allocation records; Phase 5 attributes resulting journals only.
Option B: IN — schema now (premature: references nonexistent entities).
Option C: (none)
Recommendation: A.
User decision required: YES
```

## V. RECOMMENDED ARCHITECTURE

New `party_ledger`-area (name TBD at implementation): immutable link rows
(posted-JL → Party, per-line) + derivation queries over POSTED+REVERSED
lines grouped by (party, currency, account-derived type) in §2.8 order +
statement read model (opening/derived, debit/credit, running balance,
source, description) + opening journals via frozen `post_journal` +
CREATE audit on links. Zero frozen changes. Zero stored balances. Zero
new engines (posting/currency/FX/audit/period/idempotency all reused).

## W. IMPLEMENTATION PRECONDITIONS

1. User rulings on OD-5-01..OD-5-05. 2. venv + PostgreSQL restored
(snapshot-stripped; discovery ran nothing). 3. Explicit implementation
order (this doc grants none). 4. Freeze discipline continues: any
OD-5-01-Option-C choice needs a separate Phase-2 unfreeze stating reason.
