# Tauri Desktop Shell

The Tauri v2 shell scaffold is present and intentionally contains no ERP business logic. It packages the React frontend only; the local Django runtime integration remains a later desktop deployment task.

## Verification status

`cargo check` for the shell is verified in GitHub Actions CI (the `tauri` job,
which installs the GTK/WebKit system libraries and Rust on an ubuntu-latest
runner). Desktop installer packaging and the Windows target are not yet built.

This development sandbox cannot run the compile locally because outbound
access to OS package repositories is blocked (no GTK/WebKit development
libraries available).
