"""Additional append-only guards; forward migration keeps 0017 intact."""
from django.db import migrations

SQLITE_REPLACE = (
    "CREATE TRIGGER security_auditevent_no_replace BEFORE INSERT ON security_auditevent WHEN EXISTS (SELECT 1 FROM security_auditevent WHERE id = NEW.id OR event_uuid = NEW.event_uuid OR prev_event_hash = NEW.prev_event_hash OR event_hash = NEW.event_hash) BEGIN SELECT RAISE(ABORT, 'security_auditevent replacement is forbidden'); END"
)
PG_FUNCTION = (
    "CREATE FUNCTION security_reject_audit_truncate() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF EXISTS (SELECT 1 FROM security_auditevent) THEN RAISE EXCEPTION 'security_auditevent truncate is forbidden'; END IF; RETURN NULL; END; $$"
)
PG_TRIGGER = (
    "CREATE TRIGGER security_auditevent_no_truncate BEFORE TRUNCATE ON security_auditevent "
    "FOR EACH STATEMENT EXECUTE FUNCTION security_reject_audit_truncate()"
)


def install(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "sqlite":
        schema_editor.execute(SQLITE_REPLACE)
    elif vendor == "postgresql":
        schema_editor.execute(PG_FUNCTION)
        schema_editor.execute(PG_TRIGGER)
    else:
        raise RuntimeError(f"unsupported audit trigger database vendor: {vendor}")


def remove_when_empty(apps, schema_editor):
    event = apps.get_model("security", "AuditEvent")
    if event.objects.using(schema_editor.connection.alias).exists():
        raise RuntimeError("W0-2E append-only triggers cannot be removed while audit history exists")
    vendor = schema_editor.connection.vendor
    if vendor == "sqlite":
        schema_editor.execute("DROP TRIGGER security_auditevent_no_replace")
    elif vendor == "postgresql":
        schema_editor.execute("DROP TRIGGER security_auditevent_no_truncate ON security_auditevent")
        schema_editor.execute("DROP FUNCTION security_reject_audit_truncate()")
    else:
        raise RuntimeError(f"unsupported audit trigger database vendor: {vendor}")


class Migration(migrations.Migration):
    dependencies = [("security", "0017_audit_append_only_triggers")]
    operations = [migrations.RunPython(install, remove_when_empty)]
