"""Exchange house master identity (Phase 4.4 — operational master).

One ExchangeHouse = one named financial-account relationship with an
external house (§9.3). A stable PK identity with future
currency-separated balances and its own future ledger; currency is a
future transaction/balance dimension, never a master field (OD-5). No
code (OD-7), names may repeat (OD-9), no contact/CRM fields (OD-13), no
relations of any kind (§7 — no Party/Account/Currency FK), no
balance/ledger/posting logic (§8 — those are Phase 11). This master is
NOT a Party (frozen roles; finance excluded from Party) and NOT a COA
account (1210/1220 are example leaves).

No `updated_at`: no master in this repository has one, so per the real
convention this master follows the 4.1/4.2/4.3 shape (`created_at` only).
"""

from django.db import models


class ExchangeHouse(models.Model):
    name = models.CharField(max_length=200)
    name_fa = models.CharField(max_length=200, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(name=""),
                name="exchange_house_name_nonblank",
            ),
        ]

    def __str__(self):
        return self.name
