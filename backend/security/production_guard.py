"""Fail-fast production security configuration guards."""


def require_rbac_enforcement_from_env(raw_value):
    """Return True only when Production explicitly enables ERP RBAC.

    A missing, malformed, or false value must stop settings import. The
    check runs before database configuration so a broken security posture
    cannot be hidden behind a later database-configuration error.
    """
    if not isinstance(raw_value, str) or raw_value.strip().lower() not in {
        "true",
        "false",
    }:
        raise RuntimeError(
            "ERP_RBAC_ENFORCEMENT must be explicitly set to 'true' in "
            "production; missing or malformed values are not accepted"
        )
    if raw_value.strip().lower() != "true":
        raise RuntimeError(
            "Production startup refused: ERP_RBAC_ENFORCEMENT must be "
            "explicitly 'true'. Protected ERP operations must never start "
            "with RBAC enforcement disabled."
        )
    return True
