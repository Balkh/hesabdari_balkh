# Stage 2.5 — Realized FX Pattern + §1.13 Golden Suite

**Branch:** `phase/2` (never `main`)
**Baseline commit:** `ad5359bced0149807f27c3116c44f5aa213b800f` (Stage 2.4, FROZEN)
**`main` untouched at:** `846a777438e1375331a7ce2821c9483ef5f77fc7`
**Final commit:** one clean Stage 2.5 commit on `phase/2`, message
`feat(accounting): complete Phase 2 Stage 2.5 realized FX` — exact SHA from
`git rev-parse HEAD` (reproduced in the review response; the report cannot
contain its own hash).
**Date of execution:** 2026-09-10 (UTC)
**Golden-suite raw output:** `docs/phase-reports/PHASE_2_STAGE_2.5_GOLDEN_OUTPUT.txt`
(21 printed blocks, captured on PostgreSQL)

Classification legend: `EXECUTED` = command actually run · `OBSERVED` = output read
from that run · `VERIFIED` = proven by artefact/inspection · `INFERRED` = reasoning,
not proven · `NOT EXECUTED` / `DEFERRED`.

---

## 1. Baseline verification (`EXECUTED` / `VERIFIED`)

```
$ git branch --show-current                 -> phase/2
$ git rev-parse HEAD                        -> ad5359bced0149807f27c3116c44f5aa213b800f
$ git rev-parse main                        -> 846a777438e1375331a7ce2821c9483ef5f77fc7
$ git diff --stat                           -> (empty)  tracked tree clean
$ git status --short                        -> ?? docs/phase-0/  (untracked by design)
                                               ?? docs/phase-reports/PHASE_2_STAGE_2.4_CLOSURE_EVIDENCE.md
```

Stages 2.1–2.4 verified present in code before any change: COA seeding (`coa.py`,
38 canonical accounts), journal currency contract + money engine (`services.py`,
`core/money.py`), posting integrity (`integrity_tests.py`, idempotency/audit/
reversal), balances and source trace (`balances.py`, `balance_tests.py`).

## 2. Final commit

Single commit on `phase/2` (see header). `git log -1 --format=%H` after the commit is
the authoritative value; it is reproduced in the review response and never
rewritten (`--amend` not used to chase a self-reference).

## 3. Branch

`phase/2` only. `main` untouched. No push (no credentials in this environment).

## 4. Scope

Implemented: the realized-FX accounting pattern (§1.10–§1.12) and the full §1.13
golden suite (16 scenarios) with printed evidence, plus the regression proofs
(§16–§18, §20, §23–§25).

Not implemented (documented, not silently skipped): unrealized/period-end FX
revaluation, cross-currency settlement, party subledgers/allocation, inventory
AVCO engine, any business module, any UI.

## 5. Files changed

| File | Change |
|---|---|
| `backend/accounting/fx.py` | **NEW** — realized-FX calculation + posting helper |
| `backend/accounting/fx_tests.py` | **NEW** — 69 tests (vectors, directions, validation, idempotency, rollback, reversal) |
| `backend/accounting/golden_tests.py` | **NEW** — 21 tests: 16 goldens + 4 regression blocks + historical-integrity |
| `docs/phase-reports/PHASE_2_STAGE_2.5_EVIDENCE.md` | **NEW** — this report |
| `docs/phase-reports/PHASE_2_STAGE_2.5_GOLDEN_OUTPUT.txt` | **NEW** — captured golden-suite printout (PostgreSQL) |

No migration was created: Stage 2.5 adds no schema. `makemigrations --check`
reports "No changes detected" on both backends.

## 6. Files intentionally unchanged

`models.py`, `services.py`, `coa.py`, `balances.py`, `core/money.py`,
`core/idempotency.py`, `core/dates.py`, `security/*`, migrations `0001`–`0006`,
and every Stage 2.1–2.4 test file. No frozen file was edited; §1 verification
shows a clean tracked tree at the start.

## 7. Implementation summary

`backend/accounting/fx.py` exposes two functions:

