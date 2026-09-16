"""Category master identity (Phase 4.1).

Flat classification for products. No code (contract never requires one —
see interpretation record U-2), names are non-unique, no stock, no
accounting, no behavior of any kind.
"""

from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=200)
    name_fa = models.CharField(max_length=200, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(name=""), name="cat_name_nonblank"
            ),
        ]

    def __str__(self):
        return self.name
