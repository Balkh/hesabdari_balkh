# Hesabdari Balkh ERP — Pre-Windows Completion Readiness Audit

**Audit date:** 2026-11-23  
**Mode:** Read-only baseline and dependency audit; this document adds no application code or runtime behavior.  
**Purpose:** Establish the remaining ERP/security/desktop work that must be addressed before producing and practically accepting the Windows desktop package.  
**Evidence boundary:** This is a live repository audit of the named GitHub refs below. Historical reports are treated as evidence only for the commit they identify, not as proof of the present branch.

## 1. Live repository baseline

| Item | Live value | State |
|---|---|---|
| `main` | `6498f37c3b37fd802676a11fd8012b98bad1c754` | unchanged during this audit |
| PR #57 / W0-2B-R2 | `security/w0-2b-r2-enforcement` @ `87c56129cd7b727cfe7807b4e82b6d64e85d132d` | Draft, open, unmerged |
| PR #58 / W0-2C | `security/w0-2c-mfa-session-recovery` @ `77acc03091bcfe5d3171a776596f844e18a43424` | Draft, open, unmerged |
| PR #58 base | PR #57 head @ `87c56129cd7b727cfe7807b4e82b6d64e85d132d` | stacked dependency |
| PR #58 exact-head CI | Actions run [#45229693950](https://github.com/Balkh/hesabdari_balkh/actions/runs/45229693950) | completed, all 7 jobs successful |

The seven successful jobs were Backend, PostgreSQL, Frontend, Tauri shell, and the three Windows key-custody evaluations (Windows Server 2022 x64, Windows Server 2025 x64, and Windows 11 ARM64). The Tauri job performs a frontend bundle and Linux `cargo check`; it does **not** build or launch the Windows desktop package. Windows CI probes key-custody/session APIs; it does **not** complete the end-user Windows 10/11 x64 acceptance runbook.

PR #58's description is stale: it still says the exact-head run was in progress. The live Actions resource now reports run #45229693950 as completed/successful. This audit corrects the evidence interpretation; it does not change or approve the PR.

No merge, un-draft, production activation, tag, or freeze is authorized by this audit.

## 2. What exists in code versus what is operationally exposed

### 2.1 Backend domain foundations

The current W0-2C tree contains domain models/services/tests for, among others:

- accounting and journal posting;
- purchases and landed costs;
- sales and Sales/Transit ownership, allocation, and warehouse-check services;
- payments and cross-currency settlement;
- Party Ledger;
- inventory and stock movements;
- cash accounts and exchange-house accounts;
- allocations, customer custody, and goods in transit;
- fiscal periods; and
- document numbering.

These are important foundations. Their existence alone does not establish a complete, usable ERP workflow, because each operational vertical also needs the approved API boundary, authorization declarations, frontend screens, reports/print support where required, and end-to-end evidence.

### 2.2 Mounted API surface (verified from `backend/config/urls.py` and app URL modules)

The current mounted `api/v1` surfaces are:

1. Core API root and health endpoints.
2. Security identity/authentication/MFA endpoints.
3. Fiscal-period endpoints.
4. Purchase **landed-cost** endpoints.

The current `backend/purchases/urls.py` exposes landed-cost list/detail/post/reverse only. The current root URL configuration does not mount Sales, Payments, Party Ledger, Inventory, Cash Accounts, Exchange Houses, Allocations, Customer Custody, or Goods-in-Transit APIs. This is not a claim that their domain services are absent; it is a finding that these workflows are not yet exposed through the current mounted API surface.

### 2.3 Frontend (verified from current frontend source tree)

The React application remains a foundation shell:

- the routes are the foundation home and an About page;
- the API service shown in the app calls the health endpoint;
- there is no authenticated application shell, login/MFA flow, session state, permission-aware navigation, or operational business page set;
- Dari/Persian RTL and English LTR foundations exist, but the business workflows have not yet been surfaced as a coherent bilingual operational UI.

### 2.4 Documents, reports, and backup

