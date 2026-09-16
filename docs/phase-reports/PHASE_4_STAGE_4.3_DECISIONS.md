# Phase 4.3 — Architecture Discovery Record (NO IMPLEMENTATION)

**Date (UTC):** 2026-09-15
**Branch:** `phase/4` @ `3362748986ea87887a595cc132e87508b1180da6` (clean)
**Status:** APPROVED by user 2026-09-15 — OD-1 NO CODE, OD-2 NON-UNIQUE,
OD-3 OMIT ADDRESS (see §L). Discovery-stage verdict BLOCKED is lifted by
this explicit implementation order. Implementation authorized.
**Method:** every claim cites contract section + line, or repo path + line.

---

## A. BASELINE (from repo, never memory)

```text
Branch:        phase/4
HEAD:          3362748 (4.2 closure and freeze)
4.1 frozen:    60dfaf7 (closure) — code 3602b07 + 5ef2e36
4.2 frozen:    3362748 (closure) — code b2f1995 + 6b47ff9
Phase 3:       a43725e (3.2) / 2a52ae7 (3.1) closures, in-history
Phase 2:       merged via PR #2 47d1cb8 (origin/phase/2 @ 6e31916)
main:          646e35e == origin/main (unchanged)
Working tree:  clean
```

## B. CONTRACT FINDINGS (C = mandatory rule, X = contextual)

| # | Finding | Source | Class |
|---|---|---|---|
| W1 | Warehouse master spec = ONE line: "Each warehouse has independent stock." (a Phase-6 rule, zero master fields) | §4.4 L954–956 | C (for Ph6) |
| W2 | "Main/Secondary Warehouse" = 1410/1420 POSTING ACCOUNT names, not warehouse types | L260–261 (§1.6) | X |
| W3 | Kardex keyed "Per Product + Warehouse" → stock identity = (product, warehouse) | §4.15 L1103 | C (for Ph6) |
| W4 | Transfer In/Out movement legs; "Transfers do not create revenue or expense" → transfer is a two-ended quantity move | L1086–1097 | C (for Ph6) |
| W5 | Documents reference Warehouse: PI fields §5.3 L1187; workflows §5.1/§6.1/§8.2; doc types Warehouse Receipt/Issue + Stock Transfer L1983–1986 | L1153, L1187, L1282, L1566, L1983–1986 | C (for Ph5–8) |
| W6 | Reports slice by Warehouse; "Warehouse stock (on Date X)" | L2221, L2236, L2246, L2315, L2494 | X (Ph11) |
| W7 | Roadmap: Phase 4 "Warehouses" L3144; Phase 6 "Warehouse balances" L3165. (Phase 11 "Transfers" L3219 = CASH transfers — different concept) | L3144, L3165, L3219 | X |
| W8 | ZERO occurrences: godown, store, location/bin/shelf/zone/rack, transit/main/default/keeper warehouse, warehouse code, warehouse address/contact, "inactive warehouse" | full-text negative | — |
| W9 | "Inactive" exists for: product §4.1 L930, supplier L1264, product L1265, generic entities L1392, party L1542 — never warehouse | listed lines | X |

## C. REPOSITORY FINDINGS

| # | Finding | Source |
|---|---|---|
| R1 | `backend/inventory/` = `.gitkeep` only, not installed | path |
| R2 | Warehouse in code = ONLY COA 1410/1420 posting accounts (+tests); Dari `گدام اصلی/فرعی` already used as PRESENTATION names | `coa.py:39-40` |
| R3 | Uniform master shape (Category/UOM/Party): `name` req + `name_fa` opt + `is_active` T + `created_at` + `ordering[name,id]` + blank-guard check; NO `updated_at` on any master; names NON-unique everywhere (6 precedents incl. Account/FiscalPeriod) | `categories/models.py:12-22`, `uom/models.py:12-22`, `parties/models.py:19-40` |
| R4 | Uniform service shape: `XxxValidationError`, strip+type guards, `record_audit_event` CREATE/UPDATE, idempotent no-op (no audit when unchanged), NO delete path, NO codes where contract silent (4.1 U-2/U-3, 4.2 FR-4) | `categories/services.py:82,120`, `parties/services.py:107,162`, `products/services.py:295` |
| R5 | No warehouse FK/source reference anywhere; no hierarchy infra; `NumberSequence` document-scoped (established 4.1 R-6) | repo-wide negative |
| R6 | Zero API requirements in contract (4.1-discovery proven, unchanged) → 4.1 R-10 / 4.2 domain-only precedent stands | — |

