"""Warehouse master identity (Phase 4.3 — flat Warehouse master).

One Warehouse = one physical/logical godown identity referenced by name;
documents, reports, and the future inventory layer key off the stable
primary key (§4.15 Kardex "Per Product + Warehouse"). No business code
(OD-1), names may repeat (OD-2), no address/location (OD-3). The COA rows
1410/1420 are posting ACCOUNT names, never warehouse types (§13). No
relations of any kind: the future Inventory layer will reference
Warehouse, never the reverse (§10). No financial or inventory concepts
(§11/§12 — those are future phases).

No `updated_at`: no master in this repository has one, so per the real
convention this master follows the 4.1/4.2 shape (`created_at` only).
"""

from django.db import models


class Warehouse(models.Model):
    name = models.CharField(max_length=200)
    name_fa = models.CharField(max_length=200, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(name=""), name="warehouse_name_nonblank"
            ),
        ]

    def __str__(self):
        return self.name
