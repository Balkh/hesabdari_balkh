# ERP_Afghanistan / hesabdari_balkh — Phase 1 Current Status

Date: 2026-09-07 (updated after Increments 22–24)

## Overall status

```text
FOUNDATION COMPLETE AND VERIFIED (Phase 1 close to done)
```

All previously blocking Phase 1 verification items are now cleared with
executed evidence. The only remaining Phase 1 item is desktop installer
packaging (`tauri build`), which is explicitly deferred.

## Verified by executed tests

### Local (SQLite development baseline, this sandbox)

```text
Django system check: 0 issues
Django tests: 17 passed
Backend pytest: 25 passed
Frontend build: PASS
Frontend tests: 4 passed
PHASE 1 LOCAL VERIFICATION: PASS
```

### Remote CI (GitHub Actions run 34149040085, PR #1 head f310eeb) — ALL GREEN

```text
✓ backend    in 17s   Django check + 17 tests + 25 pytest (Python 3.13)
✓ frontend   in 7s    tsc + Vite build + 4 node tests (Node 22)
✓ postgresql in 35s   full foundation suite executed on a real PostgreSQL 16 server
✓ tauri      in 2m28s cargo check PASS: Tauri v2 desktop shell compiles on Linux
```

This clears the three environment blockers that previously kept Phase 1 from
completing:

1. Remote CI execution — was failing with exit code 126 because the
   verification scripts were committed without the executable bit; fixed and
   green (Increment 22).
2. PostgreSQL compatibility — settings profile, driver, CI service job added;
   full suite passes on PostgreSQL 16 (Increment 23).
3. Tauri `cargo check` — blocked locally by missing GTK/WebKit libraries
   (apt egress blocked in the sandbox); executed in CI after adding the
   missing desktop icon set (Increment 24).

## Foundation inventory (all verified)

- Clean Git repository and documentation locations
- Django backend foundation (SQLite for local development)
- Currency master and historical directional exchange-rate foundation
- Central Jalali/Gregorian date boundary
- Document numbering foundation (Jalali-year-aware sequences)
- Double-entry journal foundation with balance/postability checks
- Atomicity and idempotency reservation foundation
- API error envelope and request logging
- Authentication/permission and audit foundation
- React + TypeScript foundation with i18n (fa/en), RTL/LTR, design tokens
- Local Django + Vite runtime integration
- Reproducible local and remote verification (backend, frontend, PostgreSQL)

## Remaining items (honest)

1. Desktop installer packaging (`tauri build` producing .deb/.rpm/AppImage)
   is not executed; the shell is verified only at `cargo check` level.
2. The Windows desktop target (the eventual offline deployment platform)
   requires a Windows runner and is not built.
3. This development sandbox still cannot run a local PostgreSQL server or a
   local Tauri compile because outbound access to OS package repositories is
   blocked; both are covered by the CI jobs above.
4. Business modules remain unimplemented by design.

## Boundary

No purchasing, sales, inventory transactions, payments, returns, remittance,
or financial reporting workflows have been implemented. Per the project
rules, those start only after Foundation readiness is approved and their
Phase 0 domain contracts are defined.