* `compute_realized_fx(...)` — pure: validates inputs, computes
  `carrying_value = Round(settled_amount × historical_rate, 2)`,
  `settlement_value = Round(settled_amount × settlement_rate, 2)`,
  `difference = |settlement_value − carrying_value|`, resolves the direction,
  validates/resolves the 8100/8200 account and returns the exact journal lines.
  Writes nothing.
* `post_realized_fx_settlement(...)` — posts that plan through the frozen
  `post_journal` (Stage 2.2/2.3): one balanced, audited, atomic, idempotent,
  immutable journal.

Reuse: `core.money` (`fx_equivalent`, `normalize_rate`, `format_rate`,
`quantize_half_up`, `to_decimal`), `post_journal`, `JournalValidationError`,
`reverse_journal`, `account_balance`, `trial_balance`, `journals_by_source`,
`trace_source`, `Account`, `Currency`, canonical 8100/8200. No second posting
engine, no second rounding rule, no second idempotency mechanism, no new
abstraction layer, no new account codes.

## 8. Realized FX accounting rules (implemented)

| Obligation | Settlement vs carrying | Result | Entry |
|---|---|---|---|
| Receivable | settlement > carrying | GAIN | Dr settlement asset (settlement value) / Cr obligation (carrying) / Cr 8100 (difference) |
| Receivable | settlement < carrying | LOSS | Dr settlement asset (settlement value) / Dr 8200 (difference) / Cr obligation (carrying) |
| Payable | settlement > carrying | LOSS | Dr obligation (carrying) / Dr 8200 (difference) / Cr settlement asset (settlement value) |
| Payable | settlement < carrying | GAIN | Dr obligation (carrying) / Cr settlement asset (settlement value) / Cr 8100 (difference) |
| Either | equal | NONE | two lines only — no 8100/8200 line (§13) |

All four directions are covered by executed tests with exact line assertions
(`FXDirectionTests`), and all four appear in the golden/trial-balance fixtures.

## 9. Currency behaviour

* `1 USD = X AFN`, `USD × Rate = AFN` (§1.11) — unchanged; rate direction stays
  explicit (`USD->AFN`, `AFN->AFN`).
* **The settlement journal is denominated in the base currency (AFN).** Its lines
  are AFN book values (Dr 7200 / Cr 7000 / Cr 200), which is what §6.1/§6.2 and the
  §28 output template demand. A USD-denominated journal could not hold those
  amounts: `post_journal` derives `afn_total = Round(total × rate, 2)`, so AFN line
  amounts under a USD journal would be multiplied by the rate a second time. With
  USD lines the golden amounts are also unreachable exactly (7000 ÷ 72 = 97.2222…,
  which 2-decimal line columns cannot hold without drift).
  Consequence — **the settlement rate is preserved in the journal's description and
  in every line's `reference` field, not in the `rate` column** (which necessarily
  holds `1.0000` for a base-currency journal). This is the one place where §10's
  wording ("settlement journal contains C") is satisfied by recorded context rather
  than by the `rate` column; the frozen single-currency journal cannot do both.
  **Flagged for the user's ruling.**
* **Cross-currency settlement is rejected** (`obligation_currency !=
  settlement_currency`) with `JournalValidationError` — no silent conversion, no
  hidden bridge journal, no new multi-currency model (§5).
* A base-currency obligation must use rate `1.0000` (same rule as `post_journal`);
  it therefore always produces the zero-FX case.

## 10. Money / rounding behaviour

`core.money` only: `fx_equivalent` = `Round(amount × rate, 2)` Half-Up; rates at 4dp
(`normalize_rate`); `float` inputs rejected with `TypeError` by the frozen money
contract. No binary float anywhere. Verified by vector G (70.1234 / 72.1234 →
7012.34 / 7212.34, difference exactly 200.00) and vector H (`2.675 → 2.68`,
`2.00005 → 2.0001` at 4dp).

## 11. §1.13 Golden Suite — 16/16 (`EXECUTED`, all PASS)

