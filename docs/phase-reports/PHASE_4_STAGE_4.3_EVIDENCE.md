# Phase 4.3 — Implementation Evidence (IMPLEMENTED → TESTED → recorded)

**Date (UTC):** 2026-09-15T19:44Z
**Branch:** `phase/4` — base `3362748` (4.2 frozen) — tree clean
**Chain:** `f8666c4`(C2 golden) → `9cdc0ce`(C1 feat) → `85368bb`(D0 rulings)
→ `3362748`. Full SHAs: f8666c40db190a2094d6aac1fe8b175253273af1,
9cdc0ce7d53a52f52b3145a02d07961150e9d25c,
85368bb2e9b1eee56e0dc1663ccc0a5396f8dbeb.
**Remote CI:** NOT RUN (separate gate; no claim made).

## Implementation

App `backend/warehouses/` (plural convention; `Warehouse` model — contract
uses only "Warehouse", 22 hits; godown/store 0): id PK + `name` required
(trimmed, non-blank, NON-UNIQUE per OD-2) + `name_fa` optional + single
`is_active` default True + `created_at` only (no `updated_at` — master
convention). ONE constraint: `warehouse_name_nonblank` DB check. Services
mirror 4.2: `WarehouseValidationError`, type/strip guards,
`resolve_warehouse`, create/update/`set_warehouse_active` via
`record_audit_event` (CREATE/actual-UPDATE; no-op silent), NO delete path.
Migration `0001_initial` (no dependencies). Settings: 1-line
`INSTALLED_APPS` addition. C1: 8 files +412/−1. C2: golden +121.

## Tests (all executed, real numbers)

| Check | SQLite | PostgreSQL 17 (real, `config.settings.postgres`) |
|---|---|---|
| pytest (full) | 465 passed (436 + 29 new) | 465 passed |
| pytest (focused `warehouses/`) | 29 passed (21 + 8, first run) | — |
| Django `test` | 17 OK | 17 OK |
| Django `--pattern=*_tests.py` | 448 OK (419 + 29) | 448 OK |
| `check` | 0 issues | 0 issues |
| `makemigrations --check` | clean | — |
| Migration zero→0001→zero→0001 | OK | OK |
| Golden G43 (`-s` trail, 21 lines) | 8 PASS / 0 FAIL | — |

Golden trail: `docs/phase-reports/PHASE_4_STAGE_4.3_GOLDEN_OUTPUT.txt`
(G43-01 minimal create; 02 required/optional names; 03 duplicate names;
04 active lifecycle; 05 rename-keeps-PK; 06 audit trail; 07 no-op
silence; 08 scope boundary 12/12 absent).

## Scope (§20 — verified via `status` / `diff --check` / `diff`)

Changed: `backend/warehouses/` (9 files) + 1 settings line + 4.3 docs.
Untouched (zero diff): Phase 1, Phase 2, Phase 3, 4.1, 4.2, frontend,
dependencies, CI workflows. `diff --check` clean.

## Architecture confirmation (user rulings honored)

Business code NONE (OD-1) · Name NON-UNIQUE (OD-2) · Address NONE (OD-3) ·
Hierarchy NONE · Warehouse type NONE (1410/1420 stay account names) ·
Default NONE · Party/Product/UOM/Category/Account/Period FK NONE ·
Inventory logic NONE · Financial logic NONE. Deactivation = flag only;
rename keeps PK; future inventory will FK Warehouse (never reverse).
