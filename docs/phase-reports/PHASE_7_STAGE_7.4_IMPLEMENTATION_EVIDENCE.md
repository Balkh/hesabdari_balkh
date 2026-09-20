# Phase 7.4 — Purchase Correction, Reversal & Historical Integrity Evidence

## Status

**IMPLEMENTED / PARTIALLY TESTED**.

Stage 7.4 strengthened and tested the posted-history protection boundary. No
Purchase reversal architecture was invented because the repository does not contain
an authoritative coherent reversal primitive for the complete Purchase event.

SQLite evidence was executed. PostgreSQL remains **BLOCKED / NOT TESTED** because no
server is reachable at `127.0.0.1:5432`.

Stage 7.4 is not frozen. Phase 7 is not frozen. Stage 7.5 was not started.

## Starting baseline

- Branch: `phase/4`
- Starting HEAD: `c521fb4b6194330142c77bcefd9e9d9795f601d9`
- Stage 7.1, 7.2, and 7.3 implementations/evidence were uncommitted working-tree
  changes.
- All existing Purchase and Phase 6 changes were preserved.

## Inspection findings

The repository does contain the generic accounting primitive:

```text
accounting.services.reverse_journal()
```

It creates a compensating JournalEntry and preserves the original journal through
its `reverses` relationship. It does not reverse a complete Purchase event:

- it does not create a compensating Purchase state/event;
- it does not create a compensating `PURCHASE_RECEIPT` inventory movement;
- it does not coordinate PurchaseLine history;
- it does not coordinate Purchase-specific supplier attribution;
- it does not provide a Purchase-level idempotency/atomicity contract;
- it does not preserve a complete Purchase → inventory → accounting correction chain.

Existing `receive_stock()` is a receipt primitive, not a Purchase reversal primitive.
Existing Purchase Return is a separate business inventory return workflow and is not a
substitute for correcting an erroneous Purchase document.

Therefore no suitable authoritative Purchase reversal/correction mechanism exists.

## Contract decision

Stage 7.4 deliberately takes **Outcome B**:

- preserve immutable posted Purchase history;
- prove that the original Purchase, PurchaseLine, receipt movement, journal,
  journal lines, and supplier attribution cannot be rewritten or deleted;
- defer a complete Purchase correction/reversal workflow.

A future correction workflow requires an explicit cross-module contract defining the
compensating Purchase event, inventory movement, accounting reversal, supplier
attribution, date/fiscal-period behavior, currency/rate behavior, idempotency, and
audit relationship. That contract is not currently established. No speculative
reversal system was introduced.

## Implementation changes

Only focused regression coverage was added:

- `backend/purchases/purchase_tests.py`
  - added a comprehensive historical immutability test covering Purchase,
    PurchaseLine, original `PURCHASE_RECEIPT` StockMovement, JournalEntry,
    JournalLine, and PartyLedgerAttribution;
  - verifies failed mutation/deletion attempts leave every original value unchanged.
- `docs/phase-reports/PHASE_7_STAGE_7.4_IMPLEMENTATION_EVIDENCE.md`
  - this report.

No production code, models, migrations, accounting code, inventory code, Party
Ledger code, fiscal-period code, or Phase 6 code was changed.

## Historical immutability evidence

The new focused test attempts to modify or delete:

- posted Purchase supplier and Purchase itself;
- posted PurchaseLine quantity and PurchaseLine itself;
- original receipt movement cost and movement itself;
- original JournalEntry description and JournalEntry itself;
- original JournalLine credit and JournalLine itself;
- original PartyLedgerAttribution party and attribution itself.

Each operation is rejected by the existing immutability protections. The test then
refreshes all records and verifies the original supplier, quantity, cost, journal
text, debit/credit value, and Party attribution remain unchanged.

No in-place correction or undo shortcut exists.

## Accounting evidence

The original Purchase journal remains protected by the existing accounting model
immutability rules. The generic `reverse_journal()` primitive was inspected but not
integrated because it cannot reverse the complete Purchase business event atomically.

No accounting mapping, COA account, journal engine, or reversal engine was changed.

## Inventory evidence