Full printed output: `PHASE_2_STAGE_2.5_GOLDEN_OUTPUT.txt`. Summary table:

| # | Scenario | Journal(s) | Result |
|---|---|---|---|
| 01 | Balanced journal | Dr 1110 / Cr 3100 5000.00 | PASS |
| 02 | Unbalanced rejection | none (rejected atomically) | PASS |
| 03 | Customer receivable | Dr 1310 / Cr 4110 1000.00 | PASS |
| 04 | Supplier payable | Dr 1410 / Cr 2110 2500.00 | PASS |
| 05 | Customer receipt | Dr 1110 / Cr 1310 1000.00 | PASS |
| 06 | Supplier payment | Dr 2110 / Cr 1110 2500.00 | PASS |
| 07 | Purchase | Dr 1410 / Cr 2110 4000.00 | PASS |
| 08 | Sale + COGS pair | JE-G08A 3000.00 + JE-G08B 1800.00 | PASS |
| 09 | COGS math | `cogs(3, 125.555) = 376.67` | PASS |
| 10 | Exchange-house movement | Dr 1210 / Cr 1110 6000.00 | PASS |
| 11 | FX gain | Dr 1110 7200 / Cr 1310 7000 / Cr 8100 200 | PASS |
| 12 | FX loss | Dr 1110 7000 / Dr 8200 200 / Cr 1310 7200 | PASS |
| 13 | Historical rate preservation | JE-G13A (rate 70) + JE-G13B (rate 72) | PASS |
| 14 | Duplicate posting prevention | 1 entry, 1 audit, reuse rejected | PASS |
| 15 | Atomic rollback | 0 rows after failure, retry succeeds | PASS |
| 16 | Source traceability | SALE / INV-G16 round-trip + after reversal | PASS |

Blocks R1–R5 (regressions: two trial-balance fixtures, two account-balance
fixtures, historical integrity) are in the same output file and all PASS.

Verbatim excerpt — GOLDEN 11 (PostgreSQL run):

```
GOLDEN 11 — FX GAIN
==================================================================

INPUT
  Historical                      100.00 USD @ 70.0000 AFN/USD
  Historical AFN                  7000.00
  Settlement                      100.00 USD @ 72.0000 AFN/USD
  Settlement AFN                  7200.00

EXPECTED
  FX Gain                         200.00
  Account                         8100 FX Gain
  8200 used                       no

JOURNAL JE-G11
  JOURNAL Number                  JE-G11
  Posting Date                    2026-03-01
  Currency                        AFN
  Rate Snapshot                   1.0000
  Rate Date                       2026-03-01
  Rate Direction                  AFN->AFN
  Status                          POSTED
  -- Debit Lines --
  Dr 1110 Cash in Hand            7200.00
  -- Credit Lines --
  Cr 1310 Trade Receivables       7000.00
  Cr 8100 Foreign Exchange Gain   200.00
  TOTAL DEBIT                     7200.00
  TOTAL CREDIT                    7200.00
  AFN EQUIVALENT                  7200.00

BALANCE
  1110 Cash                       7200.00
  1310 Receivable                 -7000.00
  8100 FX Gain                    200.00 (CREDIT)

RATE SNAPSHOT
  Historical rate (input)         70.0000
  Settlement rate                 72.0000
  Recorded in description         golden fx | Realized FX GAIN: 100.00 USD settled at 72.0000 (historical 70.0000) difference 200.00

SOURCE TRACE
  journals_by_source(FX, OBL-G11) ['JE-G11']

RECONCILIATION
  7200.00 == 7200.00              7200.00 == 7200.00
  Trial balance difference        0.00

STATUS
  Result                          PASS
```

## 12. FX gain vectors (`EXECUTED`)

| Vector | Inputs | Result |
|---|---|---|
| B — customer gain | 100 USD @70 → @72 | carrying 7000.00, settlement 7200.00, **gain 200.00**, Cr 8100 |
| E — supplier gain | 100 USD @72 → @70 | carrying 7200.00, settlement 7000.00, **gain 200.00**, Cr 8100 |
| F — partial | 100 USD obligation, 40 USD settled @70 → @72 | carrying 2800.00, settlement 2880.00, **gain 80.00** |
| G — precision | @70.1234 → @72.1234 | 7012.34 / 7212.34, **gain exactly 200.00** |