## D. PHASE 6 REQUIREMENTS (confirmed vs inferred)

Confirmed (contract): stock identity (product, warehouse) [W3]; In/Out
movement legs incl. Transfer In/Out with no revenue/expense [W4];
documents + reports reference Warehouse as a dimension [W5/W6].
Inferred (compatibility need, NOT contract): movements will FK two
warehouse ends for transfers; deactivation likely means "not selectable
for NEW operations" while history stays readable.
Unresolved: nothing blocking — all satisfied by a stable PK identity.

## E. ARCHITECTURE OPTIONS (genuine ambiguities only)

**E1 Location model.** A: flat master. B: zone/rack/shelf/bin hierarchy
(DEAD: W8 zero evidence + anti-over-engineering rule). C: flat now, add
location table later IF ever required (collapses to A + a note: a future
location table FKs Warehouse — additive, no redesign). → Recommend A.
**E2 Business code.** A: none. B: manual unique. C: auto (DEAD: R5
NumberSequence is document-scoped; no auto infra for masters). A rests on
3 user precedents (U-2/U-3/FR-4) + PK suffices for W3 keying; B rests on
human-lookup convenience (documents show a warehouse, W5). → OPEN (OD-1).
**E3 Name uniqueness.** Non-unique (6 precedents, R3) vs UNIQUE (permanent
rule from silence). Duplicate godown names ("Main Godown" per branch) are
plausible in Afghan usage. → OPEN (OD-2), recommend non-unique.
**E4 Address/location field.** Omit (Category/UOM have no such field) vs
free-text address (inert, plausible need — but pure speculation).
→ OPEN (OD-3), recommend omit.
Decided-omit (zero evidence either side would be invention; reviewable):
warehouse type flags, is_default, Party FK, Product/UOM FKs, financial/
inventory fields, API/UI. Decided-include (overwhelming convention):
`name` req, `name_fa` opt (FR-5 principle), `is_active` T, `created_at`,
blank-guard check, `record_audit_event` CREATE/UPDATE, no-op rule,
no-delete-path + future PROTECT, rename-safe PK identity.

## F. QUANTITATIVE MATRIX (1 weak – 5 strong; high simplicity = simpler)

| Decision | Option | Contract | Repo | Phase 6 | Integrity | Simplicity | Total | Rec |
|---|---|---|---|---|---|---|---|---|
| Location | A flat | 5 (W8: nothing required) | 5 (R3 flat everywhere) | 5 (W3 needs PK only) | 5 | 5 | 25 | ✅ |
| Location | B hierarchy | 1 (zero evidence) | 1 (no precedent) | 2 (unused depth) | 3 | 1 | 8 | ❌ |
| Code | A none | 4 (silent; U-2/U-3/FR-4 principle) | 5 (3 precedents) | 5 (PK keying) | 4 | 5 | 23 | ✅* |
| Code | B manual unique | 1 (invents permanent rule) | 2 (only Product-code, contract-driven) | 4 (human key) | 4 | 3 | 14 | * |
| Name uniq | A non-unique | 4 (silent everywhere) | 5 (6 precedents) | 5 (PK keying) | 4 | 5 | 23 | ✅* |
| Name uniq | B unique | 1 (invention) | 1 (zero precedent) | 3 | 3 | 3 | 11 | * |
| Address | A omit | 4 (silent) | 4 (Cat/UOM lack it) | 5 (irrelevant) | 5 | 5 | 23 | ✅* |
| Address | B free-text | 2 (speculative need) | 3 (Party trio exists) | 5 (ignorable) | 5 | 4 | 19 | * |
| Type/default | omit | 5 (W2 refutes type reading) | 5 | 5 | 5 | 5 | 25 | ✅ |

