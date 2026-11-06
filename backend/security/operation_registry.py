"""Server-owned W0-2B operation declarations for protected DRF API methods."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Optional

from security.authorization import (
    BINDING_TARGET_FISCAL_PERIOD,
    BINDING_TARGET_LANDED_COST_DOCUMENT,
    BINDING_TARGET_SELF_USER,
    TargetReference,
)
from security.permissions_catalog import CATALOG_BY_KEY

COLLECTION = "COLLECTION"
OBJECT = "OBJECT"
TARGET_NONE = "NONE"
TARGET_URL_KWARG = "URL_KWARG"
TARGET_REQUEST_USER = "REQUEST_USER"

_VALID_TARGET_KINDS = {
    BINDING_TARGET_SELF_USER,
    BINDING_TARGET_FISCAL_PERIOD,
    BINDING_TARGET_LANDED_COST_DOCUMENT,
}
_VALID_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class OperationSpec:
    operation_id: str
    permission_key: str
    binding_kind: str
    target_kind: Optional[str] = None
    target_source: str = TARGET_NONE
    target_kwarg: Optional[str] = None

    def __post_init__(self):
        if not self.operation_id or not self.operation_id.strip():
            raise ValueError("operation_id is required")
        if self.permission_key not in CATALOG_BY_KEY:
            raise ValueError(f"unknown catalog permission key: {self.permission_key}")
        scope_policy = CATALOG_BY_KEY[self.permission_key]["scope_policy"]
        if scope_policy not in {"NONE", "WAREHOUSE_REQUIRED", "OBJECT_REQUIRED"}:
            raise ValueError(f"permission key is not executable: {self.permission_key}")
        if scope_policy == "OBJECT_REQUIRED" and not (
            self.binding_kind == OBJECT
            and self.target_kind == BINDING_TARGET_SELF_USER
            and self.target_source == TARGET_REQUEST_USER
        ):
            raise ValueError(
                "OBJECT_REQUIRED catalog operations must bind the authenticated SELF_USER"
            )
        if scope_policy == "WAREHOUSE_REQUIRED":
            raise ValueError(
                "R2 operation registry has no warehouse-target API operation"
            )
        if self.binding_kind == COLLECTION:
            if self.target_kind is not None or self.target_source != TARGET_NONE or self.target_kwarg is not None:
                raise ValueError("Collection operations cannot declare target metadata")
        elif self.binding_kind == OBJECT:
            if self.target_kind not in _VALID_TARGET_KINDS:
                raise ValueError(f"invalid object target kind: {self.target_kind}")
            if self.target_source not in {TARGET_URL_KWARG, TARGET_REQUEST_USER}:
                raise ValueError("Object operations need a server-side target source")
            if self.target_source == TARGET_URL_KWARG and not self.target_kwarg:
                raise ValueError("URL_KWARG targets require target_kwarg")
            if self.target_source != TARGET_URL_KWARG and self.target_kwarg is not None:
                raise ValueError("target_kwarg is valid only for URL_KWARG")
            if self.target_source == TARGET_REQUEST_USER and self.target_kind != BINDING_TARGET_SELF_USER:
                raise ValueError("REQUEST_USER source is limited to SELF_USER")
            if self.target_source == TARGET_URL_KWARG and self.target_kind == BINDING_TARGET_SELF_USER:
                raise ValueError("SELF_USER targets must come from request.user")
        else:
            raise ValueError(f"invalid binding_kind: {self.binding_kind}")

    def build_target_reference(self, request, view):
        if self.binding_kind == COLLECTION:
            return None
        if self.target_source == TARGET_REQUEST_USER:
            target = getattr(request, "user", None)
            pk = getattr(target, "pk", None)
        else:
            kwargs = getattr(view, "kwargs", {})
            pk = kwargs.get(self.target_kwarg)
        if pk is None:
            return None
        return TargetReference(target_kind=self.target_kind, pk=pk)


_OPERATION_SPECS = {}
OPERATION_SPECS = MappingProxyType(_OPERATION_SPECS)
_METHOD_SPECS_ATTRIBUTE = "erp_operation_specs"


def erp_operations(**method_specs):
    """Attach a mapping of HTTP method to OperationSpec to a DRF @api_view."""
    normalized = {}
    for method, spec in method_specs.items():
        method = method.upper()
        if method not in _VALID_METHODS:
            raise ValueError(f"unsupported explicit HTTP method: {method}")
        if not isinstance(spec, OperationSpec):
            raise TypeError(f"{method} operation must be an OperationSpec")
        if method in normalized:
            raise ValueError(f"duplicate method declaration: {method}")
        normalized[method] = spec
    if not normalized:
        raise ValueError("at least one HTTP method operation is required")

    def decorate(callback):
        view_class = getattr(callback, "cls", None)
        if view_class is None:
            raise TypeError("erp_operations must wrap a DRF @api_view callback")
        existing = getattr(view_class, _METHOD_SPECS_ATTRIBUTE, None)
        if existing:
            raise ValueError("view already has ERP operation metadata")
        handlers = {
            method.upper()
            for method in ("get", "post", "put", "patch", "delete")
            if method in view_class.__dict__
        }
        if set(normalized) != handlers:
            raise ValueError(
                f"operation methods {sorted(normalized)} do not match DRF handlers {sorted(handlers)}"
            )
        for spec in normalized.values():
            current = _OPERATION_SPECS.get(spec.operation_id)
            if current is not None and current != spec:
                raise ValueError(f"duplicate operation_id: {spec.operation_id}")
            _OPERATION_SPECS[spec.operation_id] = spec
        setattr(
            view_class,
            _METHOD_SPECS_ATTRIBUTE,
            MappingProxyType(dict(normalized)),
        )
        return callback

    return decorate