Asserted: 8200 never used in a gain; 8100 line equals the exact difference.

## 13. FX loss vectors (`EXECUTED`)

| Vector | Inputs | Result |
|---|---|---|
| C — customer loss | 100 USD @72 → @70 | carrying 7200.00, settlement 7000.00, **loss 200.00**, Dr 8200 |
| D — supplier loss | 100 USD @70 → @72 | carrying 7000.00, settlement 7200.00, **loss 200.00**, Dr 8200 |

Asserted: 8100 never used in a loss; 8200 line equals the exact difference.
The supplier-loss direction also runs inside the AFN trial-balance fixture (R2).

## 14. Historical-rate preservation proof (`EXECUTED` — GOLDEN 13 + tests)

1. Posted obligation `JE-G13A` in USD @70.0000 → `rate = 70.0000`, `afn_total = 7000.00`.
2. Created an `ExchangeRate` row moving the current rate to 75.0000.
3. Verified the obligation journal still has rate 70.0000, totals 100.00/100.00,
   `afn_total` 7000.00, direction `USD->AFN`, status POSTED — **unchanged**.
4. Settled at 72.0000 → settlement journal carries 72.0000 in its description/line
   references; FX difference computed from 70 vs 72 = 200.00.
5. Re-read the obligation: still 70.0000 / 7000.00.

`test_no_unrealized_restatement_of_open_balances` additionally proves that adding a
later rate (88.0000) leaves the open 1310 balance byte-identical — i.e. no
unrealized revaluation happens.

## 15. Zero-FX proof (`EXECUTED`)

Equal rates produce **no 8100 and no 8200 line at all** (2-line journal, balanced):
customer, supplier and base-currency variants are all asserted. A zero-value line
would in any case be impossible: the frozen `journal_line_one_sided_positive`
constraint requires one side strictly positive.

## 16. Partial-settlement proof (`EXECUTED`)

Obligation 100 USD, settlement 40 USD, 70 → 72: carrying 2800.00, settlement
2880.00, gain **80.00** (not 200.00), `unsettled_amount` 60.00 booked nowhere.
Asserted in `PartialSettlementTests` and vector F.

## 17. Invalid-input tests (`EXECUTED` — 25 cases, all fail safely)

zero/negative historical rate · zero/negative settlement rate · missing historical
rate · missing settlement rate · missing currency · inactive currency ·
cross-currency mismatch · negative/zero obligation amount · negative settlement
amount · settlement exceeding obligation · invalid obligation kind · invalid gain
account (1110) · swapped 8100/8200 · contra 4200 as gain account · inactive 2400 as
obligation / settlement / gain account · same account on both sides · unpersisted
account · non-Account argument · float amount (TypeError) · float rate (TypeError) ·
base-currency rate ≠ 1 · a deliberately unbalanced generated plan (rejected by
`post_journal`, nothing persisted).

Every rejection is asserted to leave the database byte-identical (entries, lines,
audits, idempotency records and numbering all unchanged).

## 18. Idempotency proof (`EXECUTED` — Stage 2.3 mechanism, unchanged)

A. first request succeeds · B. exact retry returns the **same** entry (1 entry,
2 lines, 1 POST audit, balance unchanged) · C. same key with a changed fingerprint
→ `JournalValidationError` ("already used for a different operation"), original
untouched · D. failure before commit leaves **no** reservation
(`IdempotencyRecord` count 0) · E. retry after failure with the same key succeeds ·
F. duplicate journal number with a fresh key raises the real `IntegrityError` and
does not poison the key · G. orphaned reservation raises `DuplicateOperationError`
instead of returning the wrong result. Golden 14 prints A–C.

## 19. Rollback proof (`EXECUTED` on both backends, `TransactionTestCase`)

