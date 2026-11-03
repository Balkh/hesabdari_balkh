# W0-2B / R2 — Security Status and Reconciliation Addendum

**Date:** 2026-11-03  
**Repository:** `Balkh/hesabdari_balkh`  
**Baseline:** `6498f37c3b37fd802676a11fd8012b98bad1c754`  
**State:** R2 implementation in progress on `security/w0-2b-r2-enforcement`. This file is a status record, not a freeze declaration.

## 1. Source-of-truth boundary

The approved W0-2A architecture remains on its separate design branch and is not merged by this addendum. Historical R1 decisions remain authoritative except where a separately reviewed R2 addendum explicitly defines an implementation boundary. R1 compatibility tests and accounting/domain contracts must remain unchanged.

The R2 plan is maintained in the owner-reviewed revised design and execution plan. This addendum records the current baseline, corrected inventory, approved implementation defaults, blockers, and evidence rules. It does not rewrite W0-2A or assert that any unimplemented control is active.

## 2. Live baseline at start of R2

- `main` was re-fetched from GitHub at `6498f37c3b37fd802676a11fd8012b98bad1c754`.
- PR #56 is merged. No open PR was returned at the start of this work.
- CI run #516 for that exact main SHA completed successfully: backend, frontend, PostgreSQL, and Tauri jobs succeeded.
- The workflow currently uses PostgreSQL 16, not PostgreSQL 17.11. PostgreSQL 17.11 verification remains outstanding.
- GitHub reports `main.protected=false` and no repository rulesets. Detailed classic branch-protection metadata was inaccessible through the current integration. Repository governance remains an owner-side action.
- The branch `security/w0-2b-r2-enforcement` was created from the exact main SHA above. No changes were made directly to `main`.

## 3. Corrected mounted API inventory

The live URL configuration contains **13 URL patterns** and **15 explicit HTTP method operations**:

| Area | URL patterns | Explicit methods |
|---|---:|---:|
| Core infrastructure | 3 | 3 |
| Security | 1 | 1 |
| Fiscal periods | 5 | 6 |
| Purchases / landed costs | 4 | 5 |
| **Total** | **13** | **15** |

The three Core infrastructure operations remain explicit public `AllowAny` endpoints. The remaining **12 protected business API operations** use **11 distinct catalog permission keys**. The shared `purchases.landedcost.view` key is used by both collection-list and object-detail operations. `purchases.landedcost.delete_draft` is catalog-only; no current route implements it. Django Admin is a separate surface and is not included in the API route count.

## 4. Authorization decisions adopted for R2 implementation

The following recommended defaults from the revised plan govern the R2 branch:

1. The operation-aware API path validates server-declared object targets before a GM protected allow. The legacy key-only R1 resolver contract and its existing tests remain unchanged.
2. Missing, malformed, and unauthorized object targets receive a uniform generic 403 response at the permission boundary. Internal denial reasons are not returned to clients.
3. An authenticated RBAC denial remains denied if an audit write fails; audit is best-effort and failure is safely logged.
4. R2 audit vocabulary is limited to `PERMISSION_DENIED`. Other lifecycle vocabulary, audit hash chain, database triggers, immutability, and tamper-evidence remain with W0-2E.
5. `/api/v1/security/me/` continues to use the approved `security.account.view_own` key and a SELF_USER target derived only from `request.user`.
6. Global SQLite `transaction_mode=IMMEDIATE` is not changed in R2.
7. Production has no runtime authentication-only escape hatch. The production RBAC flag guard is added only after every protected route and required Admin control has been implemented and verified.

### Explicit remaining blockers

