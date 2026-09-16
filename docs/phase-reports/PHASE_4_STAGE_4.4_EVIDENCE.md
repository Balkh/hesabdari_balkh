# Phase 4.4 — Implementation Evidence (IMPLEMENTED → TESTED → recorded)

**Date (UTC):** 2026-09-15T20:18Z
**Branch:** `phase/4` — base `083d925` (4.3 frozen) — tree clean
**Chain:** `a6e15a8`(C2 golden) → `cc6411b`(C1 feat) → `c9ea73d`(D0 rulings)
→ `083d925`. Full SHAs: a6e15a898ea46e9b5862ee08d26c18a0c1f238c3,
cc6411bb8436fb0c1b2ea6ec66c01646022101f8,
c9ea73d76d3547fbf63113010018fc47e5c72543.
**Remote CI:** NOT RUN (separate gate; no claim made).

## Implementation

Two independent operational masters in separate plural apps (singular
`cash/` + `exchange/` stay reserved for future engines):

- `CashAccount(id, name req, name_fa opt, is_active T, created_at)` —
  one physical cash resource (§9.1). Constraint
  `cash_account_name_nonblank`. NOT COA 1110.
- `ExchangeHouse(id, name req, name_fa opt, is_active T, created_at)` —
  one named financial-account relationship (§9.3). Constraint
  `exchange_house_name_nonblank`. NOT a Party, NOT a COA leaf.

Services mirror 4.3 exactly: dedicated `ValidationError`, type/strip
guards, `resolve_*`, create/update/`set_*_active` via `record_audit_event`
(CREATE/actual-UPDATE; no-op silent), NO delete path. Migrations
`0001_initial` each, zero dependencies. Settings: 1-line `INSTALLED_APPS`
addition. C1: 15 files +851/−1. C2: golden +215.

## Tests (all executed, real numbers)

| Check | SQLite | PostgreSQL 17 (real, `config.settings.postgres`) |
|---|---|---|
| pytest (full) | 520 passed (465 + 55 new) | 520 passed |
| pytest (focused both apps) | 55 passed (21 + 21 + 6 + 7, first run) | — |
| Django `test` | 17 OK | 17 OK |
| Django `--pattern=*_tests.py` | 503 OK (448 + 55) | 503 OK |
| `check` | 0 issues | 0 issues |
| `makemigrations --check` | clean | — |
| Migration zero→0001 (both apps) | OK | OK |
| Golden G44 (`-s` trail, 34 lines) | 13 PASS / 0 FAIL | — |

Golden trail: `docs/phase-reports/PHASE_4_STAGE_4.4_GOLDEN_OUTPUT.txt`
(G44-01..05 cash identity/lifecycle/rename; 06..10 same for EH; 11 audit
trail; 12 no-op silence; 13 scope boundary 18/18 absent on BOTH models).
Unit scope pins additionally assert ZERO concrete relations per model.

## Scope (§22 — verified via `status` / `diff --check` / `diff`)

Changed: `backend/cash_accounts/` (8 files) +
`backend/exchange_houses/` (8 files) + 1 settings line + 4.4 docs.
Untouched (zero diff): Phase 1, Phase 2, Phase 3, 4.1, 4.2, 4.3,
frontend, dependencies, CI, accounting/currency/date/audit logic.
`diff --check` clean. No FROZEN-PHASE CONFLICT.

## Architecture confirmation (user rulings honored)

NO currency FK (OD-5) · NO codes (OD-6/OD-7) · NON-UNIQUE names (OD-8/
OD-9) · NO contact fields (OD-13) · NO Party FK · NO COA FK · NO
transaction/balance/ledger/posting/FX/remittance logic of any kind.
Deactivation = flag only; rename keeps PK.