Failure injected **after** the journal and lines are persisted (the audit writer
raises), on PostgreSQL as well as SQLite, using `TransactionTestCase` so a real
transaction — not `TestCase`'s outer wrapper — proves atomicity:

```
before == after: entries 0/0, lines 0/0, audits 0/0, idempotency 0/0,
sequences 0/0, balances 1110 = 0.00, 8100 = 0.00
then the same key retries cleanly -> 1 entry, 3 lines, afn_total 7200.00
```

A second test fails **before** persist and a third proves no numbering side effects.

## 20. Reversal proof (`EXECUTED`)

Posted a realized-FX journal, captured its complete state, reversed it: original
status → REVERSED with lines, rate snapshot, rate date, direction and AFN totals
byte-identical; reversal is balanced, mirrors debit/credit per line, links back via
`reverses`; the pair nets to zero (1110 = 0.00, 8100 = 0.00); exactly one POST and
one REVERSE audit; source trace still returns both documents.

## 21. Source-trace proof (`EXECUTED` — GOLDEN 16)

`journals_by_source("SALE", "INV-G16")` returns the journal · `trace_source()`
returns `entry_id / entry_number / entry_status / source_type / source_id /
resolved=False / document=None` · lines reachable (2) · balances include it · trial
balance includes it (difference 0.00) · after reversal both documents remain listed ·
no business document fabricated (`NumberSequence` rows = 1, only the reversal's own
JE number).

## 22. Trial-balance proof (`EXECUTED`)

Two currency-consistent fixtures (see limitation L3):

* **R1 — USD business fixture** (capital, sale, purchase, sales-return contra 4200,
  purchase-return contra 5200, a DRAFT entry, and a reversal):
  `Total debit = Total credit = 16850.00`, difference `0.00`; DRAFT excluded;
  4200 normal DEBIT and 5200 normal CREDIT unchanged.
* **R2 — AFN realized-FX fixture** (customer gain + supplier loss): total debit =
  total credit, difference `0.00`; 8100 classified CREDIT-normal (REVENUE) and 8200
  DEBIT-normal (EXPENSE), unchanged from the COA.

## 23. Account-balance proof (`EXECUTED`)

| Account | Balance | Normal |
|---|---|---|
| 1110 Cash in Hand | 15000.00 | DEBIT |
| 1210 Exchange House A | 5000.00 | DEBIT |
| 1310 Trade Receivables | 7000.00 | DEBIT |
| 1410 Main Warehouse | 2500.00 | DEBIT |
| 2110 Trade Payables | 4000.00 | CREDIT |
| 4110 Wholesale Sales | 7000.00 | CREDIT |
| 5100 COGS | 1500.00 | DEBIT |
| 8100 FX Gain | 200.00 | CREDIT |
| 8200 FX Loss | 0.00 (unused in the gain fixture) | DEBIT |
| 4100 Sales Revenue | 0.00 direct activity — non-posting group (limitation L2) | CREDIT |

Both global reconciliation (trial balance) and individual balances are proven.

## 24. Historical-integrity proof (`EXECUTED` — block R5)

Representative frozen state seeded first (a Stage 2.3 posted+reversed journal with
an idempotency key, and a Stage 2.2 legacy row with NULL currency), then a full
before/after snapshot of currencies, accounts (38 rows), journals, lines and audit
events. After running a Stage 2.5 FX settlement **and** its reversal:

```
COA unchanged                   True
Currencies unchanged            True
Existing journals unchanged     True
Existing lines unchanged        True
Existing audits unchanged       True
New journals                    2 (JE-HIST-FX + its reversal)
New lines                       6
New audits                      ['POST', 'REVERSE']
Frozen facts: 38 accounts · 2400 inactive · legacy row currency None ·
              legacy totals readable · source index present
```

## 25. SQLite test evidence (`EXECUTED`)

```
manage.py check  (config.settings.development)     System check identified no issues (0 silenced).
makemigrations --check --dry-run                   No changes detected
pytest -q                                          217 passed in 4.46s
pytest -q accounting/fx_tests.py accounting/golden_tests.py   90 passed in 1.73s
manage.py test                                     Ran 17 tests — OK
manage.py test --pattern="*_tests.py"              Ran 200 tests — OK
```

