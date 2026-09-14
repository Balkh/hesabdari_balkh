"""Unit-of-measure master identity (Phase 4.1).

Measurement-unit identity for products. No code (contract never requires
one — see interpretation record U-3), names are non-unique, no conversion
engine here: conversion data lives on the product as stored reference only.
"""

from django.db import models


class UnitOfMeasure(models.Model):
    name = models.CharField(max_length=200)
    name_fa = models.CharField(max_length=200, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(name=""), name="uom_name_nonblank"
            ),
        ]

    def __str__(self):
        return self.name