- The Documents app currently contains a document-number sequence model and numbering service. A complete centralized template/preview/print/PDF workflow is not established by the present tree.
- No backend reports application is present in the current tree.
- `backend/backup/` is only a placeholder directory; a tested backup/restore and disaster-recovery subsystem is not present.
- Therefore, reporting, Half-A4 invoice output, centralized PDF generation, backup integrity validation, and recovery drills remain material product gaps.

## 3. Security and desktop status

### 3.1 W0-2B / R2 and W0-2C

PR #57 contains operation-aware API RBAC and singleton GM enforcement. PR #58 adds MFA/TOTP, offline GM recovery, local-console guards, registered-session control, and Windows Credential Manager integration. Both are still draft/unmerged; exact-head CI success is not owner acceptance or a production release.

Current controls also include:

- mandatory GM MFA;
- at most two registered employee sessions, with a third denied without evicting existing sessions;
- 15-minute idle and 12-hour absolute lifetime for registered sessions;
- local-only bootstrap/emergency GM recovery; and
- a deliberately disabled Django Admin surface returning 404.

### 3.2 Remaining security work

1. **W0-2D — Account lockout and recovery administration:** `account_locked()` in `backend/security/authorization.py` is currently a no-op. OD-5 requires failed-login logging, configurable account lockout, and GM review/unlock capability. Numeric thresholds/duration are explicitly not selected in OD-5; they must not be silently invented. The login throttle is not a substitute for account-level lockout.
2. **W0-2E — Append-only/tamper-evident security audit:** The required control is not yet implemented as an enforceable append-only/hash-chain audit subsystem. Existing AuditEvent usage is a foundation, not proof against ordinary application-level tampering or a complete security event catalogue.
3. **W0-2F — Trusted-origin controls:** Trusted browser/WebView origins and the local API boundary need explicit restrictive configuration and tests. No wildcard trusted origin is acceptable. This must be coordinated with the actual Tauri local-runtime transport/origin contract.
4. **BasicAuthentication residual:** BasicAuthentication remains on selected frozen compatibility routes for employees not subject to MFA. Basic requests do not create registry-managed sessions, so they bypass the two-session admission cap, idle/absolute timeout, and per-session revocation. Removing it would alter the frozen Batch 2/3 compatibility contract; retaining it requires a documented, explicit owner risk decision.
5. **Django Admin:** Keep all `/admin` routes denied (404) until the dedicated singleton-GM + verified-MFA + account-lockout authorization gate and its negative-path tests exist.

OD-5 records the account-security requirements, but does not specify the numeric lockout parameters. A proposed setting set must be presented for owner selection before implementation relies on it.

### 3.3 Tauri desktop runtime

The current Tauri Rust entry point is a bare shell builder. Cargo dependencies contain Tauri only; there is no Django sidecar supervisor or backend lifecycle controller. The desktop runtime still needs:

- packaged backend launch and process supervision;
- readiness/health detection and failure-safe startup;
- graceful stop and stale-process handling;
- loopback-only binding and host/origin/CSRF alignment;
- absolute app-data database path resolution;
- proof that Django runs as the same Windows user who owns the Credential Manager secrets; and
- Windows installer/runtime smoke tests.

The current `vite.config.ts` development server binds to `0.0.0.0` and allows hosts broadly. This is a development-server setting, not evidence of a production listener, but it must be reviewed and constrained as part of W0-2F / desktop development hardening.

### 3.4 Practical Windows acceptance

The runbook `docs/security/W0-2C_WINDOWS_ACCEPTANCE_RUNBOOK.md` is marked required/manual/not executed. The outstanding tests include Windows 10 x64 and Windows 11 x64 end-user machines, reboot persistence, second-user Credential Manager isolation, real RDP/remote-control/remote-shell denials, same-user DB backup/restore, and a profile-loss GM recovery drill against a disposable database. These tests are distinct from GitHub-hosted Windows CI.

## 4. Business-contract and operational gaps

The following distinction is mandatory: a model/service/test foundation is not the same as a complete business transaction workflow.

