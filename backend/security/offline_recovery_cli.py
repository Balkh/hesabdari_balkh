"""Standalone clean-room verification; never use a running ERP settings profile.

Run from backend: python -m security.offline_recovery_cli --help
"""
import argparse
import os
import sys


def configure_offline_django():
    from django.conf import settings
    if settings.configured or os.environ.get("DJANGO_SETTINGS_MODULE"):
        raise RuntimeError("offline verifier must start in a fresh process without an ERP settings profile")
    # Model declarations are needed by the canonical audit verifier, but the
    # dummy database backend prevents ORM access, authentication and migrations.
    from config.settings.base import INSTALLED_APPS
    settings.configure(INSTALLED_APPS=INSTALLED_APPS,
                       DATABASES={"default": {"ENGINE": "django.db.backends.dummy"}},
                       SECRET_KEY=os.urandom(32).hex(), USE_TZ=True, TIME_ZONE="UTC",
                       DEFAULT_AUTO_FIELD="django.db.models.BigAutoField")
    import django
    django.setup()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify an encrypted backup in isolated disposable storage; never activate a database.")
    parser.add_argument("--backup", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--trusted-public-sha256", required=True, help="independently recorded PUBLIC fingerprint")
    parser.add_argument("--vendor", required=True, choices=("sqlite", "postgresql"))
    parser.add_argument("--isolated-postgres", action="store_true",
                        help="confirm a dedicated loopback recovery server, never production")
    parser.add_argument("--pg-port", type=int)
    parser.add_argument("--pg-user")
    args = parser.parse_args(argv)
    try:
        configure_offline_django()
        from security.local_console import require_local_console
        from security.offline_recovery import prompt_secret, parse_recovery_secret, verify_offline_recovery
        require_local_console()
        pg = None
        if args.vendor == "postgresql":
            if not args.isolated_postgres or not args.pg_user or not args.pg_port or not 1 <= args.pg_port <= 65535:
                raise RuntimeError("explicit isolated PostgreSQL server, port and role are required")
            # Ignore inherited libpq routing and option variables in this
            # isolated process; all credentials are entered locally.
            for name in list(os.environ):
                if name.startswith("PG"):
                    os.environ.pop(name)
            pg = {"HOST": "127.0.0.1", "PORT": str(args.pg_port), "USER": args.pg_user,
                  "NAME": "postgres", "PASSWORD": prompt_secret("Isolated PostgreSQL role password: ")}
        elif args.isolated_postgres or args.pg_port or args.pg_user:
            raise RuntimeError("PostgreSQL options are invalid for SQLite recovery")
        secret = parse_recovery_secret(prompt_secret("Independent recovery secret (64 hex characters): "))
        result = verify_offline_recovery(
            backup_path=args.backup, checkpoint_path=args.checkpoint, bundle_path=args.bundle,
            recovery_secret=secret, trusted_public_sha256=args.trusted_public_sha256,
            vendor=args.vendor, restore_database_config=pg)
        print("OFFLINE DISPOSABLE RECOVERY VERIFIED; no ERP database activated")
        print("Events:", result["event_count"], "Head:", result["head_hash"])
        print("Backup SHA-256:", result["backup_sha256"])
        return 0
    except Exception:
        # Do not echo secrets, arbitrary provider errors or tracebacks.
        print("Offline recovery verification failed; no activation authorized. Inspect isolated environment and retained artifacts.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
