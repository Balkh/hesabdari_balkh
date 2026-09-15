"""Party master identity (Phase 4.2, Option A — Shared Party + Roles).

One Party = one business/legal identity; Customer/Supplier are ROLES, and
dual-role is allowed (FR-1/FR-2/FR-3). No code (FR-4), bilingual names
per the real repo convention (FR-5: name required, name_fa optional),
inert contact storage (FR-6), single active flag (FR-7). No financial
layer of any kind (FR-8/FR-9 — that is Phase 5).

No `updated_at`: no master in this repository has one (`updated_at` exists
only on the document `NumberSequence` row), so per §3's own rule — real
convention wins, invent nothing — this master follows the 4.1 shape
(`created_at` only). Recorded here and in the 4.2 evidence for review.
"""

from django.db import models


class Party(models.Model):
    name = models.CharField(max_length=200)
    name_fa = models.CharField(max_length=200, blank=True, default="")
    is_customer = models.BooleanField(default=False)
    is_supplier = models.BooleanField(default=False)
    phone = models.CharField(max_length=50, blank=True, default="")
    address = models.CharField(max_length=500, blank=True, default="")
    note = models.CharField(max_length=500, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(name=""), name="party_name_nonblank"
            ),
            models.CheckConstraint(
                condition=models.Q(is_customer=True)
                | models.Q(is_supplier=True),
                name="party_has_role",
            ),
        ]

    def __str__(self):
        return self.name
