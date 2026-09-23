# Phase 8.1 — Sales Core Implementation Evidence

## Status

```text
IMPLEMENTATION NOT STARTED
BLOCKED BEFORE CODE CHANGES
WAITING FOR USER DECISION
```

## Baseline inspection

```text
Branch: phase/4
HEAD:   692e2735234e2d123625bc2dc9a2f15be9c0e564
HEAD:   freeze phase 7 purchase workflow
```

Working-tree status at inspection:

```text
 M backend/config/settings/base.py
 M docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_8_FINAL_CONTRACT_LOCK.md
?? docs/phase-reports/PHASE_8_FINAL_SALES_CONTRACT_RESOLUTION.md
?? docs/phase-reports/PHASE_8_SALES_CONTRACT_RESOLUTION_CUSTODY_DISCOVERY.md
?? docs/phase-reports/PHASE_8_SALES_CONTRACT_RESOLUTION_REPORT.md
```

The existing tracked settings diff is:

```diff
- "party_ledger", "inventory",
+ "party_ledger", "inventory", "purchases",
```

No usable Git remote is configured. GitHub baseline verification is unavailable.

## Blocking conflict

The requested Phase 8.1 requires a Django Sales application containing models, migrations, tests, and domain services. The repository currently contains only:

```text
backend/sales/.gitkeep
```

The current `INSTALLED_APPS` contains `purchases` only through the pre-existing working-tree change. It does not contain `sales`:

```text
..., "party_ledger", "inventory", "purchases",
```

The committed HEAD contains neither the `purchases` registration nor a `sales` registration.

A registered Django application is required for the approved Sales Core to be safely represented through the repository's existing model/migration/test conventions. Adding `sales` to `INSTALLED_APPS` would modify `backend/config/settings/base.py`, but the implementation prompt explicitly prohibits settings modification:

```text
DO NOT modify settings.
```

The prompt also requires stopping when a necessary dependency is missing rather than implementing around it.

Therefore implementation cannot safely begin without violating one of the explicit instructions.

## Decision required

Please explicitly choose one of these contract-consistent paths:

1. **Authorize the minimal settings change** to register the new `sales` application, while preserving the pre-existing `purchases` working-tree change; or
2. **Provide an existing approved mechanism** by which Sales models/migrations may be installed and tested without changing settings; or
3. **Keep Phase 8.1 blocked** until the settings/baseline contract is resolved.

No choice was made silently.

## Protected-systems verification

No production code was changed. Consequently:

```text
Product + Warehouse: unchanged
StockMovement: unchanged
AVCO: unchanged
receive_stock(): unchanged
issue_stock(): unchanged
Purchase: unchanged
Accounting core: unchanged
Tests: unchanged
Migrations: unchanged
Dependencies: unchanged
```

The earlier SQLite baseline remains the only recorded test result:

```text
723 passed, 2 skipped in 77.50s
```

The skipped tests were PostgreSQL-specific. No new Phase 8.1 tests were run or created. PostgreSQL verification remains unavailable.

## Implementation gate

```text
IMPLEMENTATION PERFORMED: NO
CODE MODIFIED: NO
TESTS MODIFIED: NO
MIGRATIONS CREATED: NO
ACCOUNTING MODIFIED: NO
INVENTORY MODIFIED: NO
PURCHASE MODIFIED: NO
SETTINGS MODIFIED: NO
DEPENDENCIES MODIFIED: NO
COMMIT CREATED: NO
PUSH PERFORMED: NO

STATUS:
PHASE 8.1 IMPLEMENTATION BLOCKED BEFORE CODE CHANGES
WAITING FOR EXPLICIT USER DECISION ON SALES APP REGISTRATION / SETTINGS GATE
```