17 + 200 = 217: Django's default discovery pattern (`test*.py`) does not match this
project's `*_tests.py` convention, so both patterns together reproduce the pytest
total exactly. Stage 2.5 kept the frozen `*_tests.py` convention.

## 26. PostgreSQL test evidence (`EXECUTED`)

```
manage.py check      (config.settings.postgres)    System check identified no issues (0 silenced).
manage.py migrate --no-input                       No migrations to apply (0001–0006 already [X])
manage.py showmigrations accounting                0001..0006 all [X]
makemigrations --check --dry-run                   No changes detected
pytest -q --ds=config.settings.postgres            217 passed in 11.51s
pytest --ds=... accounting/fx_tests.py accounting/golden_tests.py   90 passed in 4.94s
manage.py test                                     Ran 17 tests — OK
manage.py test --pattern="*_tests.py"              Ran 200 tests in 10.076s — OK
```

Schema verified on PostgreSQL (`EXECUTED`): index `je_src_type_id_idx` present
(`USING btree (source_type, source_id)`); `journal_line_one_sided_positive` CHECK
present; `one_base_currency` present as a partial unique index
(`... USING btree (is_base) WHERE is_base`); unique `accounting_journalentry_number_key`
and `idempotency_key_key` present; the suite's own refusal path exercises
`one_base_currency` in the server log.

## 27. PostgreSQL version

```
PostgreSQL 17.11 (Debian 17.11-0+deb13u1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit
```

## 28. Migration evidence

No schema change: **no migration created**; `0001`–`0006` untouched;
`makemigrations --check` clean on both backends; forward migration state `[X]` for
0001–0006 on PostgreSQL (0006 re-verified applied).

## 29. Django check evidence

`manage.py check` → `System check identified no issues (0 silenced).` on
`config.settings.development` **and** `config.settings.postgres`.

## 30. pytest evidence

217 passed / 0 failed on SQLite and on PostgreSQL (127 frozen + 90 new: 69 FX +
21 golden/regression). No skips in the accounting core.

## 31. Frontend evidence

```
npm test         1..4 · tests 4 · pass 4 · fail 0
npm run build    ✓ 31 modules transformed · ✓ built in 276ms
```

(Frontend is out of scope and untouched; re-run because `node_modules` is not
preserved between sessions.)

## 32. Known limitations (actual, not hedges)

* **L1 — settlement rate lives in the journal text, not the `rate` column.** The
  settlement journal is base-currency (§9); its `rate` column necessarily holds
  `1.0000`. The settlement rate is preserved in the description and in every line's
  `reference`, and is returned by `compute_realized_fx`. Needs the user's ruling.
* **L2 — revenue is posted to 4110, not 4100.** In the frozen Stage 2.1 COA,
  `4100 Sales Revenue` is a non-posting group account (`is_posting=False`), so the
  brief's "Cr 4100" is unreachable without breaking a frozen contract. 4100 is
  verified as a group with zero direct activity; 4110 carries the revenue.
* **L3 — trial balance / account balances are proven on single-currency fixtures.**
  The frozen Stage 2.4 read layer refuses to merge currencies, so an FX scenario
  (USD obligation journal + AFN settlement journal) is reconciled at entry level
  (§14/§20) plus dedicated all-USD and all-AFN fixtures (§22/§23).
* **L4 — over-settlement is rejected.** `settlement_amount > obligation_amount` is
  refused; V1 has no overpayment/advance semantics (§2.9 belongs to a later phase).
* **L5 — gain/loss accounts are locked to the canonical 8100/8200.** Any other
  account (including 4200, which is also REVENUE-typed) is rejected.
* **L6 — environment.** PostgreSQL and the virtualenv live outside the workspace
  snapshot; they were reinstalled this session and will not survive a snapshot
  restore. Evidence above is from real execution, not simulation.