`*` = recommended but OPEN for user ruling (permanent/structural class).

## G. PROPOSED MODEL (conceptual only — nothing created)

```text
Warehouse
---------
id            PK (identity; rename-safe)
name          required, trimmed, non-blank (DB check)
name_fa       optional (FR-5 principle)
code          ? OD-1 (recommend: none)
name unique   ? OD-2 (recommend: non-unique)
address       ? OD-3 (recommend: omit)
is_active     default True (selection semantics; history preserved)
created_at    UTC (no updated_at — master convention)
```

App would be `warehouses` (plural convention) + `Warehouse` model
(contract uses ONLY "Warehouse", 22 hits; godown/store 0 — Dari stays
presentation, cf. R2). Migration 0001, no dependencies (no FKs).

## H. EXPLICIT OUT-OF-SCOPE

Inventory/stock/ledger/movement/AVCO/FIFO/COGS/batch/lot/serial/
reservation/transfer engine; purchase/sales/returns; balances/receivable/
payable/opening; journals/posting/accounts mapping; cash/exchange;
invoices/payments; reporting/printing/CRM/tax; location hierarchy;
type/default flags; Party/Product/UOM FKs; API/serializers/views/URLs;
frontend; admin; new engines of any kind.

## I. OPEN DECISIONS (user MUST rule — §32/§40 class)

- **OD-1. Business code?** Recommend NONE (3 precedents + PK suffices).
  Alternative: manual unique code (human-lookup convenience).
- **OD-2. Name uniqueness?** Recommend NON-UNIQUE (6 precedents).
  Alternative: UNIQUE constraint (permanent rule from silence).
- **OD-3. Address/location free-text field?** Recommend OMIT (strict
  minimal, Cat/UOM precedent). Alternative: optional inert text.

## J. PROPOSED G43 TEST MATRIX (after approval)

Identity (valid/blank/whitespace/fa/duplicates-per-OD-2/code-per-OD-1);
status (default/deactivate/reactivate); update (valid/no-op/rename-keeps-
identity); audit (CREATE/UPDATE/no-op-silence); DB (checks/migration
fwd-rev/PG+SQLite); scope (no Product/UOM/Party FK, no inventory/
financial fields — incl. negative `hasattr` pins); golden G43-01..~08
freezing: creation, optionals, uniqueness-per-ruling, active semantics,
audit, atomic rollback, future-compat shape.

## K. PHASE 6 COMPATIBILITY TEST (conceptual — PASS)

- `Product X in Warehouse A` + `Product X in Warehouse B` = two
  (product_id, warehouse_id) stock rows (W3) — no warehouse change.
- `Warehouse A → Transfer → Warehouse B` = OUT leg (A) + IN leg (B)
  referencing two PKs (W4) — no warehouse change.
Code-or-not does not affect keying (PK either way).
Deactivation = "not selectable for new ops" + history readable (inferred
need; enforcement belongs to Phase 6+, not 4.3).

## L. USER RULINGS — 2026-09-15 (implementation order)

OD-1 NO BUSINESS CODE: no `code`, no manual/auto code, no NumberSequence;
the PK is the identity (§8/§13 honored; convenience never justifies an
identifier). OD-2 NON-UNIQUE: no `unique=True`, no UniqueConstraint on
name in any form (incl. case-insensitive/normalized); duplicates allowed.
OD-3 OMIT ADDRESS: no address/location/street/city/province/coordinates
in any form; a future physical-location concept needs its own approved
architectural decision. Final approved model: id + name(req) + name_fa
(opt) + is_active(T) + created_at — no updated_at, type, default,
hierarchy, relations, financial/inventory fields (§10–§15 verbatim).

## SCOPE STATEMENT

ONE uncommitted docs file added. Models/migrations/services/tests/API/
frontend/app: ZERO created. Frozen phases + 4.1 + 4.2 + CI + deps: ZERO
touched. No commit made.
