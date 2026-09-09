"""Central money/rounding utilities — the ONE rounding engine (Stage 2.2).

Contract: Phase 0 §3.11 (precision) + §3.12 (Half-Up rounding).

Formulas (exact contract notation):
- Line Total    = Round(Qty × Unit Price, 2)
- COGS          = Round(Qty × AVCO, 2)
- FX Equivalent = Round(Amount × Rate, 2)

Rules:
- Only Decimal/str/int inputs are accepted. ``float`` is rejected with
  TypeError because binary floating point cannot represent money exactly.
- All rounding is ROUND_HALF_UP. No banker's rounding, no truncation.
- Exchange-rate storage/display precision is 4; money precision is 2.
"""

from decimal import Decimal, ROUND_HALF_UP

MONEY_DECIMALS = 2
RATE_DECIMALS = 4


def to_decimal(value):
    """Coerce str/int/Decimal to Decimal. Rejects float and anything else."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("Boolean is not a valid monetary value")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value.strip())
    raise TypeError(f"Unsupported monetary type: {type(value).__name__} (float is forbidden)")


def quantize_half_up(value, places):
    """Round ``value`` to ``places`` decimals using ROUND_HALF_UP."""
    quantum = Decimal(1).scaleb(-places)
    return to_decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def line_total(qty, unit_price):
    """Round(Qty × Unit Price, 2)."""
    return quantize_half_up(to_decimal(qty) * to_decimal(unit_price), MONEY_DECIMALS)


def cogs(qty, avco):
    """Round(Qty × AVCO, 2)."""
    return quantize_half_up(to_decimal(qty) * to_decimal(avco), MONEY_DECIMALS)


def fx_equivalent(amount, rate):
    """Round(Amount × Rate, 2)."""
    return quantize_half_up(to_decimal(amount) * to_decimal(rate), MONEY_DECIMALS)


def normalize_rate(rate):
    """Quantize an exchange rate to 4 decimals (Half-Up) for storage."""
    return quantize_half_up(rate, RATE_DECIMALS)


def format_rate(rate):
    """Render an exchange rate at display precision 4 (e.g. '70.0000')."""
    return format(normalize_rate(rate), ".4f")
