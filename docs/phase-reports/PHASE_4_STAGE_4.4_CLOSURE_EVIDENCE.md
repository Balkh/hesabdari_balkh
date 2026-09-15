# Phase 4.4 — Closure Evidence (APPROVED → FROZEN)

**User approval:** 2026-09-15 ("تایید شد دوست من")
**Freeze (UTC):** 2026-09-15T20:27Z
**Branch:** `phase/4` — code `09199d2`
(`09199d2d91e963794948d077dd1c8e7636fe0f06`), tree clean
**Chain:** `09199d2`(C3 evidence) → `a6e15a8`(C2 golden) →
`cc6411b`(C1 feat) → `c9ea73d`(D0 rulings) → `083d925` (4.3 frozen)
**origin/main:** `646e35e` (unchanged — no merge)
**Remote CI:** NOT RUN (separate release/integration gate; no claim made)

## Freeze-time fresh verification (zero repairs needed)

Environment intact: modes 755, venv present, PostgreSQL accepting.

| Check | SQLite | PostgreSQL 17 (real) |
|---|---|---|
| pytest (full) | 520 passed | 520 passed |
| Django `test` | 17 OK | 17 OK |
| Django `--pattern=*_tests.py` | 503 OK | 503 OK |
| `check` | 0 issues | 0 issues |
| `makemigrations --check` | clean | — |
| Golden G44 (re-run) | 13 PASS / 0 FAIL | — |

## Frozen surface

`backend/cash_accounts/` + `backend/exchange_houses/` (models + services
+ 2× 0001 + 42 tests + G44-01..13) + 1 `INSTALLED_APPS` line + 4.4 docs.
Rulings honored: OD-5 no currency FK, OD-6/OD-7 no codes, OD-8/OD-9
non-unique names, OD-13 no contact; zero relations; zero transaction/
balance/ledger/posting logic. Phases 1/2/3/4.1/4.2/4.3 untouched. Any
change to this surface needs an explicit user **unfreeze** stating the
reason. Merge and next phases are user-driven only.
