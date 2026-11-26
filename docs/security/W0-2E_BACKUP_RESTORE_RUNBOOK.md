# W0-2E backup and restore operator runbook — draft

Status: implementation review, not production scheduling authorization.

## Approved policy

- End-of-business-day encrypted offline backup and before every schema upgrade.
- Signed checkpoint daily and after each shift on high-activity days.
- Retain daily copies for 30 days and one month-end copy for 12 months.
- Monthly disposable restore and full chain verification; never overwrite the live database.
- Keep encryption and signing keys separate from the database and employee profile.

## Required owner setup before scheduling

Record the actual approved offline media/location, authorized GM/OS identity, custody of recovery copies of encryption keys and signing trust keys, recovery procedure on a replacement machine, and authorized PostgreSQL maintenance/restore role if applicable. Windows Credential Manager is per OS identity: successful CI probes do not establish owner-controlled off-device recovery. Do not enable schedules or automatic retention deletion until these operational decisions and a real recovery drill are signed off. Never put secrets or key material in this runbook or the repository. No actual destination or credentials have been selected here.

## Local operations

Use the existing management commands (inspect --help for required arguments): provision_backup_keys, create_encrypted_backup, create_audit_checkpoint, verify_encrypted_backup. Use only an authorized GM and a configured independent provider. Run backup during a quiet/maintenance window, outside a transaction. PostgreSQL requires compatible pg_dump/pg_restore/createdb/dropdb and permissions for temporary database creation/deletion; use an isolated verification server for operational recovery drills. Do not use production database credentials in CI.

A valid backup is an encrypted .hbak and its signed manifest together. Keep both and separately retain the trusted verification key. File creation alone is not restore evidence. If publishing or audit logging fails, stop, preserve existing artifacts for investigation, and do not mark the run successful. Do not overwrite a live database for verification. Plaintext temporary files are restricted to disposable workspace; operating-system storage encryption and secure media handling remain operational requirements (file deletion is not guaranteed secure erasure).

## Evidence gate

CI uses synthetic financial journals and disposable databases with fixed test-only keys. It exercises AES-GCM, Ed25519, real SQLite backup and PostgreSQL dump/restore, manifest and key failure controls, restored balances and audit guards, and cleanup. A green CI is not a production recovery drill, independent physical key custody, scheduling, retention enforcement, or Windows installer acceptance. Report exact SHA and actual logs. Never merge/freeze without owner approval.
