# Fresh Database Bootstrap Runbook

## Purpose and boundary

A schema migration creates database tables; it does not create the ERP's canonical accounting master data. After all migrations have been applied to a genuinely fresh database, this manual command creates:

- The canonical V1 chart of accounts from `accounting.coa.CANONICAL_COA`.
- AFN (Afghani, ؋) as the sole base currency, with 2 decimal places.
- USD (US Dollar, $) as the required active foreign currency, with 2 decimal places.
- Exactly one audit event identified by entity `SystemBootstrap` and reference `fresh-database-v1`.

The approved domain contract identifies AFN as the base currency and USD as the primary foreign currency. This command does not create exchange rates.

## Preconditions

1. Point Django at the intended database and confirm the database name/host before proceeding.
2. Take and verify a database backup when operating on a persistent environment.
3. Apply all schema migrations first:
   ```bash
   python manage.py migrate --check
   python manage.py migrate
   ```
4. Run the bootstrap once, from the backend directory, with the deployment's normal Django settings and database credentials:
   ```bash
   python manage.py bootstrap_fresh_database
   ```
5. Review the command output and verify the resulting Account, Currency, and AuditEvent records before allowing operational use.

## Safety behavior

- This is an explicit management command. It is not run by migrations, app startup, WSGI, or ASGI.
- Before first-time writes, the command inspects every installed, managed, concrete Django model table in the configured database.
- The only exempt rows are Django-generated `contenttypes.ContentType` and `auth.Permission` reference metadata created by migrations/post_migrate. They are framework metadata, not operator-entered ERP setup.
- Existing rows in all other models block bootstrap. This includes users, groups, admin history, sessions, audit events, idempotency records, accounts, currencies, exchange rates, fiscal periods, categories, products, parties, warehouses, inventory, purchases, sales, payments, allocations, and other installed ERP-domain records.
- Before its first ORM query against Account, Currency, or AuditEvent, the command performs a schema-only preflight across all installed, managed, concrete application models. Missing model tables block bootstrap with a clear error; apply all migrations before retrying. The command does not create schema.
- On a genuinely fresh migrated database, creation of the canonical COA, AFN/USD, and the audit event occurs in one database transaction.
- A sequential rerun verifies every canonical account and required currency, confirms exactly one matching CREATE audit event, and exits without changing rows.
- If the database contains partial or divergent accounting master data, or the bootstrap audit event is missing, duplicated, orphaned while the master tables are empty, or has an unexpected action, the command refuses to proceed. It does not attempt repair, merge, reset, or overwrite.
- If audit persistence fails during first-time initialization, the database transaction rolls back the COA and currency rows as well.
- Existing canonical account edits are not silently replaced. Resolve any divergence through the approved accounting-owner process; do not delete or reset records to force the command through.
- Additional non-canonical accounts or currencies are not deleted. The command verifies the required canonical records only.
- Run this command operationally as a single controlled action; do not start concurrent bootstrap executions.

## Explicitly out of scope

The command does not create users, roles, fiscal periods, warehouses, products, parties, opening balances, exchange rates, or business transactions. Those require their own approved setup workflows.

## Evidence and review

The automated tests in `accounting/test_bootstrap.py` cover fresh initialization, AFN/USD configuration, audit recording, sequential idempotency, missing/duplicate/orphaned audit refusal, transaction rollback on audit failure, refusal on partial setup, preservation of accountant edits, refusal when non-accounting ERP records already exist, and refusal when a user already exists.

A successful command is evidence that this bootstrap operation completed for the selected database; it is not a claim that the ERP is production-ready or that other operational setup is complete.
