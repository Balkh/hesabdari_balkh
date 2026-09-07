# Phase 1 Increment 24 — Tauri Desktop Shell Verification via CI

Date: 2026-09-07

## Scope

Attempts to clear the BLOCKED "Tauri `cargo check` not tested" item from `PHASE_1_CURRENT_STATUS.md`. The Tauri v2 source scaffold from Increment 19 is unchanged — this increment only creates an environment where it can actually be compiled and verified.

## Why CI

Increment 21 recorded the first Tauri verification attempt: the Rust toolchain was installed but the compile failed inside `gdk-sys` because the sandbox lacks GTK/WebKit development libraries (`Package gdk-3.0 was not found`). Re-checking today confirmed this sandbox still cannot install those libraries: outbound access to the Debian package repositories is blocked (network egress limited to PyPI/npm/GitHub), and no Rust toolchain is present.

GitHub Actions `ubuntu-latest` runners can install both the GTK/WebKit libraries and Rust, so the verification is executed there as a first-class CI job — the same class of environment limitation the project already documents for local PostgreSQL verification.

## Changes

`.github/workflows/ci.yml` gained a `tauri` job that:

1. Installs the Tauri v2 system libraries for Debian/Ubuntu (`libwebkit2gtk-4.1-dev`, `build-essential`, `libxdo-dev`, `libssl-dev`, `libayatana-appindicator3-dev`, `librsvg2-dev`, …).
2. Builds the React bundle first (`npm ci && npm run build`) because the Tauri build context embeds `frontendDist` (`../dist`).
3. Installs the stable Rust toolchain via rustup and runs `cargo check` in `frontend/src-tauri` (with `Swatinem/rust-cache@v2` for repeat runs).

## Boundary

No desktop business logic, packaging, or bundling was added or executed in this increment. `cargo check` proves the Tauri shell compiles; it is not an installer/package run.

## First CI attempt and fix

The first CI run (run `34148473369`) reached the compile but failed with:

```text
error: proc macro panicked
 --> src/lib.rs:4:14
  |
4 |         .run(tauri::generate_context!())
  |
  = help: message: failed to open icon .../frontend/src-tauri/icons/icon.png:
         No such file or directory (os error 2)
```

Root cause: the Increment 19 scaffold had no icon set, and Tauri's
`generate_context!` requires one at compile time.

## Fix

1. `frontend/src-tauri/icons/generate_icons.py` — reproducible Pillow generator
   for a desktop icon set (no external artwork; a navy rounded square with a
   golden double-entry balance mark).
2. Generated `icons/icon.png`, `32x32.png`, `128x128.png`, `128x128@2x.png`,
   `icon.ico` and declared `bundle.icon` in `tauri.conf.json`.
3. CI cargo step now also captures and re-emits the compiler error tail as a
   workflow annotation when the check fails (keeps failures diagnosable).

## Executed evidence (GitHub Actions run `34149040085`, head `f310eeb`)

```text
✓ frontend in 7s
✓ backend in 17s
✓ tauri in 2m28s     <- cargo check PASS: the Tauri v2 shell compiles on Linux
✓ postgresql in 35s
```

## Status

PASS — `cargo check` for the Tauri v2 desktop shell is green in CI
(run `34149040085`). Desktop installer packaging (`tauri build` → .deb/.rpm/
AppImage and the future Windows target) is still NOT executed; it remains a
later packaging task outside this increment's scope.
