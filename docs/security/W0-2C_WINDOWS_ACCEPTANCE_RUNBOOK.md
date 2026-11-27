# W0-2C Windows Acceptance Runbook

Status: REQUIRED MANUAL ACCEPTANCE — NOT YET EXECUTED
Scope: Windows 10 x64 and Windows 11 x64 end-user workstations.
Safety: perform all destructive/recovery checks only against a disposable copy of the ERP database.

## 1. Why this runbook exists

GitHub Actions checks have exercised the key-provider API on Windows Server 2022, Windows Server 2025, and Windows 11 ARM64. Those runs are useful CI evidence, but they do not prove behavior on Windows 10/11 x64 end-user machines, after a reboot, across different Windows users, or during a real backup/recovery drill.

The Tauri repository shell currently does not launch/supervise the Django backend. Until that integration exists, run the Django commands manually from the local Windows console for this acceptance work.

## 2. Preparation: use a disposable Windows workstation and database

1. Sign in locally at the physical keyboard/display as the Windows user who will own the ERP desktop installation. Do not use Remote Desktop, remote-control/shadowing, SSH, or WinRM.
2. Use a dedicated test Windows account and a disposable database path. Do not point these tests at live company data.
3. Open PowerShell on the physical console and enter the backend directory.
4. Provision the OS secrets under a non-desktop settings profile first. The desktop profile intentionally refuses to boot if its Windows Credential Manager secrets do not already exist; it cannot be used to bootstrap those same secrets.

Example PowerShell setup:

```powershell
$env:DJANGO_SETTINGS_MODULE = "config.settings.development"
$env:HESABDARI_DESKTOP_DATABASE_PATH = Join-Path $env:LOCALAPPDATA "HesabdariBalkh\acceptance\hesabdari.sqlite3"
New-Item -ItemType Directory -Force (Split-Path $env:HESABDARI_DESKTOP_DATABASE_PATH) | Out-Null
python manage.py provision_windows_desktop_secrets
```

The command must report success without printing either secret value. It creates the AES key and Django signing secret in the current Windows user's Credential Manager. If provisioning reports that a partial or existing vault cannot be overwritten, stop; do not delete credential records manually as a recovery shortcut.

## 3. Provider and settings checks

From the backend directory, run:

```powershell
python -m pytest security/test_windows_key_provider.py security/test_windows_key_custody_eval.py security/test_local_console.py
python manage.py check --settings=config.settings.desktop
python manage.py migrate --settings=config.settings.desktop
```

Record Windows edition, version/build, architecture, Python version, test output, and exact branch SHA. Do not record key values, TOTP seeds, recovery codes, passwords, or credential blobs.

Confirm that:
- the provider can read the AES key and Django secret for the current Windows account;
- the key material is not returned by application logs, management-command output, or error messages;
- desktop settings require an absolute database path and fail closed when required credentials are absent;
- no fallback to environment variables, a plaintext file, or a software keyring appears when Credential Manager is unavailable.

## 4. Persistence and user isolation

1. Restart the command prompt, sign out/in, and reboot the workstation. Re-run a non-secret provider read check and `manage.py check --settings=config.settings.desktop`.
2. Sign in as a different ordinary Windows user. Attempt the same provider read check using the same application namespace. The second account must not be able to read the first account's AES key or Django signing secret.
3. Sign back in as the original owner account and verify that the original key is still available.
4. Verify that the Credential Manager records are stored for the intended user and that the provider does not request machine-wide persistence or silently widen ACLs.

Do not print or copy key material to prove equality. A test-only process can compare returned values internally and emit only PASS/FAIL.

## 5. Physical-console and remote-session denial

The shared command guard is expected to deny:
- a non-interactive process;
- SSH/remote-shell environment markers;
- a Windows process outside the active physical-console session;
- a Windows Remote Desktop client session;
- a session currently under remote control/shadowing;
- a session whose process ID does not match Windows `GlassSessionId`;
- any case in which Windows cannot provide the required session information.

