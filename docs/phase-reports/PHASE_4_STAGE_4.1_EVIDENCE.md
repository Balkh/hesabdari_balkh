# Phase 4 — Stage 4.1 Evidence: Category + UOM + Product Master

**Date (UTC):** 2026-09-14T19:14Z
**Branch:** `phase/4` (local-only; from frozen `a43725e`; `origin/main`
unchanged @ `646e35e`)
**Commits:**
- `f007b50` — docs(decisions): interpretation record (BEFORE any code)
- `3602b07a1b3e5191384abc56c459187842819027` — feat: 3 apps + 65 unit tests
  (22 files, +1466/−1; the −1 is the INSTALLED_APPS line edit)
- `5ef2e36c172bca5d7db79118b677cec16cff4c15` — test: golden G41-01..10 (+192)
- (this doc + golden output → docs commit, below)

**Verdict: IMPLEMENTED per approved rulings — awaiting user review. NOT
approved, NOT frozen, NOT merged.**

---

## Repository

- HEAD at evidence time: `5ef2e36`; parent chain → `3602b07` → `f007b50`
  → `a43725e` (3.2 freeze).
- Working tree: clean except the two new docs files (committed in C3).
- Interpretation record `PHASE_4_STAGE_4.1_DECISIONS.md` was committed
  (C0) BEFORE any model/migration existed, per user order.

## Scope (exact)

Changed/added: `backend/categories/`, `backend/uom/`, `backend/products/`
(models + services + 0001_initial migrations + `*_tests.py` + golden) and
one line in `backend/config/settings/base.py` (INSTALLED_APPS).
Intentionally untouched: every frozen Phase 1/2/3 file, all existing
migrations, frontend (zero diff), CI/scripts, requirements.
Why each file was necessary: three masters × (identity model + validated
service + audit) + deterministic migrations + contract-pinning tests.
No serializers/views/urls: domain-only per R-10 (contract has zero API
requirements; §13 smallest-boundary rule).

## Contract

Implemented from `PHASE_0_CONTRACT_V2.1.md`: §4.1 (all 15 product bullets
mapped: code unique; EN+FA names; category; primary/secondary UOM; factor;
barcode/brand optional; two reference prices; min/max/reorder; active flag;
description), §4.2 (references are suggestions — stored only, zero pricing
behavior), §3.11 (4dp price/factor storage), §3.12 (Half-Up via the ONE
money engine — applied at service level so SQLite matches PG NUMERIC),
§3.13 (examples reused in tests; direction convention recorded, never
applied), §13.4 (CREATE/UPDATE audit via existing writer).
Ambiguities: none unresolved — all 12 gaps have recorded (U)/(R) rulings
in the decisions doc, including explicit NON-decisions (R-4) pinned by
tests (duplicate names, max<min, negative suggestion price, secondary ==
primary all demonstrably allowed).

## Tests (executed)

```text
SQLite:
pytest -q                                    401 passed (326 frozen + 75 new)
manage.py test                               Ran 17 — OK
manage.py test --pattern="*_tests.py"        Ran 384 — OK (309 + 75)
manage.py check                              0 issues
makemigrations --check                       No changes detected
migrations zero→0001→zero (3 new apps)       OK forward + reverse

PostgreSQL 17.10 (real server):
pytest -q --ds=config.settings.postgres      401 passed
manage.py test                               Ran 17 — OK
manage.py test --pattern="*_tests.py"        Ran 384 — OK
manage.py check                              0 issues
migrations zero→0001→zero (3 new apps)       OK forward + reverse
```

New suites: `category_tests` 17, `uom_tests` 17, `product_tests` 31,
`golden_tests` 10 → 75 total, all green first full run except two
test-authoring savepoint fixes (IntegrityError inside TestCase atomic —
implementation was correct).

## Golden

```text
G41-01 PASS   G41-02 PASS   G41-03 PASS   G41-04 PASS   G41-05 PASS
G41-06 PASS   G41-07 PASS   G41-08 PASS   G41-09 PASS   G41-10 PASS
10 PASS, 0 FAIL — trail: PHASE_4_STAGE_4.1_GOLDEN_OUTPUT.txt (39 lines)
```

## Regression

Phase 1–3 suites all green inside the 401/384 totals (326 pytest + 17 + 309
Django counts match frozen numbers exactly — zero frozen tests touched,
zero broken). Frontend untouched (no new work manufactured).

## Diff integrity

`git status` at C2: clean. Frozen files: zero modifications (verified —
only the 22 new paths + 1 settings line exist in C1/C2).

## Scope integrity

No forbidden module touched (§28): no purchase/sales/payment/returns/
inventory/ledger/COGS/AVCO/reports/printing/numbering/auth changes; no new
accounting/currency/date/audit/numbering engines; no UI; no dependency
changes. PROTECT (not cascade) guards all master relations.

**STOP — awaiting explicit user review/approval. No freeze, no merge, no 4.2.**
