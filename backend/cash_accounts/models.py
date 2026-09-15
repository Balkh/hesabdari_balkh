"""Cash account master identity (Phase 4.4 — operational master).

One CashAccount = one physical cash resource (§9.1: "one physical cash
account", "multiple cash accounts"). A stable PK identity referenced by
name in future transfers and internal exchange; currency is a future
transaction/balance dimension, never a master field (OD-5). No code
(OD-6), names may repeat (OD-8), no relations of any kind (§7 — no
Party/Account/Currency FK), no balance/ledger/posting logic (§8 — those
are Phase 11). This master is NOT the COA account 1110: one leaf cannot
be many physical accounts.

No `updated_at`: no master in this repository has one, so per the real
convention this master follows the 4.1/4.2/4.3 shape (`created_at` only).
"""

from django.db import models


class CashAccount(models.Model):
    name = models.CharField(max_length=200)
    name_fa = models.CharField(max_length=200, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(name=""),
                name="cash_account_name_nonblank",
            ),
        ]

    def __str__(self):
        return self.name