On a disposable database, verify that each of these management commands rejects execution before changing persistent state:
- `issue_gm_bootstrap_token`
- `bootstrap_gm`
- `issue_gm_emergency_owner_key`
- `recover_gm_offline`
- `provision_windows_desktop_secrets`

Perform remote-session attempts from RDP and, where supported by the workstation policy, SSH/WinRM. Confirm a safe denial and that no token, owner key, TOTP URI, or new recovery code is shown. Then verify that the physical-console process reaches the expected next validation gate. Never generate or consume a production bootstrap token for this test.

The guard uses Windows session identity plus `SM_REMOTESESSION`, `SM_REMOTECONTROL`, and the local `GlassSessionId`. Microsoft's documentation warns that `SM_REMOTESESSION` alone can misidentify some RemoteFX sessions; the local-session registry value is the additional discriminator. See:
- https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getsystemmetrics
- https://learn.microsoft.com/en-us/windows/win32/termserv/detecting-the-terminal-services-environment
- https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-wtsgetactiveconsolesessionid
- https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-processidtosessionid

This is defense in depth, not proof of the physical identity of the person at the keyboard. Local administrators, malicious software running as that Windows user, hypervisor/console redirection, or privileged instrumentation are outside what a process-session check alone can establish. Keep the offline owner key separate and physically controlled.

## 6. Encrypted data backup and restore

Use a disposable GM account with an active TOTP device on the test database.

1. Create a backup of the database while the original Windows user and Credential Manager vault are intact.
2. Restore that backup to a separate disposable database on the same workstation under the same Windows user.
3. Confirm the restored encrypted MFA device can be read and the original GM can complete a valid TOTP login without exposing the secret.
4. Confirm recovery-code hashes remain usable only once and session rows are revoked according to the recovery test plan.

A successful same-machine restore proves only that the database backup and that user's key vault are mutually usable on that workstation. It is not a disaster-recovery plan for a lost Windows profile or lost computer.

## 7. Offline GM recovery drill after simulated profile loss

Perform this only against a disposable database copy, not the original test account or production data.

1. Preserve the separately issued offline GM emergency owner key from the test bootstrap. Do not place it in the database backup, shell history, cloud storage, or ordinary workstation files.
2. Simulate loss of the original Windows profile by using a fresh disposable Windows user profile or a dedicated test VM. Do not delete a real user's profile.
3. Provision new OS secrets under the new test profile using the physical-console command in Section 2.
4. Restore the database backup copy. Confirm that old encrypted TOTP cannot be decrypted with the new AES key and that the system does not fall back to plaintext.
5. Run the local-only `recover_gm_offline` command with the offline owner key. Verify the recovery preserves the same GM assignment and assignment history, disables previous MFA devices, revokes all active sessions, replaces the password and TOTP device, issues ten new one-time recovery-code hashes, rotates the owner key, and writes an audit event without secret material.
6. Verify successful login with the new password and new TOTP device. Verify the old TOTP device, old recovery codes, old owner key, and old sessions no longer work.
7. Retain only redacted evidence: timestamps, workstation build, branch SHA, exit codes, anonymized row counts, status assertions, and audit IDs. Destroy disposable secrets according to the test workstation procedure.

## 8. Evidence checklist

For each Windows target, attach:
- OS edition/build and architecture;
- exact repository SHA and Python version;
- unit-test and provider-test outputs;
- reboot and second-user isolation PASS/FAIL evidence;
- physical-console success and RDP/remote-control/remote-shell denial evidence;
- same-user database backup/restore evidence;
- offline GM recovery evidence from a disposable restored DB;
- redacted audit evidence and confirmation that no secret entered logs/artifacts.

## 9. Acceptance status

This document is a test procedure, not evidence that these tests have been performed. W0-2C must remain Draft and not Production-ready until the supported Windows 10/11 x64 runs, packaged Tauri/backend integration, security review, owner review, and explicit owner approval are completed.