| Area | Current evidence | Remaining work before full ERP acceptance |
|---|---|---|
| Master data | Domain models/services exist for Parties, Products, Units, Warehouses, and related records | Controlled create/edit/deactivate APIs, per-operation RBAC, searchable bilingual UI, safe validation |
| Party Ledger | Backend attribution/ledger foundation exists | API and customer/supplier ledger screens, drill-down/reconciliation, end-to-end links to invoices and payments |
| Purchase-to-Inventory | Purchase and inventory domain foundations exist; landed-cost API is mounted | Complete purchase invoice, payment/settlement, receiving, supplier ledger, inventory and exchange-house vertical through APIs and UI |
| AVAILABLE Sales | Sales domain models/services/tests exist | Expose approved sales lifecycle through API/UI; confirm all posting, COGS, inventory, ownership, payment, release and cancellation contracts |
| FUTURE Sales | OD-1 establishes Type-B ownership and source-lot COGS boundaries | Implement only within approved OD-1; do not infer unresolved custody valuation, reporting, returns, or cancellation rules |
| Payments / allocations | Service/model layers exist, including cross-currency settlement | Authorized APIs, UI, customer/supplier allocation and reconciliation flows, idempotency and reversal evidence |
| Treasury / exchange houses | Cash-account and exchange-house services exist | Operational cashbook/house ledgers, transfer/settlement/commission/statement/reconciliation APIs and UI |
| Goods in Transit / custody | Domain events/services/tests exist | Full user-facing workflows, integrated reporting and end-to-end acceptance; preserve the approved A1/B1 decisions |
| Fiscal periods | API and service/test foundations exist | Final close controls, reporting and end-to-end role/security checks |
| Documents / printing | Numbering foundation exists | Central document engine, preview, bilingual Half-A4 templates, PDF/print, selected line printing, authorization and audit |
| Reports | No reports app found in the current tree | Trial Balance, GL, P&L, Balance Sheet, cash flow, subsidiary and operational reports reconciled to source ledgers |
| Backup / restore | Placeholder only | Actual offline backup, integrity verification, restore, key/database coordination and tested disaster recovery |
| Settings / search | Foundation remains incomplete | Product configuration, controlled numbering, currency/rate, date/localization, global search and management workflows |

### Contract cautions

- The Sales contract resolution separates Sale, payment, ownership, custody, release authorization, physical issue, fulfillment, purchase, and Sales Return. Business ownership rules must not be used to invent journal/COGS treatment.
- Phase 11 Decision A1 (fail closed when later dependent activity makes correction unsafe) and B1 (Transit COGS at invoice finalization) are recorded as resolved in the owner-decision memo. A separate Phase 11 open-policy memo still has a transit-loss reversal/dependent-posting question; do not confuse it with the resolved B1 COGS-timing decision.
- The open-policy memo for transit-loss reversal must remain a gate for that specific behavior. Do not create a general history-replay engine or weaken existing reversal guards.
- Existing approved accounting foundations, posted-document immutability, invoice-time COGS rules, cost-by-lot, currency/rate traceability, and the user's phase gates remain protected.

## 5. Recommended dependency order before Windows package acceptance

This is a sequencing recommendation, not an approval to alter unresolved owner decisions.

### Gate A — Close security prerequisites

1. Finish W0-2D account lockout design and implementation after selecting the owner-controlled threshold, lock duration/decay, and GM unlock/recovery behavior.
2. Implement W0-2E append-only/hash-chain audit protection with SQLite and PostgreSQL concurrency/rollback tests; cover successful/failed login, logout, account lifecycle, role/permission changes, session revocation, bootstrap/recovery, and sensitive actions.
3. Implement W0-2F restrictive trusted-origin/CSRF/CORS settings after the local Tauri origin/transport is specified; reject wildcard and unrecognized origins.
4. Resolve the BasicAuthentication residual through an explicit owner decision and test the chosen boundary.
5. Keep Admin disabled until its complete gate is proven.

### Gate B — Complete operational backend verticals

