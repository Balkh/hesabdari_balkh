# Phase 11 — Goods in Transit Contract

**Status:** IMPLEMENTED / CI VERIFIED / FROZEN (2026-10-11)  
**Branch:** `phase/11-goods-in-transit`

## Core rule

Goods can be company-owned before physical Warehouse receipt.

- Supplier Advance is not ownership.
- Ownership transfer at Purchase may create **Owned In Transit**.
- Physical Warehouse identity remains `(Product, Warehouse)`.
- Transit is never represented as a fake Warehouse.
- Physical receipt reclassifies Transit to the destination Warehouse.
- Partial and multiple receipts are supported.
- Company-owned Transit goods may be sold before physical receipt.
- Payment does not determine ownership.
- Physical release does not create the Sale.
- Customer-owned goods may later enter company physical custody without becoming company-owned inventory.

## Accounting

When ownership is acquired before receipt:

```
Dr 1430 Goods in Transit
Cr 2110 Supplier Payable
```

When Transit is physically received:

```
Dr Warehouse Inventory
Cr 1430 Goods in Transit
```

Transit Sale COGS uses the original Purchase cost and reduces the Transit asset.

**1430 is a new posting account under 1400 Inventory and is introduced only by this approved Phase 11 branch.**

## Quantity invariant

For every Transit lot:

```
Original Owned Quantity
=
Remaining Transit
+
Received
+
Sold/Other Approved Disposition
```

Transit quantity and physical Warehouse stock are separate truths and must never double-count the same units.

## Integrity requirements

All Transit mutations are:

- atomic;
- idempotent;
- concurrency-safe;
- auditable;
- immutable after posting;
- reversible only through an explicit reversal path where the workflow supports reversal.

PostgreSQL row locking must protect quantity-sensitive operations.

## Current implementation boundary

Existing Purchase behavior remains unchanged for `IMMEDIATE` purchases.

A Purchase explicitly marked `IN_TRANSIT`:

1. posts the financial Purchase against 1430;
2. creates one immutable Transit lot per PurchaseLine;
3. creates no Warehouse StockMovement;
4. can later be received partially/multiply;
5. can be consumed by a SalesLine before receipt.

Sales from Transit use a dedicated immutable allocation and COGS journal; they do not fabricate Warehouse stock.

## Protected contracts

This phase does not change:

- Product + Warehouse physical stock identity;
- the existing inventory movement engine;
- AVCO engine;
- Supplier Advance semantics;
- Phase 10B settlement-rate semantics;
- posted-history immutability;
- reversal-only correction principle;
- Phase 8 PR #19.

## Verification and closeout — 2026-10-11

Phase 11 implementation fixes for Transit receipt, destination-transfer quantity integrity, physically returned Transit sales, and pre-delivery Warehouse Check cancellation have been merged into `main`:

- [PR #24 — fully sold Transit lot receipt lifecycle](https://github.com/Balkh/hesabdari_balkh/pull/24)
- [PR #25 — Transit destination transfer quantity](https://github.com/Balkh/hesabdari_balkh/pull/25)
- [PR #26 — returns of physically released Transit sales](https://github.com/Balkh/hesabdari_balkh/pull/26)
- [PR #27 — safe Warehouse Check cancellation reversals](https://github.com/Balkh/hesabdari_balkh/pull/27)

**Post-merge evidence:** [main CI run](https://github.com/Balkh/hesabdari_balkh/actions/runs/38160953156) completed successfully for Backend, PostgreSQL, Frontend, and Tauri at main commit `1bf105543a057d8c4380e01314ca6599abeda256`.

The cancellation decision is recorded in [PHASE_11_WAREHOUSE_CHECK_CANCELLATION_DECISION.md](PHASE_11_WAREHOUSE_CHECK_CANCELLATION_DECISION.md). Cancellation before physical delivery reverses the release authorization and restores customer-owned custody only; it does not cancel ownership or reverse the finalized Sale, revenue, original stock movement, or posted COGS. A post-delivery return remains an independent Sales Return.

This closeout freezes the Phase 11 Goods-in-Transit implementation contract. It does not resolve or override separate accounting-policy questions explicitly left open by the Phase 8 master contract.
