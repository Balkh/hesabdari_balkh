"""Vendor-specific database enforcement of append-only AuditEvent rows."""

from django.db import migrations


SQLITE_FORWARD = [
    "CREATE TRIGGER security_auditevent_no_update BEFORE UPDATE ON security_auditevent "
    "BEGIN SELECT RAISE(ABORT, 'security_auditevent is append-only'); END",
    "CREATE TRIGGER security_auditevent_no_delete BEFORE DELETE ON security_auditevent "
    "BEGIN SELECT RAISE(ABORT, 'security_auditevent is append-only'); END",
]
POSTGRES_FORWARD = [
    "CREATE OR REPLACE FUNCTION security_reject_audit_mutation() RETURNS trigger "
    "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'security_auditevent is append-only'; END; $$",
    "CREATE TRIGGER security_auditevent_no_update_delete BEFORE UPDATE OR DELETE "
    "ON security_auditevent FOR EACH ROW EXECUTE FUNCTION security_reject_audit_mutation()",
]
SQLITE_REVERSE = [
    "DROP TRIGGER IF EXISTS security_auditevent_no_update",
    "DROP TRIGGER IF EXISTS security_auditevent_no_delete",
]
POSTGRES_REVERSE = [
    "DROP TRIGGER IF EXISTS security_auditevent_no_update_delete ON security_auditevent",
    "DROP FUNCTION IF EXISTS security_reject_audit_mutation()",
]


def install_append_only_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    statements = SQLITE_FORWARD if vendor == "sqlite" else POSTGRES_FORWARD if vendor == "postgresql" else None
    if statements is None:
        raise RuntimeError(f"unsupported audit trigger database vendor: {vendor}")
    for sql in statements:
        schema_editor.execute(sql)


def remove_append_only_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    statements = SQLITE_REVERSE if vendor == "sqlite" else POSTGRES_REVERSE if vendor == "postgresql" else None
    if statements is None:
        raise RuntimeError(f"unsupported audit trigger database vendor: {vendor}")
    for sql in statements:
        schema_editor.execute(sql)


class Migration(migrations.Migration):
    dependencies = [("security", "0016_audit_chain_backfill")]

    operations = [
        migrations.RunPython(install_append_only_triggers, remove_append_only_triggers),
    ]