The original `PURCHASE_RECEIPT` StockMovement remains protected by the existing
StockMovement immutability rules. No receipt movement is edited or deleted by Stage
7.4. The existing Purchase Return and inventory correction primitives were not
redesigned or used as a hidden Purchase correction mechanism.

Stock truth remains:

```text
SUM(StockMovement.quantity) per Product + Warehouse
```

## Party-ledger evidence

The original supplier `PartyLedgerAttribution` remains protected by the existing
immutable attribution model. No supplier ledger or Purchase-specific payable ledger
was introduced.

## Currency evidence

No correction event was implemented, so no new currency/rate behavior was added.
Existing Purchase historical currency, exchange rate, rate date, and receipt cost
snapshots remain unchanged and are covered by the existing Stage 7.1/7.3 tests.

A future Purchase reversal must define its historical FX/date behavior before
implementation.

## Atomicity evidence

No new correction transaction was introduced. Existing Purchase posting atomicity
and late-failure rollback remain covered by the Stage 7.1/7.2 test suite.

A complete Purchase correction atomicity test is deferred with the correction
workflow itself.

## Idempotency evidence

No new correction operation or idempotency mechanism was introduced. Existing
Purchase posting idempotency remains covered by the prior focused tests.

A correction-specific idempotency contract is deferred until the correction event
contract is approved.

## Audit evidence

Existing Purchase creation/posting and effect-reference audit behavior remains
unchanged. No PurchaseAudit model or second audit system was created.

A correction-specific audit relationship is deferred with the correction workflow.

## Fiscal-period evidence

The existing Purchase closed-period rejection test remains in the focused suite and
continues to use `assert_posting_date_open()`.

No correction date or fiscal-period semantics were invented. A future correction
workflow must define those semantics before implementation.

## Focused tests

Command:

```text
pytest -q purchases/purchase_tests.py
```

Actual result:

```text
13 passed in 1.24s
```

## Full regression

Command:

```text
pytest -q
```

Actual result:

```text
710 passed, 2 skipped in 87.24s (0:01:27)
```

The two skipped tests are the existing PostgreSQL-specific Phase 6 concurrency
regressions. They are not PostgreSQL evidence.

## Django and migration checks

```text
python manage.py check --settings=config.settings.test
System check identified no issues (0 silenced).

python manage.py makemigrations --check --dry-run --settings=config.settings.test
No changes detected
```

`git diff --check` completed without errors.

## PostgreSQL

```text
PostgreSQL: BLOCKED / NOT TESTED
```

No PostgreSQL tests were executed because PostgreSQL remains unavailable at
`127.0.0.1:5432`.

## Phase 6 concurrency debt

The existing Phase 6 debt remains unchanged:

```text
python manage.py test inventory.inventory_tests.Stage6ConcurrencyTests --verbosity 2
```

The PostgreSQL-specific concurrency tests must execute against a real PostgreSQL
server before that debt can be closed.

## Protected surfaces

Unchanged:

- Phase 2 accounting core, COA, money, balances, posting integrity, and FX;
- Phase 3 fiscal-period implementation;
- Phase 4 Product, Party, Warehouse, Cash Account, and Exchange House systems;
- Phase 5 PartyLedgerAttribution architecture;
- Phase 6 StockMovement, AVCO, returns, dispatch, adjustments, and concurrency
  locking;
- Stage 7.1–7.3 production behavior.

No payments, settlements, tax, sales, general reversal engine, new ledger, new GL,
new AVCO engine, new audit system, new idempotency system, or Stage 7.5 work was
introduced.

## Working tree at evidence capture

```text
 M backend/config/settings/base.py
 M docs/phase-reports/PHASE_6_STAGE_6.6_IMPLEMENTATION_EVIDENCE.md
?? backend/purchases/
?? docs/phase-reports/PHASE_7_STAGE_7.1_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.2_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.3_IMPLEMENTATION_EVIDENCE.md
?? docs/phase-reports/PHASE_7_STAGE_7.4_IMPLEMENTATION_EVIDENCE.md
```

## Commit and freeze status

```text
No commit created.
No merge performed.
No freeze performed.
```

Stage 7.4 implementation/evidence is complete for this increment. Waiting for USER
REVIEW. Stage 7.5 was not started.