- **Denial-audit flood limit:** normal DRF throttles run after permission checks and therefore do not bound denied-request audit writes. A bounded denial-audit throttle is the preferred design, but its threshold has not been specified in the owner-reviewed plan. Do not invent a threshold or turn on persistent denial auditing until this is resolved.
- **Django Admin activation:** the approved GM-only gate is required. Before enabling it for deployment, inventory existing staff/superuser accounts and verify the intended GM account has an active GM assignment and `is_staff=True`. No automatic superuser-to-GM conversion is to be introduced in R2.
- **PostgreSQL 17.11:** current CI is PostgreSQL 16; a 17.11 run and full evidence are still required.
- **Repository protection:** GitHub owner action is required to protect `main` and require the agreed CI checks.
- **Credential rotation:** any previously exposed GitHub credentials must be revoked by the owner; do not put token values in source, logs, reports, or chat. Revocation is not considered verified until the owner confirms it.

## 5. Route inventory to be enforced

| Method | Route | Permission key | Operation ID | Binding |
|---|---|---|---|---|
| GET | `/api/v1/security/me/` | `security.account.view_own` | `security.me.retrieve` | Object: authenticated self User |
| GET | `/api/v1/fiscal-periods/` | `fiscal.period.view` | `fiscal.period.collection.list` | Collection |
| POST | `/api/v1/fiscal-periods/` | `fiscal.period.create` | `fiscal.period.collection.create` | Collection |
| POST | `/api/v1/fiscal-periods/<pk>/close/` | `fiscal.period.close` | `fiscal.period.object.close` | Object: FiscalPeriod |
| POST | `/api/v1/fiscal-periods/<pk>/reopen/` | `fiscal.period.reopen` | `fiscal.period.object.reopen` | Object: FiscalPeriod |
| POST | `/api/v1/fiscal-periods/<pk>/lock/` | `fiscal.period.lock` | `fiscal.period.object.lock` | Object: FiscalPeriod |
| POST | `/api/v1/fiscal-periods/<pk>/unlock/` | `fiscal.period.unlock` | `fiscal.period.object.unlock` | Object: FiscalPeriod |
| GET | `/api/v1/purchases/landed-costs/` | `purchases.landedcost.view` | `purchases.landedcost.collection.list` | Collection |
| POST | `/api/v1/purchases/landed-costs/` | `purchases.landedcost.create` | `purchases.landedcost.collection.create` | Collection |
| GET | `/api/v1/purchases/landed-costs/<pk>/` | `purchases.landedcost.view` | `purchases.landedcost.object.retrieve` | Object: LandedCostDocument |
| POST | `/api/v1/purchases/landed-costs/<pk>/post/` | `purchases.landedcost.post` | `purchases.landedcost.object.post` | Object: LandedCostDocument |
| POST | `/api/v1/purchases/landed-costs/<pk>/reverse/` | `purchases.landedcost.reverse` | `purchases.landedcost.object.reverse` | Object: LandedCostDocument |

Collection request-body identifiers such as landed-cost payee/currency IDs remain domain inputs validated by existing services; they do not become authorization targets.

## 6. Implementation and verification state

Each implementation batch must have a reviewable diff and tests. The sequence is:

- R2.0: this documentation/status addendum.
- R2.1: operation registry, constructor-free DRF permission, typed target references, shared operation-aware resolver path, and URL/system drift check.
- R2.2: GM-only custom Django Admin site, gated on account inventory review before deployment.
- R2.3: wire the 12 listed operations, with authentication-first permission ordering and endpoint tests.
- R2.4: add authenticated denial audit only after the flood-control threshold is explicitly settled.
- R2.5: require strict `ERP_RBAC_ENFORCEMENT=True` at Production startup, after complete route/Admin coverage.
- R2.6: SQLite, PostgreSQL 17.11, migration, exact PR-head CI, and post-merge evidence.

Do not claim PASS, VERIFIED, COMPLETE, GREEN, or FROZEN merely because source changes or CI exist. Report the exact branch, commit SHA, test command/output, CI run, database version, skips, and outstanding caveats.

## 7. Frozen business invariants

R2 does not change accounting posting, immutable posted records, reversal-only history, inventory movement/costing, fiscal-period lifecycle services, landed-cost posting/reversal, idempotency, or any other business rule. Authorization wraps the existing API/services; it does not replace domain validation.

**Current status:** documentation addendum only until subsequent implementation commits land. No merge, production enablement, or freeze is implied.
