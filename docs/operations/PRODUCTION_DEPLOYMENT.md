# Production Deployment Preconditions

This document records prerequisites only. It does not define a supported
container image, process manager, public hostname, or production topology.

## Explicit settings profile

WSGI and ASGI server processes must set `DJANGO_SETTINGS_MODULE` explicitly.
For production, set it to `config.settings.production`; never copy the
development value from `.env.example` into a production service.

The Django management entry point intentionally retains its development
default for local commands. Production commands must set the environment
explicitly, for example:

```sh
DJANGO_SETTINGS_MODULE=config.settings.production python manage.py check --deploy
DJANGO_SETTINGS_MODULE=config.settings.production python manage.py collectstatic --noinput
```

## Required environment

Production settings require all of the following:

- `DJANGO_SETTINGS_MODULE=config.settings.production`
- `DJANGO_SECRET_KEY`: a strong, unique secret of at least 50 characters
- `DJANGO_DEBUG=false`
- `DJANGO_ALLOWED_HOSTS`: explicit production hostnames. The wildcard
  entry `*` is rejected at startup (enforced in
  `config/settings/production.py`; regression-tested in
  `security/test_security_batch3.py`)
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
  `POSTGRES_HOST`, and `POSTGRES_PORT`

Startup fails fast — before the application can serve any request —
when a required variable is missing (`DJANGO_SECRET_KEY` or any
`POSTGRES_*` value), the secret is empty, the development default, or
shorter than 50 characters, `DJANGO_DEBUG=true`, or
`DJANGO_ALLOWED_HOSTS` is empty or contains the wildcard entry `*`.
Error messages name the offending variable and never echo configured
secret values.

Do not commit production secrets or place them in logs. Supply them through
the deployment platform's secret/environment mechanism.

## TLS and reverse proxy

Production settings enable SSL redirection, secure session/CSRF cookies, and
one-year HSTS. The deployment proxy must terminate valid TLS, overwrite or
strip any client-supplied `X-Forwarded-Proto` header before setting its own,
and prevent direct untrusted access to the Django application server. Verify
the actual DNS, certificate, proxy-header, redirect, and HTTPS health-probe
behavior after infrastructure exists; code configuration alone is not proof.

HSTS `includeSubDomains` and `preload` remain disabled until the owner
documents and approves the public domain/subdomain architecture.

## Static files

`STATIC_ROOT` is the collection destination. Run `collectstatic` during
deployment and configure a trusted web server or static-file service to serve
the resulting files. Django's development static-file serving is not a
production deployment strategy.

## Admin access and throttling limits

The current admin login has no application-level login throttling. Until a
separate owner-approved control is implemented, restrict admin access at the
network/proxy layer and use strong, unique staff passwords. Document the
actual restriction in the deployment runbook.

The configured DRF throttle uses Django's local-memory cache unless an
environment explicitly configures another cache. Its counters are per
process and are not shared between workers or servers. Treat it as a
basic per-process guard, not complete brute-force protection. Do not assume
that an external/shared cache exists.

## CSRF, logging, and verification

For browser/session-based access, configure the exact trusted HTTPS origins
required by the deployment; do not add wildcard trusted origins. Request
logging currently uses the console handler, so the deployment platform must
capture, retain, and protect process logs according to its operational needs.

Before exposing the service, run Django's deployment checks with the
production environment, verify PostgreSQL connectivity and migrations, test
the health endpoint over HTTPS through the real proxy, and verify admin,
CSRF, static-file, and redirect behavior. Infrastructure-dependent checks
remain unverified until a real deployment exists.

## Security control status (Security Batch 3)

Implemented in code and covered by regression tests:

- Explicit `DJANGO_SETTINGS_MODULE` requirement at WSGI/ASGI startup
  (fail-fast; `manage.py` keeps its local-development default).
- Production secret guard: missing, empty, development-default, and
  sub-50-character secrets abort startup.
- Production `DJANGO_DEBUG=true` aborts startup.
- Production host guard: empty host lists and the wildcard entry `*`
  abort startup; explicit hostnames boot cleanly.
- PostgreSQL-only production database configuration: each `POSTGRES_*`
  variable is required; a missing variable aborts startup.
- `STATIC_ROOT` for `collectstatic`.
- DRF authenticated-by-default permissions and per-process request
  throttles; a denied unauthorized write persists neither a domain row
  nor an audit event (regression-tested).

Configured in settings but NOT verified in real infrastructure:

- TLS termination, `X-Forwarded-Proto` hygiene, HSTS delivery, secure
  redirects, and static-file delivery require a real deployment to
  verify; repository evidence cannot prove infrastructure behavior.

Deferred by owner decision (not implemented in Security Batch 3):

- Admin login protection: a reverse-proxy strategy must be verified
  against a real deployment before an application-level control is
  added. No admin login throttling exists today.
- Shared cache for throttle counters: counters remain per-process
  (local-memory cache); a Redis/shared-cache decision remains open.
- Financial role granularity: the authorization model is unchanged —
  every ERP endpoint requires an authenticated user and nothing more;
  role-granularity review is deferred to a separate owner-approved
  phase.

## Not decided by this document

This document does not choose an API client login/token flow, RBAC roles,
Redis/shared cache, admin code-level throttling, container packaging, or a
process manager. Those require separate owner-approved contracts.
