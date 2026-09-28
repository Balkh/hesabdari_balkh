# Phase 8.1 — Sales Core Runtime Validation Evidence

**Mode:** Validation / test recovery only  
**Status:** Implemented, runtime-tested, regression-tested, evidence produced, waiting for user review  
**No APPROVED, VERIFIED, COMPLETE, GREEN, or FROZEN claim is made.**

## A. Exact baseline

```text
Branch: phase/4
HEAD before validation: 692e2735234e2d123625bc2dc9a2f15be9c0e564
HEAD message: freeze phase 7 purchase workflow
```

Working tree before validation contained the pre-existing changes plus the Phase 8.1 implementation:

```text
 M backend/config/settings/base.py
 M docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
?? backend/sales/__init__.py
?? backend/sales/apps.py
?? backend/sales/migrations/
?? backend/sales/models.py
?? backend/sales/sales_tests.py
?? backend/sales/services.py
?? docs/phase-reports/PHASE_8.1_SALES_CORE_IMPLEMENTATION_BLOCKED.md
?? docs/phase-reports/PHASE_8.1_SALES_CORE_IMPLEMENTATION_EVIDENCE.md
```

The pre-existing Purchase registration was preserved. The authorized settings diff is:

```diff
- "party_ledger", "inventory",
+ "party_ledger", "inventory", "purchases", "sales",
```

No unrelated tracked documentation was modified during validation. No reset, clean, discard, commit, push, or merge was performed.

## B. Environment

```text
Python: 3.13.14
Dependency source: repository root requirements.txt via backend/.venv
Django requirement: Django>=5.2,<6.0
Installed Django: 5.2.17
Test runner: pytest + pytest-django from repository requirements
```

The environment was prepared using the repository-declared dependencies only:

```text
python -m venv backend/.venv
backend/.venv/bin/python -m pip install -r requirements.txt
```

No dependency file was changed and no package upgrade was requested.

PostgreSQL check:

```text
POSTGRESQL UNAVAILABLE: connection refused at 127.0.0.1:5432
```

No PostgreSQL verification is claimed.

## C. Implementation state

Sales files:

```text
backend/sales/__init__.py
backend/sales/apps.py
backend/sales/models.py
backend/sales/services.py
backend/sales/sales_tests.py
backend/sales/migrations/__init__.py
backend/sales/migrations/0001_initial.py
```

Implemented within Phase 8.1:

- `Sale`;
- `SaleLine`;
- `AVAILABLE` and `FUTURE` Sale Types;
- `DRAFT` and `FINALIZED` commercial lifecycle;
- customer Party validation;
- Currency, exchange-rate, and rate-date validation;
- Product and primary Unit validation;
- required line-level Warehouse;
- quantity, unit price, discount, line totals, and Sale totals;
- fiscal-period validation on finalization;
- existing Audit service integration;
- existing `IdempotencyRecord` finalization boundary;
- instance and QuerySet finalized immutability;
- focused Sales tests.

Migration inspection:

```text
sales.0001_initial
  Create model Sale
  Create model SaleLine
  Create five SaleLine check constraints
```

Migration consistency command:

```text
cd backend
.venv/bin/python manage.py makemigrations --check --dry-run
```

Result:

```text
No changes detected
```

## D. Runtime checks

Django system check:

```text
cd backend
.venv/bin/python manage.py check
```

Result:

```text
System check identified no issues (0 silenced).
```

Migration plan included:

```text
purchases.0001_initial
sales.0001_initial
```

The focused pytest run created a fresh SQLite test database and applied the migration graph, including `sales.0001_initial`.

## E. Focused Sales tests

Final focused command:

```text
cd backend
.venv/bin/python -m pytest sales/sales_tests.py -q
```

Final result:

```text
12 passed in 1.37s
```

An initial focused run exposed one test expectation error: the test expected `450.00` after retaining a `5.00` line discount; the implementation correctly calculated `445.00`. The focused test expectation was corrected, then the focused suite was rerun successfully. No production behavior was broadened.

The focused suite covers:

- valid Draft creation;
- customer, Product, Unit, Warehouse, quantity, price, discount, currency, and FX validation;
- multiple lines and multiple Warehouses;
- same Product from different Warehouses;
- AVAILABLE finalization;
- FUTURE finalization;
- finalization idempotency;
- fiscal-period rejection;
- totals inconsistency rejection;
- finalized Sale and SaleLine mutation/deletion rejection through instance and QuerySet paths;
- draft updates and totals recalculation;
- no accounting or inventory side effects.

## F. Finalization tests

The focused tests establish:

```text
DRAFT → FINALIZED
```

for both Sale Types. Finalization validates the Sale and fiscal period, writes the existing audit convention, and uses the existing idempotency record convention.

No finalization path calls:

```text
post_journal()
receive_stock()
issue_stock()
```

No journal or downstream operational document is created.

## G. Immutability tests

The focused suite exercises finalized mutation rejection for:

- Sale customer;
- Sale status/total through QuerySet update;
- SaleLine quantity through instance save;
- SaleLine quantity through QuerySet update;
- Sale deletion through QuerySet delete;
- SaleLine deletion through QuerySet delete;
- draft-only update service after finalization.

The model and QuerySet guards reuse the existing `PostedImmutabilityError` convention rather than creating a second immutability framework.

## H. FUTURE Sale safety

The focused FUTURE test proves after finalization:

```text
StockMovement count unchanged
Product + Warehouse stock unchanged
AVCO unchanged
No custody model/event created
No release model/event created
No fulfillment allocation
No Payment
No JournalEntry
```

The Sales implementation contains no imports or calls to `post_journal()`, `receive_stock()`, or `issue_stock()`.

## I. Regression

Final post-implementation full backend command:

```text
cd backend
.venv/bin/python -m pytest -q
```

Final result:

```text
735 passed, 2 skipped in 84.79s (0:01:24)
```

The two skipped tests are PostgreSQL-specific concurrency tests. This is new post-implementation evidence and is not the earlier baseline result.

## J. PostgreSQL

```text
POSTGRESQL VERIFICATION: UNAVAILABLE
Reason: connection refused at 127.0.0.1:5432
```

SQLite runtime evidence and PostgreSQL evidence are kept separate. No PostgreSQL concurrency claim is made.

## K. Protected systems

The protected-path diff inspection returned no modified files under:

```text
backend/accounting/
backend/inventory/
backend/purchases/
backend/parties/
backend/party_ledger/
backend/products/
backend/warehouses/
backend/currencies/
backend/fiscal_periods/
```

The only non-Sales production code change is the authorized `sales` registration in:

```text
backend/config/settings/base.py
```

The implementation does not modify:

```text
Product + Warehouse identity
StockMovement
AVCO
receive_stock()
issue_stock()
Purchase behavior
Party architecture
PartyLedgerAttribution
JournalEntry
JournalLine
post_journal()
Money/Currency engines
Fiscal Period engine
existing returns
```

The pre-existing `purchases` registration discrepancy remains preserved and was not repaired.

## L. Scope audit and remaining blockers

The implementation contains only the authorized commercial Sales Core. It does not implement:

```text
Payment
Sales Return
Revenue posting
COGS
Inventory-reduction accounting
Custody accounting
Fulfillment allocation
Warehouse Release Authorization
Physical release
Frontend
Printing
Reporting
```

Remaining limitations/blockers:

1. PostgreSQL verification is unavailable in this environment.
2. The two PostgreSQL-dependent regression tests remain skipped.
3. Financial Sales decisions remain intentionally unresolved: `4110`/`4120`, revenue timing, COGS timing, inventory reduction, custody accounting, Type B accounting, cancellation accounting, and Sales Return accounting.
4. The pre-existing Phase 7 Purchase registration discrepancy remains documented and unchanged.
5. GitHub baseline verification remains unavailable because no usable remote is configured.

## Final status

```text
IMPLEMENTED
RUNTIME TESTED
REGRESSION TESTED
EVIDENCE PRODUCED
WAITING FOR USER REVIEW
```

No approval, verification, completion, green, or frozen status is claimed.
