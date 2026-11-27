# Offline disaster recovery — ODR candidate

Status: engineering candidate, not operational authorization. No actual owner keys, physical media, database or recovery device were accessed. Preserve existing W0 acceptance baseline e076b678fd842f0a88f21da26e34303335b5712f and CI 45901831568.

## Threat model and limits

- An independently held, cryptographically random 256-bit recovery secret (64 hexadecimal characters) encrypts a small versioned HBR1 envelope using AES-256-GCM, a random 96-bit nonce and domain-separated authenticated header. This is a random key, NOT a human password; syntax cannot prove entropy. Use an owner-approved offline random generator or password manager on a trusted device. No recovery secret is accepted in argv, environment or logs by production commands.
- One bundle covers one explicit historical backup AES key ID and checkpoint Ed25519 public-key ID. Maintain a bundle and independently recorded PUBLIC SHA-256 fingerprint for every retained key pair. The public fingerprint is checked out of band; never trust a fingerprint from the untrusted manifest or bundle itself.
- No signing private key, MFA encryption key, Django signing secret, emergency owner key, password or session data is escrowed. The recovery provider has no active/signing methods. Replacement-device signing rotation, employee MFA re-enrollment and GM recovery are separate existing or future owner-approved workflows. No account activation or database installation is implemented here.
- A stolen bundle plus its recovery secret can decrypt backups covered by that key; keep bundle, recovery secret and backup on distinct owner-controlled offline custody locations. Loss of all copies means loss of access. No automatic export, retention deletion, schedule, or vault import. Python process memory cannot guarantee secure zeroization; encrypted workspace/disk and trusted OS remain required.

## Owner-only issuance on source

From the actual source installation, locally and interactively, use manage.py create_backup_recovery_bundle --destination ABSOLUTE_EXTERNAL_PATH --encryption-id ID --signing-id ID with the normal authorized settings. The command checks physical/local console policy, current singleton GM emergency owner key (not consumed), independent secret and confirmation, configured key provider, schema and full chain; writes only an exclusive encrypted artifact and audits its digest. No keys are printed; the public fingerprint and artifact digest are safe to record out of band. If audit commit fails after publication, retain artifact securely and investigate; no success claim. Use explicit retained historical IDs, never silently fall back to current IDs.

## Clean-room disposable verification

Use a clean trusted checkout of the compatible verifier, an encrypted temporary workspace and a local interactive terminal. From backend, with DJANGO_SETTINGS_MODULE unset, run python -m security.offline_recovery_cli --vendor sqlite --backup PATH --checkpoint PATH --bundle PATH --trusted-public-sha256 PUBLIC_FINGERPRINT. For PostgreSQL use --vendor postgresql --isolated-postgres --pg-port PORT --pg-user ROLE on an isolated loopback-only recovery instance, not a production server. Enter recovery secret and isolated PostgreSQL password interactively. The standalone process uses Django dummy ORM backend; it does not query an ERP account or use source credentials. Explicit engine matching, pinned public trust, authenticated bundle, signed manifest, ciphertext digest, authenticated decrypt, disposable restore, full chain/guards and cleanup are mandatory. PostgreSQL dumps execute database objects; only restore authenticated trusted backups in a restricted isolated instance. Physical isolation and role permissions must be verified by owner, not assumed by flags.

Successful verification does not install the restored DB or create a GM session. Never point the tool at production infrastructure, never overwrite a live database, never treat temporary files as securely erased. A separate activation and disaster recovery drill must establish account recovery, new vault provisioning, preserved financial balances, new signing authority, replacement-device operational acceptance and RPO/RTO. Actual deployment topology, two independent backup media, key custody, retention/scheduling and recovery location remain owner decisions.

## Tests and evidence

Targeted suite covers envelope roundtrip, no signing-private read, wrong recovery secret/pin, tamper/truncation, key reuse, collision, owner authorization denial, and real fresh-process disposable restore on both engines with dummy ORM and 125.50 AFN journal reconciliation. CI uses synthetic data and test-only secrets. Actual execution pending. No merge/freeze/deployment authorization.
