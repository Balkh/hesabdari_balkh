#!/usr/bin/env python3
"""W0-2E static audit-writer inventory and conservative review gate.

This is a source inspection aid, not a proof of runtime reachability,
transaction ownership, dynamic dispatch, database integrity or audit coverage.
Migrations and test code are listed separately and need their own review.
Unknown model/table access fails closed pending explicit source review.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

EXPECTED_BUSINESS = {
    "accounting/services.py", "allocations/services.py",
    "cash_accounts/services.py", "categories/services.py",
    "customer_custody/services.py", "exchange_houses/services.py",
    "fiscal_periods/services.py", "goods_in_transit/services.py",
    "inventory/services.py", "parties/services.py",
    "party_ledger/services.py", "payments/services.py",
    "products/services.py", "purchases/services.py",
    "purchases/landed_cost_posting.py", "purchases/landed_cost_reversal.py",
    "purchases/landed_cost_services.py", "purchases/supplier_refund_services.py",
    "sales/services.py", "sales/returns_services.py",
    "supplier_advances/services.py", "uom/services.py", "warehouses/services.py",
}
EXPECTED_SECURITY = {
    "security/auth_views.py", "security/emergency_owner_key_service.py",
    "security/login_lockout.py", "security/mfa_policy.py",
    "security/mfa_service.py", "security/management/commands/bootstrap_gm.py",
    "security/management/commands/issue_gm_bootstrap_token.py",
}
REVIEWED_MODEL_ACCESS = {
    "security/models.py",  # Schema declarations.
    "security/audit_chain.py",  # Single event writer and verifier.
    "security/audit_chain_signals.py",  # Empty-ledger genesis initialization.
    "security/audit_views.py",  # Verified read/export.
    "security/backup_service.py",  # Read-only restored snapshot verification.
    "accounting/management/commands/bootstrap_fresh_database.py",  # Marker reads.
}
APPROVED_MODEL_WRITES = {
    ("security/audit_chain.py",
     "AuditChainHead.objects.filter(pk=1).update(updated_at=now)"),
    ("security/audit_chain_signals.py",
     "AuditChainHead.objects.using(using).create(pk=1, head_hash=GENESIS_HASH)"),
}
MODEL_NAMES = {"AuditEvent", "AuditChainHead"}
WRITER_NAMES = {"record_audit_event", "append_audit_event"}
MUTATORS = {
    "create", "acreate", "bulk_create", "abulk_create", "bulk_update",
    "abulk_update", "update", "aupdate", "delete", "adelete", "_raw_delete",
    "get_or_create", "aget_or_create", "update_or_create", "aupdate_or_create",
    "save", "asave", "save_base",
}
TABLE = re.compile(r"\bsecurity_audit(?:event|chainhead)\b", re.I)
SQL_MUTATION = re.compile(
    r"\b(?:insert\s+into|replace\s+into|update|delete\s+from|truncate(?:\s+table)?)\b",
    re.I,
)


def classification(path: str) -> str:
    parts = Path(path).parts
    name = parts[-1]
    if any(part.startswith(".") or part == "__pycache__" for part in parts):
        return "excluded"
    if "migrations" in parts:
        return "migration"
    if "tests" in parts or name.startswith("test_") or name.endswith("_tests.py") or name == "tests.py":
        return "test"
    return "runtime"


def inspect_source(path: str, source: str) -> tuple[list, list, list]:
    tree = ast.parse(source, filename=path)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for imported in node.names:
                if imported.name in MODEL_NAMES | WRITER_NAMES:
                    aliases[imported.asname or imported.name] = imported.name

    def canonical_name(name):
        return aliases.get(name, name)

    def scope(node):
        current = parents.get(node)
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return current.name
            current = parents.get(current)
        return "<module>"

    def contains_model(node):
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and canonical_name(child.id) in MODEL_NAMES:
                return True
            if isinstance(child, ast.Attribute) and child.attr in MODEL_NAMES:
                return True
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if child.value in MODEL_NAMES or child.value in {
                    "security.AuditEvent", "security.AuditChainHead",
                }:
                    return True
        return False

    calls, references, issues = [], [], []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        name = None
        if isinstance(node, ast.Name):
            name = canonical_name(node.id)
        elif isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.alias):
            name = node.name
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if TABLE.search(value):
                references.append((line, scope(node), "audit-table reference"))
                if SQL_MUTATION.search(value):
                    issues.append((line, "possible direct audit-table SQL mutation"))
            elif value in MODEL_NAMES or value in {"security.AuditEvent", "security.AuditChainHead"}:
                name = value.rsplit(".", 1)[-1]
        if name in MODEL_NAMES:
            references.append((line, scope(node), name))
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        call_name = canonical_name(func.id) if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None
        )
        if call_name in WRITER_NAMES:
            calls.append((line, scope(node), call_name))
            if call_name == "append_audit_event" and path != "security/services.py":
                issues.append((line, "lower-level append called outside central service"))
        if isinstance(func, ast.Attribute) and func.attr in MUTATORS and contains_model(func.value):
            if (path, ast.unparse(node)) not in APPROVED_MODEL_WRITES:
                issues.append((line, "unreviewed direct audit-model mutation"))
        if call_name in MODEL_NAMES and path != "security/audit_chain.py":
            issues.append((line, "audit model constructed outside the chain implementation"))

    if references and path not in REVIEWED_MODEL_ACCESS:
        issues.extend((line, f"unreviewed {name} access") for line, _, name in references)
    return sorted(set(calls)), sorted(set(references)), sorted(set(issues))


def self_test():
    examples = [
        ("unreviewed.py", "from security.models import AuditEvent as E\nE.objects.create(action='CREATE')\n"),
        ("unreviewed.py", "apps.get_model('security', 'AuditEvent').objects.all()\n"),
        ("security/backup_service.py", "cursor.execute('DELETE FROM security_auditevent')\n"),
        ("unreviewed.py", "from security.audit_chain import append_audit_event as write\nwrite()\n"),
        ("security/audit_views.py", "AuditEvent.objects.filter(pk=1).update(reason='x')\n"),
    ]
    for path, source in examples:
        if not inspect_source(path, source)[2]:
            raise AssertionError(f"negative control missed: {path}: {source}")
    positive = [
        ("security/audit_views.py", "AuditEvent.objects.all()\n"),
        ("security/services.py", "append_audit_event()\n"),
        ("security/audit_chain_signals.py",
         "AuditChainHead.objects.using(using).create(pk=1, head_hash=GENESIS_HASH)\n"),
        ("security/backup_service.py", "cursor.execute('SELECT id FROM security_auditevent')\n"),
        ("accounting/services.py", "record_audit_event()\n"),
    ]
    for path, source in positive:
        if inspect_source(path, source)[2]:
            raise AssertionError(f"positive control failed: {path}: {source}")
    print(f"Inventory guard self-tests: {len(examples) + len(positive)} passed")


def main():
    self_test()
    counts = {"runtime": 0, "migration": 0, "test": 0, "excluded": 0}
    callers = {}
    violations = []
    # Walk the actual checkout. Skip dependency and cache directories rather
    # than treating installed third-party Python as project source.
    for path in sorted(BACKEND.rglob("*.py")):
        relative = path.relative_to(BACKEND).as_posix()
        kind = classification(relative)
        if kind == "excluded":
            continue
        counts[kind] += 1
        if kind != "runtime":
            continue
        calls, refs, issues = inspect_source(relative, path.read_text(encoding="utf-8"))
        for line, function, writer in calls:
            print(f"CALL {relative}:{line} {function} -> {writer}")
            if writer == "record_audit_event":
                callers[relative] = callers.get(relative, 0) + 1
        for line, function, name in refs:
            print(f"REFERENCE {relative}:{line} {function} -> {name}")
        violations.extend(f"{relative}:{line}: {message}" for line, message in issues)

    for path in sorted((EXPECTED_BUSINESS | EXPECTED_SECURITY) - callers.keys()):
        violations.append(f"{path}: expected central writer call not found")

    if counts["runtime"] == 0:
        violations.append("no runtime files scanned")

    print(f"Scanned runtime Python files: {counts['runtime']}")
    print(f"Separate migration files: {counts['migration']}; test files: {counts['test']}")
    print(f"Central writer modules: {len(callers)}; syntactic call sites: {sum(callers.values())}")
    print(f"Expected business modules present: {len(EXPECTED_BUSINESS & callers.keys())}/{len(EXPECTED_BUSINESS)}")
    print(f"Expected security modules present: {len(EXPECTED_SECURITY & callers.keys())}/{len(EXPECTED_SECURITY)}")
    print("Scope: static source inventory; manual call graph, transaction and runtime tests remain required.")
    for violation in violations:
        print(f"REVIEW REQUIRED: {violation}", file=sys.stderr)
    if violations:
        print(f"AUDIT WRITER INVENTORY: FAILED ({len(violations)} review findings)", file=sys.stderr)
        return 1
    print("AUDIT WRITER INVENTORY: PASS (static gate only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
