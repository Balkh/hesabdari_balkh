"""Derived stock + AVCO (Phase 6.1) — movement history is the ONLY truth.

- ``stock_for``: SUM of signed quantities per (Product, Warehouse) (§8).
- ``avco_for``: chronological replay with the mandatory zero-stock
  reset (§16/§17): when running quantity reaches zero (or below via an
  OUT leg), the running cost basis is discarded — no hidden remainder
  ever carries into a new cycle. While quantity is positive, OUT legs
  relieve cost at the running 4dp AVCO (exact division, then Half-Up);
  an IN leg arriving while quantity is negative first fills the hole,
  and only the surplus above zero establishes a new basis at the
  receipt's own unit cost. Returns None when quantity is zero or
  negative (no known cost basis → manual temporary cost, §18).
"""

from decimal import Decimal

from django.db.models import Sum

from core.money import quantize_half_up

from .models import StockMovement

AVCO_DECIMALS = 4


def movements_for(product, warehouse):
    """Kardex-ordered posted movements for one (Product, Warehouse)."""
    return StockMovement.objects.filter(
        product=product, warehouse=warehouse
    ).order_by("movement_date", "id")


def stock_for(product, warehouse):
    """Current integer stock derived from immutable movements (§11)."""
    total = movements_for(product, warehouse).aggregate(
        total=Sum("quantity")
    )["total"]
    return int(total or 0)


def avco_for(product, warehouse):
    """4dp AVCO in AFN, or None when there is no known cost basis."""
    quantity = 0
    cost = Decimal("0")
    legs = movements_for(product, warehouse).values(
        "quantity", "unit_cost_afn"
    )
    for leg in legs.iterator():
        units = leg["quantity"]
        unit_afn = leg["unit_cost_afn"]
        if units > 0:
            if quantity >= 0:
                quantity += units
                cost += units * unit_afn
            else:
                quantity += units
                if quantity > 0:
                    cost = quantity * unit_afn
                else:
                    cost = Decimal("0")
        else:
            taken = -units
            if quantity > 0:
                average = quantize_half_up(cost / quantity, AVCO_DECIMALS)
                cost -= min(taken, quantity) * average
                quantity -= taken
                if quantity <= 0:
                    cost = Decimal("0")
                elif cost < 0:
                    # Rounding dust only (relief at rounded AVCO can
                    # overshoot by a fraction of a fils); never a real
                    # negative basis.
                    cost = Decimal("0")
            else:
                quantity -= taken
    if quantity <= 0:
        return None
    return quantize_half_up(cost / quantity, AVCO_DECIMALS)
