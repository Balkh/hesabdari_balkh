# W0-2E final review — candidate, not approved or frozen

## Evidence baseline

- Batch A: fc8ca4a7ad8c8bc5654adf784df10f9291328da4 / CI 45871240992: 7/7; 8 targeted tests on each engine.
- Batch B: 4ebf28333a6ca7002486515ca20a3bf88bd92a66 / CI 45874146230: 7/7; 4 targeted migration tests each, no model drift.
- Batch C: 211b8fd9955b074d6374b7f24607da0b8a29e495 / CI 45880480180: 7/7; 4 targeted restore tests each; real isolated restore of balanced 125.50 AFN journal and trigger rejection. SQLite pytest 1436 passed/19 skipped; PostgreSQL 1440 passed/15 skipped.
- Batch D: current candidate must be verified on its exact SHA; no PASS inferred from previous results.

## Owner decision matrix

A: SQLite IMMEDIATE and 20-second timeout, concurrent append, timeout and rollback tests executed in previous gates. Known limit: exhaustive outer transaction/caller graph and every financial aggregate still not independently proven. Do not add unproven retries.
B: AES-256-GCM and signed Ed25519 backups, isolated dual-engine restore tested. Actual offline destination, independent owner key custody/recovery, schedule and retention enforcement, production restore drill not established; see draft backup runbook.
C: GM-only review/export, active singleton MFA, separate export authority; no Auditor role or Accountant grant. Batch D adds negative access and privacy tests; legacy records not rewritten. Pattern-based redaction cannot guarantee arbitrary unlabelled secrets in free text; historic content must be handled with owner-approved restricted custody, not silently changed.

## Performance and residual risks

Invalid audit filters are rejected before ledger verification; remove unused user join. The full verifier still materializes and hashes all rows, holding the writer serialization boundary; cost grows with history. No production-scale throughput/latency SLA or load benchmark has been established. A future measured optimization must preserve exact snapshot and tamper detection; do not substitute unaudited sampling or cached success.
Static inventory does not prove dynamic call graph or that every domain mutation emits an event. Authorization denial still fails closed if audit persistence fails; such failures require monitoring and operational response (not a claim of durable denial logging when storage is unavailable). Database/OS owner can bypass ordinary controls; trigger inspection is not proof against privileged replacement. PostgreSQL TRUNCATE and SQLite replacement semantics require separate explicit review before production acceptance.
Session/Basic compatibility unchanged. No hawala implementation. No merge, deployment, release, freeze, or W0-2F transition approved.

## Final approval gate

Review exact-head CI jobs and raw targeted logs; reconcile residual findings, validate operational custody and deployment prerequisites, and obtain explicit owner decision. This file is a draft evidence matrix, not a release certificate.
