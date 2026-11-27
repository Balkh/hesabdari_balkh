# W0 security acceptance gate — engineering candidate, not operational approval

Baseline: PR #62, branch integration/w0-security-consolidated, ec2c4fdd5003d3ab701d06522bea8c1851816522, pinned main 6498f37c3b37fd802676a11fd8012b98bad1c754. CI 45898389350: 7/7 on temporary merge c0b6ee155e857f91ea18a4f215909f97322f6dbb, identical tree 4c8736508816e4f4d355f4c78c9160b99b37a8e6. Six findings FR-01–06 verified within tested scope. No merge/freeze/release/deploy approval.

## Engineering gate candidate

- Add targeted real central writer failure after final event INSERT at AuditChainHead.save in transit sale, transit delivery, historical transit custody bridge, future sale. Compare persisted financial state and audit head before/after, retry with correct existing financial contract and idempotency. Historical fixture is disposable; no production mutation.
- Benchmark 10,000 committed synthetic events in 100 transactions; reconnect and verify entire chain using one ledger SELECT, verify subsequent append. Record actual times. This is not peak concurrency, memory, or production SLA evidence.
- Enable verbose Django and pytest skip reasons without removing or relaxing tests. Previous CI only published totals: Django SQLite 2, PostgreSQL 6 skips; pytest SQLite 21, PostgreSQL 17 skips. Individual reasons still require actual new logs.
- No runtime code or accounting formula changes in this candidate. New results pending. Other financial aggregates and legacy non-transit delivery path still require separate coverage review; do not imply exhaustive tests.

## Operational acceptance — unresolved prerequisites

Approved policy: daily offline encrypted backup, before every schema upgrade, daily or shift signed checkpoint, 30 daily and 12 month-end retention, monthly disposable recovery. Do not enable automatic jobs or deletion yet.

Owner decisions to record (never record actual passwords or keys in GitHub or chat):
1. Actual deployment model (local Windows dedicated GM OS account, or separately authorized server). Identify dedicated account and storage permissions, not credentials.
2. Offline media: recommend two independent encrypted removable drives rotated, one disconnected/off-site, distinct from live data path; actual location/media owner-selected. Confirm compatible exclusive file publication and disk encryption.
3. Key recovery: current Windows provider creates keys in a per-user machine-local vault and refuses plaintext export; there is no proven replacement-device key import/recovery path. Public-key-only reads are possible but independent trust transfer is not implemented. Before production, select a separately protected recovery design (e.g. offline encrypted recovery bundle with independently held recovery secret and trusted public-key fingerprint, or approved external key provider); design/implement/test separately, never export plaintext secrets. Preserve encryption keys for all retained backup versions. Do not assume the Windows vault survives hardware loss.
4. Clean-room recovery authorization: existing verify_encrypted_backup management command requires an active GM in a database before calling the disposable restore service. A replacement machine without a restored database cannot assume that identity exists. Design an explicit locally authorized recovery/bootstrap workflow with independent trust and no authentication bypass on live systems; require isolated verification and actual replacement-device drill before operational sign-off.
5. Retention, schedule and responsibility: actual owner-approved end-of-day time, shift cadence, media rotation, monthly drill, backup-failure alerts, review of retention candidates before deletion, recovery objectives (RPO/RTO) and production data volume. Do not silently schedule or delete.
6. Physical test: provision owner-controlled keys; create encrypted backup and signed checkpoint on selected offline media; verify trusted fingerprint out-of-band; restore on separate disposable Windows machine or isolated PostgreSQL server; verify chain, financial reconciliation, record counts and required guards; validate GM access/recovery; document observed recovery duration and sanitized evidence; never overwrite live DB. Confirm no plaintext residue and acknowledge deletion is not secure erasure.

## Decisions and limits

Engineering merge acceptance and production activation are separate decisions. No physical media, key, owner device, or actual operational schedule has been accessed or selected by this review. No approval to merge, freeze, deploy, release or close original PRs. Hawala out of scope. 