1. Master data and Party Ledger APIs.
2. Purchase-to-Inventory end-to-end API vertical, including supplier settlement and exchange-house handling where applicable.
3. AVAILABLE Sales API vertical; then FUTURE Sales only under OD-1 and after unresolved accounting gates are approved.
4. Payments/allocations, cash accounts, exchange-house operations, goods-in-transit and customer-custody workflows.
5. Exact per-method RBAC declaration and negative-path tests for every mounted route; no authenticated-only shortcut in production.

### Gate C — Complete the operational frontend

1. Login, MFA enrollment/challenge, recovery-code handling for eligible employees, logout, CSRF, auth context, permission-aware routing.
2. Session expiry handling, the two-minute pre-expiry warning, and safe reauthentication.
3. Bilingual RTL/LTR operational screens for every approved workflow, with validation/error/loading/empty states.
4. No frontend authority for accounting balances, permissions, posting, dates, or transaction state; the backend/domain remains source of truth.

### Gate D — Complete operational support systems

1. Centralized reports with traceable drill-down and reconciliation to authoritative ledgers.
2. Centralized documents, preview, Half-A4/PDF/print, numbering and print audit.
3. Offline backup/restore/disaster recovery with database/key custody and integrity checks.
4. Remaining configuration, search, and deployment/upgrade controls.

### Gate E — Desktop runtime, then Windows package

Only after Gates A–D have passed review:

1. Integrate and supervise the packaged Django runtime from Tauri.
2. Prove loopback-only listener, secure origin/CSRF behavior, correct app-data DB path, same Windows-user key custody, and reliable shutdown/restart.
3. Build the Windows installer.
4. Execute the manual Windows 10/11 x64 acceptance runbook and full disposable-data recovery drill.
5. Perform end-to-end accounting/inventory/security/reporting/printing/backup acceptance.

## 6. Owner decisions needed before affected implementation

The audit found these decision gates; it does not choose on the owner's behalf:

- **W0-2D lockout parameters:** OD-5 requires configurable lockout and GM unlock but intentionally leaves numeric thresholds/time windows to implementation selection. Approve an exact policy before code hardens those values. Recommended candidate for review: 5 failed password attempts within 15 minutes, followed by a 15-minute timed lock, with progressive extension on repeated lockouts and GM-logged unlock. This is a recommendation only, not an adopted setting.
- **BasicAuthentication:** retain the narrow legacy compatibility exception with an explicit risk acceptance, or authorize a staged migration to registered SessionAuthentication on every affected route. Do not silently alter Batch 2/3.
- **Transit-loss reversal:** obtain the remaining owner choice in `PHASE_11_OPEN_POLICY_DECISIONS.md` before implementing reversal after dependent postings.
- **Sales accounting gates:** review the exact outstanding Sales posting/COGS/valuation/custody/returns decisions before expanding Sales posting behavior.

## 7. Evidence and completion rules

For each implementation batch, record exact branch/SHA/PR, changed files, migration impact, SQLite and PostgreSQL results, frontend build/tests, API positive and negative paths, accounting golden/reconciliation evidence, and current CI on the exact head.

A successful CI run is necessary but not sufficient. Physical Windows acceptance, backup/recovery evidence, operational user review, and explicit approval remain separate gates.

## 8. Final audit conclusion

**The project is not ready for a Windows release package today.** The immediate blockers are not the installer itself: they are the still-unfinished security controls, exposed operational API/UI workflows, reports/documents, backup/restore, and the Tauri-to-Django runtime boundary.

The correct next action is to proceed one bounded workstream at a time, beginning with W0-2D design/implementation after the lockout policy decision, then W0-2E and W0-2F, while separately advancing the business verticals and operational UI. Do not build or declare an accepted Windows package until the preceding gates have evidence and owner review.

---
**Audit limitations:** This document does not inspect a physical Windows workstation, execute local database tests, prove manual end-user behavior, or re-evaluate all historical business-phase test logs. It records current GitHub source/resource observations plus the cited contract/status documents. Where a previous report conflicts with the current source tree, the current branch tree controls; historical report claims are not carried forward as current facts.
