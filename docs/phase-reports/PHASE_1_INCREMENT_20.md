# Phase 1 Increment 20 — Local Runtime Integration

Date: 2026-09-06

## Scope

Started the local Django API and Vite frontend together, fixed preview-host allowlists, and verified browser-facing paths through the local runtime.

## Implemented

- Django development server bound to `0.0.0.0:8000`
- Vite frontend bound to `0.0.0.0:5173`
- Django development hosts allow preview hosts
- Vite allowed hosts configured for the preview environment
- Frontend `/api` proxy verified against Django

## Verification evidence

```text
Frontend preview host response: PASS
Backend API host response: PASS
Health response: {"status":"ok","service":"hesabdari_balkh-backend","database":"ok"}
```

## Status

PASS for local runtime integration. Tauri remains blocked pending Rust/Cargo.
