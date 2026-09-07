# Phase 1 Increment 22 — CI Repair and Verification Fix

Date: 2026-09-07

## Scope

Fixed the first GitHub Actions CI execution (push `611cc8a` → run `34147039783`) so that remote verification can pass. This was the previously BLOCKED "remote CI execution" item in `PHASE_1_CURRENT_STATUS.md`.

## Root cause evidence

Both CI jobs failed at `scripts/verify_backend.sh` / `scripts/verify_frontend.sh` with:

```text
X Process completed with exit code 126.
```

`exit code 126` means "found but not executable": the three verification scripts were committed with git mode `100644` (no executable bit), so the CI `run:` steps could not execute them. Locally the suite had only ever been invoked through `bash script.sh`, which masked the problem.

A second local-only defect was found while reproducing the frontend job: `npm test` (`node --test tests`) fails on the current Node.js because a bare directory argument to the test runner is no longer supported (Node ≥ 21 treats it as a module path):

```text
Error: Cannot find module '.../frontend/tests'
```

## Changes

1. `chmod +x` the three verification scripts and commit them with git mode `100755`.
2. `frontend/package.json`: test command now targets the actual test file — `node --test tests/frontend.test.mjs`.
3. `.github/workflows/ci.yml`: frontend job node-version `20` → `22` (Node 20 reached end-of-life April 2026).

## Verification (executed locally before commit)

```text
$ ./scripts/verify_phase1.sh
Django system check: 0 issues      (from verify_backend.sh, set -e pipefail)
Django tests: 17 passed
Backend pytest: 25 passed
Frontend build: PASS
Frontend tests: 4 passed
PHASE 1 LOCAL VERIFICATION: PASS
```

Remote CI execution result is reported separately once the pull request triggers GitHub Actions.

## Status

PASS for this increment (local). Remote CI re-execution is triggered by the accompanying pull request.
