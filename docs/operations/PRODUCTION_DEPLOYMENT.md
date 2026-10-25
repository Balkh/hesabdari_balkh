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
- `DJANGO_ALLOWED_HOSTS`: explicit production hostnames, not `*`
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
  `POSTGRES_HOST`, and `POSTGRES_PORT`

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

## Not decided by this document

This document does not choose an API client login/token flow, RBAC roles,
Redis/shared cache, admin code-level throttling, container packaging, or a
process manager. Those require separate owner-approved contracts.