## 33. Deferred functionality

Unrealized / period-end FX revaluation (V2, §1.10) · cross-currency settlement
(later phase) · party subledgers, allocation and advances (Phase 5) · AVCO engine
(Phase 6) · purchase/sales/payment/return workflows (Phases 7–10) · exchange-house
and remittance ledgers (Phases 11–12) · printing and reporting · fiscal periods ·
master data · any UI.

Nothing in Stage 2.5 implements a business module: no Purchase, Sale, Customer,
Supplier or Exchange House object is created anywhere in the code.

## 34. Exact commands executed

```bash
# baseline
git branch --show-current ; git rev-parse HEAD ; git rev-parse main ; git status --short ; git diff --stat

# SQLite
DJANGO_SETTINGS_MODULE=config.settings.development python manage.py check
DJANGO_SETTINGS_MODULE=config.settings.development python manage.py makemigrations --check --dry-run
python -m pytest -q
python -m pytest -q accounting/fx_tests.py accounting/golden_tests.py
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py test
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py test --pattern="*_tests.py"

# PostgreSQL (server 17.11, database erp_afghanistan, role erp_afghanistan)
DJANGO_SETTINGS_MODULE=config.settings.postgres python manage.py check
DJANGO_SETTINGS_MODULE=config.settings.postgres python manage.py migrate --no-input
DJANGO_SETTINGS_MODULE=config.settings.postgres python manage.py showmigrations accounting
DJANGO_SETTINGS_MODULE=config.settings.postgres python manage.py makemigrations --check --dry-run
DJANGO_SETTINGS_MODULE=config.settings.postgres python -m pytest -q --ds=config.settings.postgres
python -m pytest -q --ds=config.settings.postgres accounting/fx_tests.py accounting/golden_tests.py
DJANGO_SETTINGS_MODULE=config.settings.postgres python manage.py test
DJANGO_SETTINGS_MODULE=config.settings.postgres python manage.py test --pattern="*_tests.py"
python -m pytest -s --ds=config.settings.postgres accounting/golden_tests.py \
    > docs/phase-reports/PHASE_2_STAGE_2.5_GOLDEN_OUTPUT.txt

# schema inspection
psql -h 127.0.0.1 -U erp_afghanistan -d erp_afghanistan -c "select version();"
psql ... -c "select indexname, indexdef from pg_indexes where tablename='accounting_journalentry';"
psql ... -c "select conname, pg_get_constraintdef(oid) from pg_constraint where conrelid::regclass::text in (...);"

# frontend
cd frontend && npm test && npm run build
```

## 35. Final status

| Item | Result |
|---|---|
| Baseline verified | PASS |
| No duplicate architecture | PASS |
| Realized FX helper | PASS (minimal, reuses the frozen engine) |
| Customer gain / loss | PASS |
| Supplier gain / loss | PASS |
| Historical rate snapshot preserved | PASS |
| Settlement rate recorded | PASS (text/context — limitation L1) |
| Zero-FX case | PASS |
| Partial settlement | PASS |
| Invalid FX inputs rejected | PASS (25 cases) |
| Golden suite | **16/16 PASS** (plus 5 regression blocks) |
| Idempotency | PASS |
| Atomic rollback | PASS (SQLite **and** PostgreSQL, real transactions) |
| Reversal compatibility | PASS |
| Audit integrity | PASS |
| Source traceability | PASS |
| Trial balance | PASS (difference 0.00) |
| Account balances | PASS |
| Historical integrity | PASS |
| SQLite regression | PASS (217 pytest / 200+17 Django) |
| PostgreSQL regression | PASS (217 pytest / 200+17 Django, v17.11) |
| Django checks | PASS |
| Frontend | PASS (4/4 tests, build OK) |
| `makemigrations --check` | PASS (no changes) |
| `main` untouched | PASS |
| Phase 3 work started | **No** |

**STATUS: IMPLEMENTED / TESTED / EVIDENCE READY — AWAITING USER REVIEW.**
Stage 2.5 is not APPROVED or FROZEN until the user says so.
