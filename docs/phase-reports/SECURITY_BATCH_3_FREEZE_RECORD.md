# Security Batch 3 — Freeze Record

## Status

Owner-approved and frozen after merge and post-merge CI verification.

Lifecycle completed: INSPECT → IMPLEMENT → TEST → EVIDENCE → USER REVIEW → APPROVED → **FROZEN**.

## Frozen content

| Item | Value |
|---|---|
| Source PR | [#45 — Security Batch 3](https://github.com/Balkh/hesabdari_balkh/pull/45) |
| Reviewed PR head | `b6044a16640524be9be9ec3527d90a1c18dd066e` |
| PR base | `c6694105cfa893cb1f6ef386e8783490ec19ea05` |
| Merge strategy | Squash merge |
| Merge commit | `453db0695cfc10c0f87b1d18da57a2fca35e11d5` |
| Tree at merge | `744c75a9a928ec91cb85801044a3f6218a593ea2` |
| CI run on PR head | [40404095383](https://github.com/Balkh/hesabdari_balkh/actions/runs/40404095383) — all four jobs SUCCESS |
| Post-merge main CI | [40619971314](https://github.com/Balkh/hesabdari_balkh/actions/runs/40619971314) — all four jobs SUCCESS on the merge commit |

## Scope frozen

1. Production settings reject the exact parsed `ALLOWED_HOSTS` entry `*`; regression cases cover standalone, mixed, and whitespace-padded entries.
2. F-10 production negative-path tests cover missing PostgreSQL environment variables, unsafe DEBUG, invalid/missing secret, and empty/wildcard hosts.
3. Positive production settings boot and WSGI/ASGI entrypoint tests.
4. Characterization of the existing DRF throttle cache behavior.
5. Anonymous protected financial write is denied with HTTP 403 and persists neither a domain row nor an audit event.
6. Production deployment documentation updated to state code-level controls, deployment-dependent checks, and deferred decisions.

## Evidence

The post-merge workflow run `40619971314` completed with conclusion `success` for the exact main commit `453db0695cfc10c0f87b1d18da57a2fca35e11d5`. The `backend`, `frontend`, `postgresql`, and `tauri` jobs each completed successfully. The PR-head workflow `40404095383` also passed all four jobs.

## Owner decisions and deferred work

- Admin login protection remains deferred until a real deployment and reverse-proxy rate-limiting strategy can be verified.
- Shared cache/Redis for throttle counters remains undecided; current local-memory throttle counters are per-process.
- Financial role granularity is unchanged and deferred to a separate owner-approved phase.
- No accounting-contract changes, migrations, remittance/hawala functionality, dependency changes, or CI workflow changes were included in this batch.

## Known limitations — not a production-readiness claim

Repository CI proves the tested code-level behavior only. TLS termination, proxy/header hygiene, HSTS delivery, secure redirects, static-file serving, and admin protection under real deployment conditions remain unverified. This record does not claim production infrastructure readiness or complete security certification.

## Approval

The repository owner explicitly approved merge and freeze in the project review conversation. This record documents that approval and the verified post-merge evidence; it does not expand the approved scope.
