# Phase 11 — Goods in Transit Contract

**Status:** APPROVED FOR IMPLEMENTATION  
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
